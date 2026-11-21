"""Email parsing (.eml via the standard library, Outlook .msg via olefile) and RFQ field extraction."""
from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

import olefile


@dataclass
class ParsedEmail:
    message_id: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    received_at: datetime
    attachments: list = field(default_factory=list)       # (name, bytes) tuples or intake.files.Incoming
    thread_id: str = ""                                    # Gmail threadId / Graph conversationId / References root
    remote_id: str = ""                                    # provider message id, to fetch the files again


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    import html as h
    return re.sub(r"\n{3,}", "\n\n", h.unescape(text)).strip()


def parse_eml(data: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    try:
        when = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        when = datetime.now(timezone.utc)
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = _html_to_text(body)
    atts = []
    for a in msg.iter_attachments():
        fn = a.get_filename() or "attachment"
        payload = a.get_payload(decode=True) or b""
        if a.get_content_type() == "message/rfc822" and not payload:
            continue
        atts.append((fn, payload))
    mid = str(msg.get("Message-ID") or f"<{hash(data)}@upload>")
    return ParsedEmail(mid.strip(), name or addr, addr, str(msg.get("Subject", "")), body.strip(), when, atts)


# ---- Outlook .msg (MS-OXMSG compound file)
def _msg_str(ole, prefix, prop):
    for typ, enc in (("001F", "utf-16-le"), ("001E", "latin-1")):
        p = f"{prefix}__substg1.0_{prop}{typ}"
        if ole.exists(p):
            return ole.openstream(p).read().decode(enc, "replace").rstrip("\x00")
    return ""


def parse_msg(data: bytes) -> ParsedEmail:
    ole = olefile.OleFileIO(data)
    subject = _msg_str(ole, "", "0037")
    body = _msg_str(ole, "", "1000")
    if not body and ole.exists("__substg1.0_10130102"):
        body = _html_to_text(ole.openstream("__substg1.0_10130102").read().decode("utf-8", "replace"))
    name = _msg_str(ole, "", "0C1A")
    addr = _msg_str(ole, "", "5D01") or _msg_str(ole, "", "0C1F")
    headers = _msg_str(ole, "", "007D")
    mid = (re.search(r"(?im)^message-id:\s*(\S+)", headers) or [None, ""])[1] or f"<msg-{hash(data)}@upload>"
    when = datetime.now(timezone.utc)
    dm = re.search(r"(?im)^date:\s*(.+)$", headers)
    if dm:
        try:
            when = parsedate_to_datetime(dm[1].strip())
        except (TypeError, ValueError):
            pass
    atts = []
    for entry in ole.listdir(streams=False, storages=True):
        if len(entry) == 1 and entry[0].startswith("__attach_version1.0_"):
            pre = entry[0] + "/"
            fn = _msg_str(ole, pre, "3707") or _msg_str(ole, pre, "3704") or "attachment"
            dp = pre + "__substg1.0_37010102"
            if ole.exists(dp):
                atts.append((fn, ole.openstream(dp).read()))
    return ParsedEmail(mid, name or addr, addr, subject, body.strip(), when, atts)


def parse_email_file(filename: str, data: bytes) -> ParsedEmail:
    return parse_msg(data) if filename.lower().endswith(".msg") else parse_eml(data)


# ---- deterministic field extraction (AI refines these when configured)
MONTHS = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
DATE = rf"(\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})\.?,?\s+\d{{4}}|(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}})"
SUFFIX = r"(?:Ltd|Limited|Inc|LLC|GmbH|AG|SA|AS|AB|BV|NV|Oy|SpA|Srl|s\.r\.o\.|Corp(?:oration)?|Co\.?|Company|Plc|PLC|Pty|Systems|Industries|Engineering|Manufacturing|Aerospace|Robotics|Marine|Pumps|Medical|Hydraulics|Automation|Instruments)"


def _f(value, conf, evidence, source="email-pattern"):
    return {"value": value, "confidence": conf, "evidence": (evidence or "")[:240], "source": source}


def _line(text, idx):
    s = text.rfind("\n", 0, idx) + 1
    e = text.find("\n", idx)
    return text[s:e if e >= 0 else len(text)].strip()


def extract_fields(subject: str, body: str, sender_name: str, sender_email: str, filenames: list[str]) -> dict:
    text = (subject or "") + "\n" + (body or "")
    out: dict = {}
    sig = "\n".join((body or "").split("\n\n")[-2:])
    m = re.search(rf"^[ \t]*(?:[^\n,]*,[ \t]*)?([A-Z][\w&.'-]*(?:[ \t]+[A-Z][\w&.'-]*){{0,4}}[ \t]+{SUFFIX})\.?[ \t]*$", sig, re.M)
    if m:
        out["customer_name"] = _f(m[1].strip(), 0.75, _line(sig, m.start(1)))
    elif sender_email and "@" in sender_email:
        dom = sender_email.split("@")[1].split(".")[0]
        out["customer_name"] = _f(dom.replace("-", " ").title(), 0.35, f"from sender domain {sender_email.split('@')[1]}")
    if sender_name:
        out["customer_contact"] = _f(sender_name, 0.9, "From: " + sender_name)
    m = re.search(r"\b(?:RFQ|RFP|request for quot\w*|enquiry|inquiry)[ \t]*(?:no\.?|number|ref(?:erence)?|#)?[ \t]*[:#]?[ \t]*([A-Z0-9][A-Z0-9][A-Z0-9\-/_.]{2,24})", text, re.I)
    if m and re.search(r"\d", m[1]):
        out["customer_rfq_no"] = _f(m[1].rstrip(".,"), 0.8, _line(text, m.start()))
    pns, ev = [], ""
    for m in re.finditer(r"\b(?:P/N|PN|part(?:\s*(?:no\.?|number|#))?|drawing(?:\s*(?:no\.?|number))?)\s*[:#]?\s*([A-Z]{1,6}[-_]?\d[\w\-]{1,20})", text, re.I):
        pns.append(m[1].rstrip(".,"))
        ev = ev or _line(text, m.start())
    for fn in filenames:
        mm = re.match(r"^([A-Z]{2,6}-\d{3,6}(?:-\d{1,3})?)", fn, re.I)
        if mm:
            pns.append(mm[1].upper())
    if pns:
        out["part_numbers"] = _f(", ".join(dict.fromkeys(pns)), 0.8 if ev else 0.55, ev or "from attachment names")
    m = re.search(r"\brev(?:ision)?\.?\s*[:#]?\s*([A-Z]{1,2}\d?|\d{1,2})\b", text, re.I)
    if m:
        out["revision"] = _f(m[1].upper(), 0.7, _line(text, m.start()))
    qty, qev = [], ""
    NUM = r"(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)"
    for m in re.finditer(rf"\b(?:qty|quantity|quantities)\s*[:=]?\s*({NUM}(?:\s*(?:/|,|and|&|\+|or)\s*{NUM})*)|\b({NUM})\s*(?:pcs|pieces|off|units|ea|parts|sets|assemblies)\b", text, re.I):
        for n in re.findall(NUM, m[1] or m[2]):
            v = int(n.replace(",", ""))
            if 0 < v < 10_000_000 and v not in qty:
                qty.append(v)
        qev = qev or _line(text, m.start())
    if qty:
        out["quantities"] = _f(sorted(qty), 0.75, qev)
    non_quote = "\n".join(l for l in text.split("\n") if not re.search(r"quot|respond|reply|return|submit|bid", l, re.I))
    m = re.search(rf"(?:deliver\w*|required\s+by|need(?:ed)?\s+by|due\s+date|ship\w*)[^\n]{{0,60}}?{DATE}", non_quote, re.I)
    if m:
        out["due_date"] = _f(m[1], 0.7, _line(non_quote, m.start()))
    else:
        m = re.search(r"\blead\s*time[^\n]{0,30}?(\d+\s*(?:weeks?|wks?|days?))", text, re.I)
        if m:
            out["due_date"] = _f(m[1], 0.6, _line(text, m.start()))
    m = re.search(rf"(?:quot\w*|respond|response|reply|return|submit|bid)[^\n]{{0,50}}?(?:by|before|no later than|deadline|due)\s*:?\s*{DATE}", text, re.I)
    if m:
        out["quote_due"] = _f(m[1], 0.75, _line(text, m.start()))
    m = re.search(r"\b(?:material|matl)[ \t]*[:\-][ \t]*([^\n.;,]{3,60})", text, re.I)
    if m:
        out["material"] = _f(m[1].strip(), 0.75, _line(text, m.start()))
    procs = re.findall(r"\b(anodi[sz]e[^\n.;]{0,40}|hard\s*coat\w*|black\s*oxide|passivat\w*|zinc\s*plat\w*|nickel\s*plat\w*|chem(?:ical)?\s*film|alodine|powder\s*coat\w*|heat\s*treat\w*[^\n.;]{0,30}|\d{2}\s*-\s*\d{2}\s*HRC|bead\s*blast\w*)", text, re.I)
    if procs:
        out["special_processes"] = _f("; ".join(dict.fromkeys(p.strip() for p in procs)), 0.75, "found in email")
    reqs = re.findall(r"\b(material\s*cert\w*|3\.1\s*cert\w*|EN\s*10204|certificate of conformity|C\s?of\s?C|first article[^\n.;]{0,25}|AS9102|PPAP|ITAR|AS9100\w*|ISO\s*13485|NADCAP|CMM\s*report)", text, re.I)
    if reqs:
        out["requirements"] = _f("; ".join(dict.fromkeys(r.strip() for r in reqs)), 0.75, "found in email")
    if re.search(r"\bITAR\b|export[- ]controlled|EAR99", text, re.I):
        out["itar"] = _f(True, 0.8, "export-control wording in email")
    return out
