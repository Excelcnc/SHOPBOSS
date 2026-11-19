from datetime import datetime, timezone

import pytest

from app.services.email.parse import ParsedEmail


def msg(mid, subject, atts, samples=None):
    data = [(n, (samples / n).read_bytes() if samples and (samples / n).exists() else b"x") for n in atts]
    return ParsedEmail(f"<{mid}@cust>", "Buyer", "buyer@customer.example", subject, "Please see attached.\n\nAcme Robotics Inc", datetime.now(timezone.utc), data)


class FakeGraph:
    def __init__(self):
        self.batches, self.msgs, self.calls = [], {}, 0

    def folder_counts(self):
        return {"displayName": "RFQ", "totalItemCount": 12, "unreadItemCount": 3}

    def delta(self, link, since=None):
        self.calls += 1
        ids = self.batches.pop(0) if self.batches else []
        return ids, f"delta-{self.calls}"

    def get_message(self, mid):
        return self.msgs[mid]

    def subscribe(self, url, cs):
        return {"id": "sub-1", "expirationDateTime": "2099-01-01T00:00:00Z"}


@pytest.fixture()
def graph(monkeypatch):
    import app.services.email.graph as g
    import app.services.email.mailboxes as mbx
    fake = FakeGraph()
    monkeypatch.setattr(g, "graph_configured", lambda: True)
    monkeypatch.setattr(mbx, "graph_client", lambda mb, http=None: fake)
    return fake


def test_graph_mailbox_connect_sync_filter_dedupe(client, samples, graph):
    r = client.post("/api/mailboxes", json={"kind": "graph", "address": "Purchasing@excel-cnc.example", "folder": "RFQ"}).json()
    assert r["address"] == "purchasing@excel-cnc.example" and r["test"]["ok"] and "12 messages" in r["test"]["message"]
    mid = r["id"]
    # first sync only records the position: old mail is not imported
    graph.batches = [["old1"]]
    graph.msgs["old1"] = msg("old1", "RFQ 100 old", ["BRK-20417_RevC.step"], samples)
    assert client.post(f"/api/mailboxes/{mid}/sync").json()["imported"] == 0
    # new mail: one RFQ, one invoice (filtered out)
    graph.batches = [["n1", "n2"]]
    graph.msgs["n1"] = msg("n1", "RFQ 4471 bracket", ["BRK-20417_RevC.step", "BRK-20417_RevC.pdf"], samples)
    graph.msgs["n2"] = msg("n2", "Invoice 88231", ["INV-88231.pdf"])
    out = client.post(f"/api/mailboxes/{mid}/sync").json()
    assert out["imported"] == 1 and out["skipped"] == 1 and out["last_error"] is None
    rfqs = client.get("/api/rfqs").json()
    assert len(rfqs) == 1
    assert client.get(f"/api/rfqs/{rfqs[0]['id']}").json()["email"]["mailbox"] == "purchasing@excel-cnc.example"
    # the same email also delivered to a second connected mailbox is not duplicated
    r2 = client.post("/api/mailboxes", json={"kind": "graph", "address": "sales@excel-cnc.example"}).json()
    graph.batches = [[], ["n1"]]
    client.post(f"/api/mailboxes/{r2['id']}/sync")
    client.post(f"/api/mailboxes/{r2['id']}/sync")
    assert len(client.get("/api/rfqs").json()) == 1
    lst = client.get("/api/mailboxes").json()
    assert lst["graph_available"] and len(lst["mailboxes"]) == 2
    assert client.post("/api/mailboxes", json={"kind": "graph", "address": "purchasing@excel-cnc.example", "folder": "RFQ"}).status_code == 409


def test_graph_webhook_routes_to_mailbox(client, samples, graph):
    r = client.post("/api/mailboxes", json={"kind": "graph", "address": "quotes@excel-cnc.example"}).json()
    from app.db import SessionLocal
    from app.models import Mailbox
    db = SessionLocal()
    m = db.get(Mailbox, r["id"])
    m.state = {"delta_link": "x", "subscription": {"id": "sub-9", "expirationDateTime": "2099-01-01T00:00:00Z", "client_state": "s3cret"}}
    db.commit(); db.close()
    graph.msgs["w1"] = msg("w1", "Request for quotation SHF-3310", ["SHF-3310_RevC.step"], samples)
    bad = {"value": [{"subscriptionId": "sub-9", "clientState": "wrong", "resourceData": {"id": "w1"}}]}
    assert client.post("/api/intake/graph/notify", json=bad).status_code == 202 and client.get("/api/rfqs").json() == []
    good = {"value": [{"subscriptionId": "sub-9", "clientState": "s3cret", "resourceData": {"id": "w1"}}]}
    assert client.post("/api/intake/graph/notify", json=good).status_code == 202
    assert len(client.get("/api/rfqs").json()) == 1


def test_graph_requires_server_app(client, monkeypatch):
    import app.services.email.graph as g
    monkeypatch.setattr(g, "graph_configured", lambda: False)
    r = client.post("/api/mailboxes", json={"kind": "graph", "address": "a@b.example"})
    assert r.status_code == 400 and "mailbox app" in r.json()["detail"]


class FakeImap:
    store = {}
    def __init__(self, host, port, user, password, folder="INBOX"):
        assert password == "app-pass-123"
        self.folder, self.count = "INBOX", len(self.store)
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def max_uid(self): return max(self.store) if self.store else 0
    def uids_since(self, d): return list(self.store)
    def uids_after(self, last): return [u for u in self.store if u > last]
    def fetch(self, uid): return self.store[uid]


def test_imap_mailbox_password_encrypted_and_sync(client, samples, monkeypatch):
    import app.services.email.mailboxes as mbx
    monkeypatch.setattr(mbx, "ImapClient", FakeImap)
    FakeImap.store = {1: b"From: x@y.z\r\nSubject: old\r\nMessage-ID: <o1@x>\r\n\r\nhello"}
    r = client.post("/api/mailboxes", json={"kind": "imap", "address": "rfq@gmail.example", "imap_host": "imap.gmail.com", "imap_password": "app-pass-123"}).json()
    assert r["has_password"] and "imap_password" not in r and r["test"]["ok"]
    from app.db import SessionLocal
    from app.models import Mailbox
    db = SessionLocal(); enc = db.get(Mailbox, r["id"]).imap_password_enc; db.close()
    assert enc and "app-pass-123" not in enc
    assert client.post(f"/api/mailboxes/{r['id']}/sync").json()["imported"] == 0  # first sync: position only
    FakeImap.store[2] = (samples / "RFQ_BWP-2026-0418.eml").read_bytes()
    out = client.post(f"/api/mailboxes/{r['id']}/sync").json()
    assert out["imported"] == 1
    assert client.get("/api/rfqs").json()[0]["customer_name"] == "Brightwater Pumps Ltd"
    assert client.delete(f"/api/mailboxes/{r['id']}").json()["ok"]
