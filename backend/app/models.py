"""Database schema. Every business table carries shop_id so many shops can share one deployment."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def uid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


# ---------------------------------------------------------------- shop setup
class Shop(Base, TimestampMixin):
    __tablename__ = "shops"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    units: Mapped[str] = mapped_column(String(8), default="mm")
    # pricing policy: margin, contingency, rounding, minimums, volume tiers, estimating factors
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="estimator")  # admin | estimator | viewer
    external_id: Mapped[Optional[str]] = mapped_column(String(200), index=True)  # Entra object id / GitHub id
    # may open files marked ITAR / CUI / export-controlled (granted by a shop admin; every view is audited)
    export_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("shop_id", "email"),)


class RateType(Base, TimestampMixin):
    """Hourly rates: milling, turning, 5-axis, setup, programming, inspection, plus any custom rate."""
    __tablename__ = "rate_types"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    rate_per_hour: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("shop_id", "key"),)


class Machine(Base, TimestampMixin):
    __tablename__ = "machines"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # mill3 | mill4 | mill5 | lathe | millturn | swiss
    rate_key: Mapped[str] = mapped_column(String(50), default="milling")
    travel_mm: Mapped[list] = mapped_column(JSONType, default=list)  # [x, y, z] or [max dia, max length] for lathes
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict)  # e.g. {"live_tooling": true, "bar_capacity_mm": 65}
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Material(Base, TimestampMixin):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[Optional[str]] = mapped_column(ForeignKey("shops.id"), index=True)  # null = global reference row
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list] = mapped_column(JSONType, default=list)
    family: Mapped[str] = mapped_column(String(30))  # aluminum, steel, stainless, titanium, copper, plastic, nickel
    density_g_cm3: Mapped[float] = mapped_column(Float)
    machinability: Mapped[float] = mapped_column(Float, default=1.0)  # removal rate relative to 6061 = 1.0
    reference_price_per_kg: Mapped[float] = mapped_column(Float)      # market reference
    reference_price_date: Mapped[Optional[str]] = mapped_column(String(10))
    shop_price_per_kg: Mapped[Optional[float]] = mapped_column(Float)  # shop override wins
    shop_price_date: Mapped[Optional[str]] = mapped_column(String(10))


class OutsideProcess(Base, TimestampMixin):
    __tablename__ = "outside_processes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    keywords: Mapped[list] = mapped_column(JSONType, default=list)  # drawing/email words that trigger it
    supplier: Mapped[str] = mapped_column(String(120), default="")
    basis: Mapped[str] = mapped_column(String(20), default="per_part")  # per_part | per_kg | per_dm2 | per_lot
    price: Mapped[float] = mapped_column(Float, default=0.0)
    lot_charge: Mapped[float] = mapped_column(Float, default=0.0)     # minimum / setup charge per lot
    lead_days: Mapped[int] = mapped_column(Integer, default=5)
    markup_pct: Mapped[float] = mapped_column(Float, default=15.0)


# ---------------------------------------------------------------- intake
class Email(Base, TimestampMixin):
    __tablename__ = "emails"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # graph | imap | upload
    message_id: Mapped[str] = mapped_column(String(500), index=True)
    sender_name: Mapped[str] = mapped_column(String(300), default="")
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    thread_id: Mapped[str] = mapped_column(String(500), default="", index=True)   # Gmail threadId / Graph conversationId
    mailbox_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    remote_id: Mapped[str] = mapped_column(String(500), default="")                # provider message id (for re-fetching)
    __table_args__ = (UniqueConstraint("shop_id", "message_id"),)


class Rfq(Base, TimestampMixin):
    __tablename__ = "rfqs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | estimating | quoted | won | lost
    customer_name: Mapped[str] = mapped_column(String(300), default="")
    customer_contact: Mapped[str] = mapped_column(String(300), default="")
    customer_email: Mapped[str] = mapped_column(String(320), default="")
    customer_rfq_no: Mapped[str] = mapped_column(String(100), default="")
    due_date: Mapped[Optional[str]] = mapped_column(String(40))
    email_id: Mapped[Optional[str]] = mapped_column(ForeignKey("emails.id"))
    extracted: Mapped[dict] = mapped_column(JSONType, default=dict)  # field -> {value, confidence, source, evidence}
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | done | error
    analysis_error: Mapped[Optional[str]] = mapped_column(Text)
    assigned_to: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="rfq", cascade="all, delete-orphan")
    parts: Mapped[list["Part"]] = relationship(back_populates="rfq", cascade="all, delete-orphan")


class Attachment(Base, TimestampMixin):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"), index=True)
    filename: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(20))  # model | drawing | email | other
    ext: Mapped[str] = mapped_column(String(12))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    storage_key: Mapped[str] = mapped_column(String(500), default="")   # "" until the bytes are stored
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    # fetching | stored | analyzing | ready | download_only | needs_manual | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="stored")
    status_reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="upload")   # upload | graph | gmail | imap | link | portal
    origin: Mapped[str] = mapped_column(String(300), default="")         # zip:x.zip, eml:fwd.eml, link:dropbox ...
    email_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    mailbox_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    source_ref: Mapped[dict] = mapped_column(JSONType, default=dict)     # how to fetch it again (message/attachment ids, url)
    export_controlled: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_id: Mapped[Optional[str]] = mapped_column(String(32))     # earlier revision of the same file in this RFQ
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rfq: Mapped[Rfq] = relationship(back_populates="attachments")

    @property
    def stored(self) -> bool:
        return bool(self.storage_key)


# ---------------------------------------------------------------- parts & analysis
class Part(Base, TimestampMixin):
    __tablename__ = "parts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"), index=True)
    part_number: Mapped[str] = mapped_column(String(120), default="")
    revision: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(20), default="machined")  # machined | assembly | purchased
    parent_part_id: Mapped[Optional[str]] = mapped_column(ForeignKey("parts.id"))
    qty_per_parent: Mapped[int] = mapped_column(Integer, default=1)
    model_attachment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("attachments.id"))
    drawing_attachment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("attachments.id"))
    match: Mapped[dict] = mapped_column(JSONType, default=dict)         # model<->drawing pairing evidence
    cad: Mapped[dict] = mapped_column(JSONType, default=dict)           # geometry summary + features
    drawing: Mapped[dict] = mapped_column(JSONType, default=dict)       # extracted callouts + title block
    material_code: Mapped[Optional[str]] = mapped_column(String(50))
    material_source: Mapped[dict] = mapped_column(JSONType, default=dict)
    processes: Mapped[list] = mapped_column(JSONType, default=list)     # detected outside processes
    warnings: Mapped[list] = mapped_column(JSONType, default=list)
    vector: Mapped[list] = mapped_column(JSONType, default=list)        # similarity features
    purchased: Mapped[dict] = mapped_column(JSONType, default=dict)     # for purchased components: vendor, cost
    rfq: Mapped[Rfq] = relationship(back_populates="parts")


# ---------------------------------------------------------------- quoting
class Quote(Base, TimestampMixin):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"), index=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("parts.id"), index=True)
    versions: Mapped[list["QuoteVersion"]] = relationship(back_populates="quote", cascade="all, delete-orphan", order_by="QuoteVersion.number")


class QuoteVersion(Base, TimestampMixin):
    """Each 'Save As' creates a new version; the original is never overwritten."""
    __tablename__ = "quote_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120), default="Original")
    parent_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("quote_versions.id"))
    inputs: Mapped[dict] = mapped_column(JSONType, default=dict)     # material, quantities, rate snapshot, process list
    overrides: Mapped[dict] = mapped_column(JSONType, default=dict)  # key -> {value, by, at, reason}
    result: Mapped[dict] = mapped_column(JSONType, default=dict)     # full calculation for each quantity
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | final | sent
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    quote: Mapped[Quote] = relationship(back_populates="versions")


class QuoteOutput(Base, TimestampMixin):
    """Frozen customer-facing lines: Part #, Rev, Qty, Price."""
    __tablename__ = "quote_outputs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"), index=True)
    quote_number: Mapped[str] = mapped_column(String(40))
    lines: Mapped[list] = mapped_column(JSONType, default=list)
    valid_until: Mapped[Optional[str]] = mapped_column(String(10))
    notes: Mapped[str] = mapped_column(Text, default="")
    pdf_key: Mapped[Optional[str]] = mapped_column(String(500))


