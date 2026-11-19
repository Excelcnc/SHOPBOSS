"""Email + password accounts, invitations, and shop isolation in production auth mode."""
import os

import pytest


@pytest.fixture()
def prod(monkeypatch):
    """App in production auth mode with a fake outbox instead of SMTP."""
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.db import Base, engine, reset_engine
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-tokens")
    get_settings.cache_clear()
    reset_engine()
    Base.metadata.drop_all(engine())
    Base.metadata.create_all(engine())
    outbox = []
    from app.services import mailer
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subj, text: outbox.append((to, subj, text)) or True)
    from app.main import app
    with TestClient(app) as c:
        c.outbox = outbox
        yield c
    get_settings.cache_clear()


def code_for(c, email):
    import re
    return re.search(r"\b(\d{6})\b", [m for m in c.outbox if m[0] == email.lower()][-1][2]).group(1)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def signup(c, email, shop="Acme Machining", pw="correct horse battery"):
    r = c.post("/api/auth/signup", json={"email": email, "password": pw, "name": "Pat Smith", "shop_name": shop})
    assert r.status_code == 200, r.text
    assert r.json() == {"verify": True}
    r = c.post("/api/auth/verify", json={"email": email, "code": code_for(c, email)})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_config_is_public(prod):
    r = prod.get("/api/config").json()
    assert r["dev"] is False and r["signup_open"] is True and r["email_verification"] is True


def test_signup_verify_login(prod):
    assert prod.get("/api/me").status_code == 401
    tok = signup(prod, "Pat@Gmail.com")
    me = prod.get("/api/me", headers=auth(tok)).json()
    assert me["email"] == "pat@gmail.com" and me["role"] == "admin" and me["shop"]["name"] == "Acme Machining"
    # the new shop is ready to quote: default rates seeded
    assert len(prod.get("/api/shop", headers=auth(tok)).json()["rates"]) >= 5
    # sign in again
    assert prod.post("/api/auth/login", json={"email": "pat@gmail.com", "password": "nope nope nope"}).status_code == 401
    r = prod.post("/api/auth/login", json={"email": "PAT@gmail.com", "password": "correct horse battery"})
    assert r.status_code == 200 and prod.get("/api/me", headers=auth(r.json()["token"])).status_code == 200
    # duplicate sign-up refused
    assert prod.post("/api/auth/signup", json={"email": "pat@gmail.com", "password": "another long password", "shop_name": "X"}).status_code == 409


def test_wrong_code_and_short_password(prod):
    assert prod.post("/api/auth/signup", json={"email": "a@b.co", "password": "short", "shop_name": "S"}).status_code == 400
    prod.post("/api/auth/signup", json={"email": "a@b.co", "password": "long enough pw", "shop_name": "S"})
    for _ in range(5):
        assert prod.post("/api/auth/verify", json={"email": "a@b.co", "code": "000000"}).status_code == 400
    # after 5 wrong tries even the right code is refused until a new one is sent
    assert prod.post("/api/auth/verify", json={"email": "a@b.co", "code": code_for(prod, "a@b.co")}).status_code == 400
    prod.post("/api/auth/resend", json={"email": "a@b.co"})
    assert prod.post("/api/auth/verify", json={"email": "a@b.co", "code": code_for(prod, "a@b.co")}).status_code == 200


def test_unverified_login_asks_for_code(prod):
    prod.post("/api/auth/signup", json={"email": "u@yahoo.com", "password": "long enough pw", "shop_name": "S"})
    r = prod.post("/api/auth/login", json={"email": "u@yahoo.com", "password": "long enough pw"})
    assert r.status_code == 403 and r.json()["detail"] == "verify"


def test_lockout_and_reset(prod):
    signup(prod, "lock@shop.com")
    for _ in range(8):
        prod.post("/api/auth/login", json={"email": "lock@shop.com", "password": "wrong password!"})
    assert prod.post("/api/auth/login", json={"email": "lock@shop.com", "password": "correct horse battery"}).status_code == 429
    old = prod.post("/api/auth/forgot", json={"email": "lock@shop.com"})
    assert old.status_code == 200
    r = prod.post("/api/auth/reset", json={"email": "lock@shop.com", "code": code_for(prod, "lock@shop.com"), "password": "brand new password"})
    assert r.status_code == 200
    assert prod.post("/api/auth/login", json={"email": "lock@shop.com", "password": "brand new password"}).status_code == 200
    # unknown email gets the same answer
    assert prod.post("/api/auth/forgot", json={"email": "nobody@shop.com"}).status_code == 200


def test_reset_signs_out_old_sessions(prod):
    tok = signup(prod, "s@shop.com")
    prod.post("/api/auth/forgot", json={"email": "s@shop.com"})
    prod.post("/api/auth/reset", json={"email": "s@shop.com", "code": code_for(prod, "s@shop.com"), "password": "brand new password"})
    assert prod.get("/api/me", headers=auth(tok)).status_code == 401


