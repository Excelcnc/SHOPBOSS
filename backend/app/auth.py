"""Authentication.

Production (AUTH_MODE other than "dev") accepts two kinds of bearer token:
* Email + password accounts (any email provider), see services/accounts.py. Each sign-up creates a
  shop, unless an admin invited that email, in which case it joins the inviting shop.
* Microsoft Entra ID tokens ("Sign in with Microsoft"), when ENTRA_CLIENT_ID is set. Each Microsoft 365
  tenant maps to one shop, created on first sign-in. Someone who already has an email account (or an
  invitation) is matched by email address instead.
The first user of a shop becomes its admin.

dev: trusts X-Dev-User / X-Dev-Shop headers. Local development and tests only.
"""
from __future__ import annotations

import functools

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import IntegrationState, Shop, User
from .services import accounts
from .services.shopdata import seed_shop


@functools.lru_cache
def _jwks(tenant: str):
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys")


def _verify_entra(token: str) -> dict:
    s = get_settings()
    unverified = jwt.decode(token, options={"verify_signature": False})
    tid = unverified.get("tid", "")
    if s.entra_tenant_id and s.entra_tenant_id not in ("common", "organizations") and tid != s.entra_tenant_id:
        raise HTTPException(401, "Token is from another tenant")
    key = _jwks(tid or "common").get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=[s.entra_client_id, f"api://{s.entra_client_id}"],
                        options={"verify_iss": False})
    # v2 tokens: login.microsoftonline.com/<tid>/v2.0 ; v1 tokens: sts.windows.net/<tid>/
    if claims.get("iss") not in (f"https://login.microsoftonline.com/{tid}/v2.0", f"https://sts.windows.net/{tid}/"):
        raise jwt.InvalidIssuerError("Unexpected token issuer")
    return claims


def _shop_for_tenant(db: Session, tenant_key: str, name: str) -> Shop:
    st = db.scalar(select(IntegrationState).where(IntegrationState.kind == "tenant:" + tenant_key))
    if st:
        return db.get(Shop, st.shop_id)
    shop = seed_shop(db, name)
    db.add(IntegrationState(shop_id=shop.id, kind="tenant:" + tenant_key, state={"tenant": tenant_key}))
    db.flush()
    return shop


def current_user(db: Session = Depends(get_db), authorization: str | None = Header(None),
                 x_dev_user: str | None = Header(None), x_dev_shop: str | None = Header(None)) -> User:
    s = get_settings()
    if s.auth_mode == "dev":
        email = (x_dev_user or "estimator@example.com").lower()
        shop = _shop_for_tenant(db, "dev:" + (x_dev_shop or "default"), (x_dev_shop or "Demo Machine Shop"))
        ext = "dev:" + email
        name = email.split("@")[0].replace(".", " ").title()
    else:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Sign in required")
        token = authorization.split(" ", 1)[1]
        if accounts.is_local_token(token):
            return accounts.user_from_token(db, token)
        if not s.entra_client_id:
            raise HTTPException(401, "Sign in required")
        try:
            claims = _verify_entra(token)
        except jwt.PyJWTError as e:
            raise HTTPException(401, f"Invalid token: {e}")
        email = (claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").lower()
        ext = "entra:" + claims["oid"]
        name = claims.get("name", email)
        user = db.scalar(select(User).where(User.external_id == ext))
        if not user and email:
            # Same person as an email account or an invitation: use that shop.
            user = accounts.find(db, email)
            inv = None if user else accounts.pending_invite(db, email)
            if inv:
                user = db.scalar(select(User).where(User.shop_id == inv.shop_id, User.email == email)) or User(shop_id=inv.shop_id, email=email, name=name, role=inv.role)
                db.add(user)
                inv.accepted_at = accounts.now()
            if user:
                user.external_id = ext
        if user:
            if not user.active:
                raise HTTPException(403, "Your account has been disabled by your shop admin.")
            db.commit()
            return user
        domain = email.split("@")[-1] if "@" in email else "shop"
        shop = _shop_for_tenant(db, "entra:" + claims["tid"], domain)
    user = db.scalar(select(User).where(User.external_id == ext))
    if not user:
        first = db.scalar(select(User.id).where(User.shop_id == shop.id).limit(1)) is None
        user = User(shop_id=shop.id, email=email, name=name, role="admin" if first else "estimator", external_id=ext)
        db.add(user)
    db.commit()
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Shop admins only")
    return user
