"""Public sign-up / sign-in endpoints and the shop's team (users and invitations)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..config import get_settings
from ..db import get_db
from ..models import Invite, User
from ..services import accounts, mailer

router = APIRouter(prefix="/api")


@router.get("/config")
def public_config():
    """What the sign-in screen needs. No secrets."""
    s = get_settings()
    return {"dev": s.dev, "signup_open": s.signup_open, "email_verification": mailer.enabled(),
            "microsoft": {"client_id": s.entra_client_id, "tenant": s.entra_tenant_id or "organizations"} if s.entra_client_id else None}


class SignupIn(BaseModel):
    email: str
    password: str
    name: str = ""
    shop_name: str = ""


class EmailIn(BaseModel):
    email: str


class CodeIn(BaseModel):
    email: str
    code: str


class LoginIn(BaseModel):
    email: str
    password: str


class ResetIn(BaseModel):
    email: str
    code: str
    password: str


def _session(u: User) -> dict:
    return {"token": accounts.make_token(u)}


@router.get("/auth/invite")
def invite_lookup(email: str, db: Session = Depends(get_db)):
    """Lets the sign-up form skip 'shop name' for invited people."""
    inv = accounts.pending_invite(db, accounts.normalize(email))
    if not inv:
        return {"invited": False}
    from ..models import Shop
    return {"invited": True, "shop": db.get(Shop, inv.shop_id).name}


@router.post("/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    user, needs_code = accounts.signup(db, body.email, body.password, body.name, body.shop_name)
    return {"verify": True} if needs_code else _session(user)


@router.post("/auth/verify")
def verify(body: CodeIn, db: Session = Depends(get_db)):
    return _session(accounts.verify(db, body.email, body.code))


@router.post("/auth/resend")
def resend(body: EmailIn, db: Session = Depends(get_db)):
    u = accounts.find(db, accounts.normalize(body.email))
    if u and not u.email_verified:
        accounts.issue_code(db, u, "verify")
    return {"ok": True}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    return _session(accounts.login(db, body.email, body.password))


@router.post("/auth/forgot")
def forgot(body: EmailIn, db: Session = Depends(get_db)):
    if not mailer.enabled():
        raise HTTPException(503, "Password reset needs outgoing email, which isn't set up on this server yet. Ask your shop admin.")
    accounts.forgot(db, body.email)
    return {"ok": True}


@router.post("/auth/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    return _session(accounts.reset(db, body.email, body.code, body.password))


@router.post("/auth/logout-everywhere")
def logout_everywhere(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ team
@router.get("/team")
def team(user: User = Depends(current_user), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.shop_id == user.shop_id).order_by(User.created_at)).all()
    invites = db.scalars(select(Invite).where(Invite.shop_id == user.shop_id, Invite.accepted_at.is_(None)).order_by(Invite.created_at)).all()
    return {"users": [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active, "me": u.id == user.id,
                       "sign_in": "Microsoft" if (u.external_id or "").startswith("entra:") and not u.password_hash else "Email" if u.password_hash else "—",
                       "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None} for u in users],
            "invites": [{"id": i.id, "email": i.email, "role": i.role, "invited_by": i.invited_by, "created_at": i.created_at.isoformat()} for i in invites],
            "email_enabled": mailer.enabled()}


class InviteIn(BaseModel):
    email: str
    role: str = "estimator"


@router.post("/team/invites")
def add_invite(body: InviteIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    inv = accounts.invite(db, user, body.email, body.role)
    return {"id": inv.id, "emailed": mailer.enabled()}


@router.delete("/team/invites/{iid}")
def del_invite(iid: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    inv = db.get(Invite, iid)
    if not inv or inv.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    db.delete(inv)
    db.commit()
    return {"ok": True}


class MemberIn(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None


@router.put("/team/users/{uid}")
def update_member(uid: str, body: MemberIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.shop_id != user.shop_id:
        raise HTTPException(404, "Not found")
    if u.id == user.id:
        raise HTTPException(400, "You can't change your own role or disable yourself.")
    if body.role is not None:
        if body.role not in ("admin", "estimator"):
            raise HTTPException(400, "Role must be admin or estimator.")
        u.role = body.role
    if body.active is not None:
        u.active = body.active
        u.token_version = (u.token_version or 0) + 1  # sign them out now
    db.commit()
    return {"ok": True}
