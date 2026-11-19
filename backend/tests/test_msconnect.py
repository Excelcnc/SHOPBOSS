"""Connect with Microsoft (delegated sign-in) against a fake Microsoft endpoint."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from test_accounts import auth, prod, signup  # noqa: F401  (fixture)


class FakeMicrosoft:
    """Token endpoint + the few Graph calls the app makes. 'shared' lists mailboxes the user may open."""
    def __init__(self, me="owner@excel-cnc.com", shared=("sales@excel-cnc.com",)):
        self.me, self.shared, self.calls, self.n = me, set(shared) | {me}, [], 0

    def __call__(self, req: httpx.Request):
        u = req.url
        self.calls.append((req.method, str(u)))
        if u.host == "login.microsoftonline.com":
            form = parse_qs(req.content.decode())
            if form["grant_type"][0] == "refresh_token" and form["refresh_token"][0] == "revoked":
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "AADSTS70000 revoked"})
            self.n += 1
            return httpx.Response(200, json={"access_token": f"at{self.n}", "refresh_token": f"rt{self.n}", "expires_in": 3600})
        path = u.path
        if path == "/v1.0/me":
            return httpx.Response(200, json={"mail": self.me})
        box = path.split("/users/")[1].split("/")[0] if "/users/" in path else ""
        if box not in self.shared:
            return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
        if "mailFolders" in path and "$filter" in str(u):
            return httpx.Response(200, json={"value": [{"id": "F1"}]})
        if path.endswith("/messages/delta"):
            return httpx.Response(200, json={"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=1"})
        if "/mailFolders/" in path:
            return httpx.Response(200, json={"displayName": "RFQ", "totalItemCount": 7, "unreadItemCount": 2})
        return httpx.Response(404)


@pytest.fixture()
def ms(prod, monkeypatch):
    from app.config import get_settings
    from app.services.email import msconnect
    for k, v in {"APP_URL": "https://quote.test", "GRAPH_TENANT_ID": "tid", "GRAPH_CLIENT_ID": "cid", "GRAPH_CLIENT_SECRET": "sec"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    fake = FakeMicrosoft()
    monkeypatch.setattr(msconnect, "HTTP_FACTORY", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    prod.fake = fake
    prod.base_url = "https://testserver"  # the sign-in cookie is https-only, like on Render
    return prod


def start(c, tok, **body):
    r = c.post("/api/mailboxes/microsoft/start", json={"folder": "RFQ", **body}, headers=auth(tok))
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert urlparse(r.json()["url"]).path == "/tid/oauth2/v2.0/authorize"
    assert q["redirect_uri"] == ["https://quote.test/api/oauth/microsoft/callback"] and "Mail.Read.Shared" in q["scope"][0]
    return q["state"][0]


def callback(c, state, **extra):
    return c.get("/api/oauth/microsoft/callback", params={"code": "c0de", "state": state, **extra}, follow_redirects=False)


def test_connect_own_and_shared_mailbox(ms):
    tok = signup(ms, "owner@excel-cnc.com", shop="Excel CNC")
    assert ms.get("/api/mailboxes", headers=auth(tok)).json()["ms_connect"] is True
    r = callback(ms, start(ms, tok))
    assert r.status_code == 303 and "ms_connected=owner%40excel-cnc.com" in r.headers["location"]
    r = callback(ms, start(ms, tok, address="Sales@excel-cnc.com", label="Sales"))
    assert "ms_connected=sales%40excel-cnc.com" in r.headers["location"], r.headers["location"]
    boxes = {m["address"]: m for m in ms.get("/api/mailboxes", headers=auth(tok)).json()["mailboxes"]}
    assert boxes["sales@excel-cnc.com"]["kind"] == "msoauth" and boxes["sales@excel-cnc.com"]["connected_as"] == "owner@excel-cnc.com"
    assert boxes["sales@excel-cnc.com"]["folder"] == "RFQ" and boxes["sales@excel-cnc.com"]["label"] == "Sales"
    # the refresh token is stored encrypted, never in plain text
    from app.db import SessionLocal
    from app.models import Mailbox
    db = SessionLocal()
    mb = db.get(Mailbox, boxes["sales@excel-cnc.com"]["id"])
    assert mb.oauth_token_enc and "rt" not in mb.oauth_token_enc
    # sync refreshes the token, keeps the rotated one, records the delta position
    from app.services.email import mailboxes as mbx
    old = mb.oauth_token_enc
    client = mbx.graph_client(mb, http=httpx.Client(transport=httpx.MockTransport(ms.fake)))
    assert mbx.sync(db, mb, client) == 0 and mb.last_error is None
    db.refresh(mb)
    assert mb.oauth_token_enc != old and mb.state.get("delta_link")
    assert "Microsoft 365" not in (mb.last_error or "")
    db.close()


def test_mailbox_without_access_is_explained(ms):
    tok = signup(ms, "owner@excel-cnc.com", shop="Excel CNC")
    r = callback(ms, start(ms, tok, address="ceo@excel-cnc.com"))
    loc = r.headers["location"]
    assert "ms_error" in loc and "can%27t+open+ceo%40excel-cnc.com" in loc
    assert ms.get("/api/mailboxes", headers=auth(tok)).json()["mailboxes"] == []


def test_callback_needs_same_browser(ms):
    """A sign-in link started by one shop can't be completed in someone else's browser."""
    attacker = signup(ms, "evil@gmail.com", shop="Evil")
    state = start(ms, attacker)
    ms.cookies.clear()  # the victim's browser has no cookie from this start
    r = callback(ms, state)
    assert "ms_error" in r.headers["location"] and "this+browser" in r.headers["location"]
    assert ms.get("/api/mailboxes", headers=auth(attacker)).json()["mailboxes"] == []


def test_tampered_state_and_microsoft_error(ms):
    tok = signup(ms, "owner@excel-cnc.com", shop="Excel CNC")
    state = start(ms, tok)
    assert "expired" in callback(ms, state[:-3] + "abc").headers["location"]
    r = ms.get("/api/oauth/microsoft/callback", params={"error": "access_denied", "error_description": "The user declined."}, follow_redirects=False)
    assert "ms_error=The+user+declined." in r.headers["location"]


def test_estimators_cannot_connect(ms):
    admin = signup(ms, "owner@excel-cnc.com", shop="Excel CNC")
    ms.post("/api/team/invites", json={"email": "est@excel-cnc.com"}, headers=auth(admin))
    est = signup(ms, "est@excel-cnc.com", shop="")
    assert ms.post("/api/mailboxes/microsoft/start", json={}, headers=auth(est)).status_code == 403


def test_revoked_sign_in_asks_to_reconnect(ms):
    tok = signup(ms, "owner@excel-cnc.com", shop="Excel CNC")
    callback(ms, start(ms, tok))
    from app.crypto import encrypt
    from app.db import SessionLocal
    from app.models import Mailbox
    from app.services.email import mailboxes as mbx
    db = SessionLocal()
    mb = db.query(Mailbox).one()
    mb.oauth_token_enc = encrypt("revoked")
    db.commit()
    mbx.sync(db, mb, mbx.graph_client(mb, http=httpx.Client(transport=httpx.MockTransport(ms.fake))))
    assert "Reconnect" in db.get(Mailbox, mb.id).last_error
    db.close()