def test_invite_joins_shop_and_isolation(prod):
    admin = signup(prod, "owner@acme.com", shop="Acme")
    other = signup(prod, "boss@globex.com", shop="Globex")
    r = prod.post("/api/team/invites", json={"email": "Helper@Outlook.com", "role": "estimator"}, headers=auth(admin))
    assert r.status_code == 200 and any(m[0] == "helper@outlook.com" for m in prod.outbox)
    assert prod.get("/api/auth/invite", params={"email": "helper@outlook.com"}).json() == {"invited": True, "shop": "Acme"}
    # invited person needs no shop name
    r = prod.post("/api/auth/signup", json={"email": "helper@outlook.com", "password": "helper password"})
    assert r.status_code == 200
    tok = prod.post("/api/auth/verify", json={"email": "helper@outlook.com", "code": code_for(prod, "helper@outlook.com")}).json()["token"]
    me = prod.get("/api/me", headers=auth(tok)).json()
    assert me["shop"]["name"] == "Acme" and me["role"] == "estimator"
    team = prod.get("/api/team", headers=auth(admin)).json()
    assert {u["email"] for u in team["users"]} == {"owner@acme.com", "helper@outlook.com"} and team["invites"] == []
    # estimators can't invite; other shops can't see the team or RFQs
    assert prod.post("/api/team/invites", json={"email": "x@y.com"}, headers=auth(tok)).status_code == 403
    rfq = prod.post("/api/rfqs", data={"customer_name": "Wayne Ent", "subject": "Brackets"}, headers=auth(admin))
    assert rfq.status_code == 200, rfq.text
    assert prod.get(f"/api/rfqs/{rfq.json()[0]['id']}", headers=auth(other)).status_code == 404
    assert "owner@acme.com" not in str(prod.get("/api/team", headers=auth(other)).json())
    # disabling a member signs them out
    uid = next(u["id"] for u in team["users"] if u["email"] == "helper@outlook.com")
    assert prod.put(f"/api/team/users/{uid}", json={"active": False}, headers=auth(admin)).status_code == 200
    assert prod.get("/api/me", headers=auth(tok)).status_code == 401


def test_invite_only_mode(prod, monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("SIGNUP_OPEN", "false")
    get_settings.cache_clear()
    r = prod.post("/api/auth/signup", json={"email": "z@z.com", "password": "long enough pw", "shop_name": "Z"})
    assert r.status_code == 403


def test_tampered_token_rejected(prod):
    tok = signup(prod, "t@shop.com")
    assert prod.get("/api/me", headers=auth(tok[:-2] + "xx")).status_code == 401


def test_microsoft365_mailboxes_limited_to_proven_domain(prod, monkeypatch):
    """The server's mailbox app belongs to one company: other shops must not be able to read its mail."""
    from app.config import get_settings
    from app.services.email import graph
    for k, v in {"GRAPH_TENANT_ID": "t", "GRAPH_CLIENT_ID": "c", "GRAPH_CLIENT_SECRET": "s", "GRAPH_SHOP_DOMAINS": "excel-cnc.com"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(graph.GraphClient, "folder_counts", lambda self: {"displayName": "RFQ", "totalItemCount": 3, "unreadItemCount": 1})
    body = {"kind": "graph", "address": "purchasing@excel-cnc.com", "folder": "RFQ"}

    stranger = signup(prod, "boss@gmail.com", shop="Somebody Else")
    assert prod.get("/api/mailboxes", headers=auth(stranger)).json()["graph_available"] is False
    assert prod.post("/api/mailboxes", json=body, headers=auth(stranger)).status_code == 403

    owner = signup(prod, "owner@excel-cnc.com", shop="Excel CNC")  # proved the address with a code
    assert prod.get("/api/mailboxes", headers=auth(owner)).json()["graph_available"] is True
    assert prod.post("/api/mailboxes", json={**body, "address": "someone@other.com"}, headers=auth(owner)).status_code == 403
    r = prod.post("/api/mailboxes", json=body, headers=auth(owner))
    assert r.status_code == 200, r.text


def test_unproven_address_cannot_use_microsoft365(prod, monkeypatch):
    """Without outgoing email nobody proves their address, so nobody gets the mailbox app."""
    from app.config import get_settings
    from app.services import mailer
    for k, v in {"GRAPH_TENANT_ID": "t", "GRAPH_CLIENT_ID": "c", "GRAPH_CLIENT_SECRET": "s", "GRAPH_SHOP_DOMAINS": "excel-cnc.com"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    r = prod.post("/api/auth/signup", json={"email": "fake@excel-cnc.com", "password": "long enough pw", "shop_name": "Impostor"})
    tok = r.json()["token"]
    assert prod.get("/api/mailboxes", headers=auth(tok)).json()["graph_available"] is False
    # and the address can't be claimed again by someone else
    assert prod.post("/api/auth/signup", json={"email": "fake@excel-cnc.com", "password": "other long pw", "shop_name": "X"}).status_code == 409