# ---------------------------------------------------------------- history
class HistoricalJob(Base, TimestampMixin):
    __tablename__ = "historical_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="import")  # import | quote | jobboss
    external_ref: Mapped[str] = mapped_column(String(120), default="")
    part_number: Mapped[str] = mapped_column(String(120), default="")
    revision: Mapped[str] = mapped_column(String(20), default="")
    customer: Mapped[str] = mapped_column(String(300), default="")
    material: Mapped[str] = mapped_column(String(120), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    est_hours: Mapped[Optional[float]] = mapped_column(Float)
    actual_hours: Mapped[Optional[float]] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(10), default="")  # won | lost | ''
    job_date: Mapped[Optional[str]] = mapped_column(String(10))
    attributes: Mapped[dict] = mapped_column(JSONType, default=dict)  # size, complexity, features when known
    vector: Mapped[list] = mapped_column(JSONType, default=list)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[Any] = mapped_column(JSONType, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Mailbox(Base, TimestampMixin):
    """A linked mailbox (read-only). Tokens are encrypted at rest (app/crypto.py) and never logged or returned by the API."""
    __tablename__ = "mailboxes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    provider: Mapped[str] = mapped_column(String(10))                  # gmail | graph
    auth: Mapped[str] = mapped_column(String(10), default="oauth")     # oauth (delegated, per user) | app (Graph application permission)
    address: Mapped[str] = mapped_column(String(320), default="")
    token_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="connected")   # connected | error | reconnect | disabled
    last_error: Mapped[str] = mapped_column(Text, default="")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    backfill_days: Mapped[int] = mapped_column(Integer, default=0)
    # None = default RFQ keywords; "" = every message with files or links (dedicated quoting mailbox)
    keywords: Mapped[Optional[str]] = mapped_column(Text, default=None)
    state: Mapped[dict] = mapped_column(JSONType, default=dict)        # gmail history id / graph delta link
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("shop_id", "provider", "address"),)


class IntegrationState(Base, TimestampMixin):
    """Graph subscription ids, delta links, IMAP UIDs."""
    __tablename__ = "integration_state"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    state: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("shop_id", "kind"),)
