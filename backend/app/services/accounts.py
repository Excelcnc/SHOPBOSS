"""Email + password accounts that work with any email provider.

Sign-up: email, password, name, shop name -> a 6-digit code is emailed -> entering it verifies the
address and signs in. Someone invited by a shop admin joins that shop instead of creating a new one.
Sessions are signed tokens (HS256 with SECRET_KEY); bumping users.token_version signs a user out
everywhere (password reset does this).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Invite, Shop, User
from . import mailer
from .shopdata import seed_shop

log = logging.getLogger(__name__)
ISSUER = "cncquote"
CODE_MINUTES = 15
MAX_CODE_ATTEMPTS = 5
MAX_FAILED_LOGINS = 8
LOCK_MINUTES = 15
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
now = lambda: datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


# ---------------------------------------------------------------- passwords & codes
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(pw: str, stored: str | None) -> bool:
    try:
        _, salt, h = (stored or "").split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except ValueError:
        return False


def password_problem(pw: str) -> str | None:
    if len(pw) < 10:
        return "Use at least 10 characters for the password."
    if len(pw) > 200:
        return "Password is too long."
    return None


def _code_hash(user: User, code: str) -> str:
    return hmac.new(_secret().encode(), f"{user.id}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_code(db: Session, user: User, purpose: str) -> str:
    code = f"{secrets.randbelow(10**6):06d}"
    user.code_hash, user.code_purpose = _code_hash(user, code), purpose
    user.code_expires, user.code_attempts = now() + timedelta(minutes=CODE_MINUTES), 0
    db.commit()
    s = get_settings()
    link = f"\n\nOr open {s.app_url.rstrip('/')}" if s.app_url else ""
    if purpose == "verify":
        mailer.send(user.email, f"Your CNC Quote code: {code}",
                    f"Hello {user.name or ''},\n\nYour CNC Quote verification code is {code}\nIt expires in {CODE_MINUTES} minutes.{link}\n\n"
                    "If you didn't create an account, ignore this email.")
    else:
        mailer.send(user.email, f"Reset your CNC Quote password: {code}",
                    f"Your CNC Quote password reset code is {code}\nIt expires in {CODE_MINUTES} minutes.\n\n"
                    "If you didn't ask to reset your password, ignore this email; your password has not changed.")
    return code


def use_code(db: Session, user: User | None, code: str, purpose: str):
    bad = HTTPException(400, "That code is wrong or has expired. Ask for a new code.")
    if not user or not user.code_hash or user.code_purpose != purpose:
        raise bad
    if user.code_attempts >= MAX_CODE_ATTEMPTS or _aware(user.code_expires) < now():
        raise bad
    if not hmac.compare_digest(user.code_hash, _code_hash(user, re.sub(r"\D", "", code or ""))):
        user.code_attempts += 1
        db.commit()
        raise bad
    user.code_hash = user.code_purpose = user.code_expires = None
    user.code_attempts = 0


# ---------------------------------------------------------------- sessions
def _secret() -> str:
    s = get_settings()
    if s.secret_key:  # derived key: never the same bytes as the mailbox-password encryption key
        return hashlib.sha256(b"sessions:" + s.secret_key.encode()).hexdigest()
    if s.dev:
        return "dev-only-insecure-key-0123456789abcdef"
    raise HTTPException(500, "SECRET_KEY is not set on the server.")


def make_token(user: User) -> str:
    s = get_settings()
    claims = {"iss": ISSUER, "sub": user.id, "ver": user.token_version or 0, "exp": now() + timedelta(days=s.session_days)}
    return jwt.encode(claims, _secret(), algorithm="HS256")


def is_local_token(token: str) -> bool:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss") == ISSUER
    except jwt.PyJWTError:
        return False


def user_from_token(db: Session, token: str) -> User:
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"], issuer=ISSUER)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Sign in required")
    user = db.get(User, claims.get("sub"))
    if not user or not user.active or (user.token_version or 0) != claims.get("ver"):
        raise HTTPException(401, "Sign in required")
    return user


# ---------------------------------------------------------------- accounts
def normalize(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 320:
        raise HTTPException(400, "Enter a valid email address.")
    return e


def find(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email, User.password_hash.is_not(None)).order_by(User.created_at))


def pending_invite(db: Session, email: str) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.email == email, Invite.accepted_at.is_(None)).order_by(Invite.created_at.desc()))


def signup(db: Session, email: str, password: str, name: str, shop_name: str) -> tuple[User, bool]:
    """Returns (user, needs_code). Re-signing up before verifying just updates the details."""
    s = get_settings()
    email = normalize(email)
    if (p := password_problem(password)):
        raise HTTPException(400, p)
    user = find(db, email)
    if user and (user.email_verified or (user.last_login_at and not mailer.enabled())):
        raise HTTPException(409, "An account with this email already exists. Sign in, or use 'Forgot password'.")
    inv = pending_invite(db, email)
    if not user:
        if not inv and not s.signup_open:
            raise HTTPException(403, "New sign-ups are by invitation only. Ask your shop admin to invite you.")
        if inv:
            shop, role = db.get(Shop, inv.shop_id), inv.role
        else:
            if not (shop_name or "").strip():
                raise HTTPException(400, "Enter your shop's name.")
            shop, role = seed_shop(db, shop_name.strip()[:200]), "admin"
        user = db.scalar(select(User).where(User.shop_id == shop.id, User.email == email))  # e.g. used Microsoft sign-in before
        if not user:
            user = User(shop_id=shop.id, email=email, role=role)
            db.add(user)
    user.name = (name or "").strip()[:200] or email.split("@")[0]
    user.password_hash = hash_password(password)
    db.flush()
    if mailer.enabled():
        issue_code(db, user, "verify")
        return user, True
    log.warning("SMTP not configured: %s signed up without email verification", email)
    _accept(db, user, proven=False)
    return user, False


def _accept(db: Session, user: User, proven: bool):
    """Account usable. email_verified is only set when the person proved the address with a code."""
    if proven:
        user.email_verified = True
    inv = db.scalar(select(Invite).where(Invite.email == user.email, Invite.shop_id == user.shop_id, Invite.accepted_at.is_(None)))
    if inv:
        inv.accepted_at = now()
    user.last_login_at = now()
    db.commit()


def verify(db: Session, email: str, code: str) -> User:
    user = find(db, normalize(email))
    use_code(db, user, code, "verify")
    _accept(db, user, proven=True)
    return user


def login(db: Session, email: str, password: str) -> User:
    email = normalize(email)
    user = find(db, email)
    wrong = HTTPException(401, "Email or password is wrong.")
    if not user or not user.active:
        check_password(password, hash_password("timing-equalizer"))
        raise wrong
    if user.locked_until and _aware(user.locked_until) > now():
        raise HTTPException(429, f"Too many wrong passwords. Try again in {LOCK_MINUTES} minutes, or reset your password.")
    if not check_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until, user.failed_logins = now() + timedelta(minutes=LOCK_MINUTES), 0
        db.commit()
        raise wrong
    user.failed_logins, user.locked_until = 0, None
    if not user.email_verified and mailer.enabled():
        issue_code(db, user, "verify")
        raise HTTPException(403, "verify")
    user.last_login_at = now()
    db.commit()
    return user


def forgot(db: Session, email: str):
    user = find(db, normalize(email))
    if user and user.active:  # same answer either way: don't reveal who has an account
        issue_code(db, user, "reset")


def reset(db: Session, email: str, code: str, password: str) -> User:
    if (p := password_problem(password)):
        raise HTTPException(400, p)
    user = find(db, normalize(email))
    use_code(db, user, code, "reset")
    user.password_hash = hash_password(password)
    user.token_version = (user.token_version or 0) + 1
    user.failed_logins, user.locked_until = 0, None
    _accept(db, user, proven=True)  # receiving the code proves the address
    return user


def invite(db: Session, admin: User, email: str, role: str) -> Invite:
    email = normalize(email)
    if role not in ("admin", "estimator"):
        raise HTTPException(400, "Role must be admin or estimator.")
    if db.scalar(select(User).where(User.shop_id == admin.shop_id, User.email == email)):
        raise HTTPException(409, "That person is already on your team.")
    other = find(db, email)
    if other and other.shop_id != admin.shop_id:
        raise HTTPException(409, "That email already has an account with another shop.")
    inv = db.scalar(select(Invite).where(Invite.shop_id == admin.shop_id, Invite.email == email))
    if not inv:
        inv = Invite(shop_id=admin.shop_id, email=email)
        db.add(inv)
    inv.role, inv.invited_by, inv.accepted_at = role, admin.name or admin.email, None
    db.commit()
    s = get_settings()
    shop = db.get(Shop, admin.shop_id)
    where = s.app_url.rstrip("/") or "the CNC Quote website"
    mailer.send(email, f"{admin.name or admin.email} invited you to {shop.name} on CNC Quote",
                f"{admin.name or admin.email} invited you to quote with {shop.name} on CNC Quote.\n\n"
                f"Open {where} and choose 'Create account' with this email address ({email}).")
    return inv
