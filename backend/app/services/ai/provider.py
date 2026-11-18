"""AI extraction behind a provider interface. The AI only EXTRACTS (email fields, drawing callouts);
it never sets prices. Results carry confidence scores and drawing locations, and are merged with the
deterministic text-layer results, which take precedence.

Configured with ANTHROPIC_API_KEY. Without it, NullProvider is used and the app runs on
deterministic extraction only. RFQs flagged as export-controlled (ITAR) are never sent.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Protocol

from ...config import get_settings

log = logging.getLogger(__name__)

_M = {"type": "object", "additionalProperties": False, "required": ["value", "confidence", "bbox"],
      "properties": {"value": {"type": ["string", "null"]}, "confidence": {"type": "number"},
                     "bbox": {"type": ["array", "null"], "items": {"type": "number"}}}}
DRAWING_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["meta", "items", "unreadable", "notes"],
    "properties": {
        "meta": {"type": "object", "additionalProperties": False,
                 "required": ["drawing_number", "description", "revision", "units", "material", "general_tolerance", "surface_finish", "heat_treatment", "coating", "overall_length", "overall_width", "overall_height"],
                 "properties": {k: _M for k in ["drawing_number", "description", "revision", "units", "material", "general_tolerance", "surface_finish", "heat_treatment", "coating", "overall_length", "overall_width", "overall_height"]}},
        "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["cat", "label", "value", "tol", "qty", "critical", "confidence", "bbox"],
                                              "properties": {"cat": {"type": "string", "enum": ["dimension", "diameter", "radius", "hole", "thread", "slot", "pocket", "wall", "gdt", "finish", "fit", "weld", "note", "coating", "heat", "standard"]},
                                                             "label": {"type": "string"}, "value": {"type": "string"}, "tol": {"type": ["string", "null"]},
                                                             "qty": {"type": ["integer", "null"]}, "critical": {"type": "boolean"}, "confidence": {"type": "number"},
                                                             "bbox": {"type": ["array", "null"], "items": {"type": "number"}}}}},
        "unreadable": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["description", "bbox"],
                                                   "properties": {"description": {"type": "string"}, "bbox": {"type": ["array", "null"], "items": {"type": "number"}}}}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}
_F = {"type": "object", "additionalProperties": False, "required": ["value", "confidence", "evidence", "ambiguous"],
      "properties": {"value": {"type": ["string", "null"]}, "confidence": {"type": "number"}, "evidence": {"type": "string"}, "ambiguous": {"type": "boolean"}}}
EMAIL_KEYS = ["customer_name", "customer_contact", "customer_rfq_no", "part_numbers", "revision", "quantities", "due_date", "quote_due", "material", "special_processes", "requirements"]
EMAIL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fields", "summary", "parts"],
                "properties": {"fields": {"type": "object", "additionalProperties": False, "required": EMAIL_KEYS, "properties": {k: _F for k in EMAIL_KEYS}},
                               "summary": {"type": "string"},
                               "parts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["part_number", "revision", "quantities", "material"],
                                                                    "properties": {"part_number": {"type": "string"}, "revision": {"type": ["string", "null"]},
                                                                                   "quantities": {"type": "array", "items": {"type": "integer"}}, "material": {"type": ["string", "null"]}}}}}}

RULES = ("Use only information present in the supplied material. Never invent dimensions, tolerances, materials, quantities or dates. "
         "If something is not shown or not legible, use null (or list it as unreadable). Confidence is 0.0-1.0: how sure you are the value is exactly as written.")


class AIProvider(Protocol):
    name: str
    def available(self) -> bool: ...
    def extract_email(self, subject: str, body: str, sender: str, filenames: list[str]) -> dict | None: ...
    def read_drawing(self, page_pngs: list[bytes], text_layer: str, filename: str) -> dict | None: ...


class NullProvider:
    name = "none"
    def available(self): return False
    def extract_email(self, *a, **k): return None
    def read_drawing(self, *a, **k): return None


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.model = model

    def available(self):
        return True

    def _json(self, content: list, schema: dict, effort: str = "medium") -> dict | None:
        a = self._anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model, max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": content}],
            )
        except a.RateLimitError:
            log.warning("AI rate limited")
            raise
        except (a.BadRequestError, a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError) as e:
            log.error("AI request rejected: %s", e)
            return None
        except (a.APIStatusError, a.APIConnectionError) as e:
            log.error("AI request failed: %s", e)
            raise
        if resp.stop_reason == "refusal":
            log.warning("AI declined request (%s)", getattr(resp.stop_details, "category", None))
            return None
        if resp.stop_reason == "max_tokens":
            log.warning("AI output truncated")
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None

    def extract_email(self, subject, body, sender, filenames):
        prompt = (f"You extract RFQ (request for quotation) data from a customer email sent to a CNC machine shop.\n{RULES}\n"
                  f"From: {sender}\nSubject: {subject}\nAttachments: {', '.join(filenames) or 'none'}\n---\n{body[:20000]}\n---\n"
                  "Quantities: list every quantity break requested. Dates: keep the customer's wording and append the ISO date in brackets when unambiguous. "
                  "Set ambiguous=true when the email is unclear or contradicts itself. 'parts' lists each part the customer wants quoted.")
        return self._json([{"type": "text", "text": prompt}], EMAIL_SCHEMA, effort="low")

    def read_drawing(self, page_pngs, text_layer, filename):
        content: list = []
        for png in page_pngs[:2]:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()}})
        content.append({"type": "text", "text": (
            f"You are a senior manufacturing engineer reading an engineering drawing ({filename}) to quote it for CNC machining.\n{RULES}\n"
            "Coordinates: bbox is [x0, y0, x1, y1] as integers 0-1000 relative to the FIRST image (full sheet), origin top-left.\n"
            + (f"Text layer of the file (exact characters; positions unknown):\n\"\"\"\n{text_layer[:25000]}\n\"\"\"\n" if text_layer else "The file has no text layer (scan); read everything from the image.\n")
            + "Extract the title block, every toleranced dimension, hole callout (with quantity), thread, fit, GD&T frame, surface finish, coating, "
              "heat treatment, weld symbol and manufacturing note. overall_length/width/height only if dimensioned. Mark critical=true for GD&T, fits and "
              "tolerance bands tighter than 0.05 mm (0.002 in). At most 80 items.")})
        return self._json(content, DRAWING_SCHEMA, effort="medium")


def get_provider() -> AIProvider:
    s = get_settings()
    if s.ai_enabled and s.anthropic_api_key:
        return AnthropicProvider(s.anthropic_api_key, s.ai_model)
    return NullProvider()
