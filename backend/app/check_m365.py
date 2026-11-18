"""Check the Microsoft 365 setup from the server, using the values in .env.

    python -m app.check_m365                 # mailbox access + settings
    python -m app.check_m365 other@shop.com  # also confirm the access policy blocks another mailbox

Prints counts only; never message contents.
"""
import sys

import httpx

from .config import get_settings


def main() -> int:
    s = get_settings()
    ok = True

    def line(good: bool, msg: str, fix: str = ""):
        nonlocal ok
        ok &= good
        print(("  OK    " if good else "  FAIL  ") + msg + (f"\n          -> {fix}" if fix and not good else ""))

    print("Microsoft 365 mailbox connection")
    for k in ("graph_tenant_id", "graph_client_id", "graph_client_secret", "graph_mailbox"):
        line(bool(getattr(s, k)), f"{k.upper()} is set", f"add {k.upper()} to .env")
    if not ok:
        return 1
    import msal
    app = msal.ConfidentialClientApplication(s.graph_client_id, authority=f"https://login.microsoftonline.com/{s.graph_tenant_id}", client_credential=s.graph_client_secret)
    tok = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    line("access_token" in tok, "app can sign in to Microsoft Graph",
         f"{tok.get('error')}: {tok.get('error_description', '')[:200]} (check tenant ID, client ID and that the secret value, not its ID, was copied)")
    if not ok:
        return 1
    import base64, json
    claims = json.loads(base64.urlsafe_b64decode(tok["access_token"].split(".")[1] + "=="))
    line("Mail.Read" in claims.get("roles", []) or "Mail.ReadWrite" in claims.get("roles", []), "Mail.Read application permission granted",
         "API permissions -> add Microsoft Graph APPLICATION permission Mail.Read -> Grant admin consent")
    h = {"Authorization": "Bearer " + tok["access_token"]}
    r = httpx.get(f"https://graph.microsoft.com/v1.0/users/{s.graph_mailbox}/mailFolders/inbox?$select=totalItemCount,unreadItemCount", headers=h, timeout=30)
    if r.status_code == 200:
        j = r.json()
        line(True, f"can read {s.graph_mailbox} inbox ({j.get('totalItemCount')} messages, {j.get('unreadItemCount')} unread)")
    else:
        line(False, f"reading {s.graph_mailbox} inbox returned HTTP {r.status_code}",
             "check the mailbox address; if 403, the application access policy may exclude it (Test-ApplicationAccessPolicy)")
    if len(sys.argv) > 1:
        other = sys.argv[1]
        r2 = httpx.get(f"https://graph.microsoft.com/v1.0/users/{other}/mailFolders/inbox?$select=totalItemCount", headers=h, timeout=30)
        line(r2.status_code in (403, 404), f"access policy blocks other mailbox {other} (HTTP {r2.status_code})",
             "the app can read other mailboxes: create the ApplicationAccessPolicy in docs/M365_SETUP.md step 4")
    print("\nWebhook (instant delivery)")
    if s.graph_webhook_url:
        line(s.graph_webhook_url.startswith("https://"), f"GRAPH_WEBHOOK_URL = {s.graph_webhook_url}", "must be a public https:// URL")
    else:
        print("  INFO  GRAPH_WEBHOOK_URL not set: new RFQs arrive by 5-minute polling instead of instantly")
    print("\nSign-in")
    if s.auth_mode == "entra":
        line(bool(s.entra_client_id and s.entra_tenant_id), "ENTRA_CLIENT_ID and ENTRA_TENANT_ID set", "add them to .env")
    else:
        print("  INFO  AUTH_MODE is 'dev' (no sign-in). Set AUTH_MODE=entra for the pilot.")
    print("\nResult: " + ("ready" if ok else "fix the FAIL lines above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
