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
    # Email + password accounts (any email provider). Passwords are scrypt hashes; codes are hashed too.
    password_hash: Mapped[Optional[str]] = mapped_column(String(300))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    code_hash: Mapped[Optional[str]] = mapped_column(String(128))
    code_purpose: Mapped[Optional[str]] = mapped_column(String(20))  # verify | reset
    code_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    code_attempts: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to sign out everywhere
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("shop_id", "email"),)


class Invite(Base, TimestampMixin):
    """A teammate invited by a shop admin. Signing up (or in) with this email joins the shop."""
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20), default="estimator")
    invited_by: Mapped[str] = mapped_column(String(200), default="")
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
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
class Mailbox(Base, TimestampMixin):
    """An email account the app pulls RFQs from.
    kind "msoauth": someone signed in with Microsoft and allowed reading (their own mailbox, or a shared
                    mailbox they have access to); an encrypted refresh token is kept.
    kind "graph":   the deployment's own mailbox app (application permission, one Microsoft 365 company).
    kind "imap":    other providers, with an encrypted app password."""
    __tablename__ = "mailboxes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # msoauth | graph | imap
    address: Mapped[str] = mapped_column(String(320))
    label: Mapped[str] = mapped_column(String(120), default="")
    folder: Mapped[str] = mapped_column(String(200), default="inbox")
    filter_rfqs: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    backfill_days: Mapped[int] = mapped_column(Integer, default=0)  # import this many days of old mail on first sync
    imap_host: Mapped[str] = mapped_column(String(200), default="")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_user: Mapped[str] = mapped_column(String(320), default="")
    imap_password_enc: Mapped[str] = mapped_column(Text, default="")
    oauth_token_enc: Mapped[str] = mapped_column(Text, default="")        # msoauth: encrypted refresh token
    connected_as: Mapped[str] = mapped_column(String(320), default="")    # msoauth: who signed in
    state: Mapped[dict] = mapped_column(JSONType, default=dict)  # delta link, subscription, last uid
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("shop_id", "kind", "address", "folder"),)


class Email(Base, TimestampMixin):
    __tablename__ = "emails"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # graph | imap | upload
    mailbox: Mapped[str] = mapped_column(String(320), default="")  # which connected account it came from
    message_id: Mapped[str] = mapped_column(String(500), index=True)
    sender_name: Mapped[str] = mapped_column(String(300), default="")
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
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
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500))
    rfq: Mapped[Rfq] = relationship(back_populates="attachments")


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


class IntegrationState(Base, TimestampMixin):
    """Graph subscription ids, delta links, IMAP UIDs."""
    __tablename__ = "integration_state"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    state: Mapped[dict] = mapped_column(JSONType, default=dict)
    __table_args__ = (UniqueConstraint("shop_id", "kind"),)
