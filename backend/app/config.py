"""Application settings, read from environment variables (see .env.example)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://cnc:cnc@localhost:5432/cncquote"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./data/files"          # local file storage; swap for Azure Blob/S3 in production
    run_jobs_inline: bool = False              # True = run analysis in the request (tests/dev without a worker)

    # Auth: "dev" trusts an X-Dev-User header (local only). Anything else ("prod", or the older "entra")
    # requires sign-in: email + password accounts (any email provider) and, when ENTRA_CLIENT_ID is set,
    # "Sign in with Microsoft" too.
    auth_mode: str = "dev"
    entra_tenant_id: str = ""                  # one tenant ID, or "organizations" for any Microsoft 365 company
    entra_client_id: str = ""                  # sign-in app registration (audience)
    signup_open: bool = True                   # anyone may create a shop; False = invite only
    # Company portal mode, e.g. "excel-cnc.com": only these email domains (plus invited people) can create
    # accounts, and everyone joins the one company shop instead of creating their own.
    signup_domains: str = ""
    session_days: int = 30

    # Public address of the app, e.g. https://cnc-quote.onrender.com (links in emails, Graph webhook)
    app_url: str = ""

    # Outgoing email (verification codes, invitations). Any SMTP service: Resend, Postmark, Brevo,
    # SendGrid, Microsoft 365. Without it, new accounts are not email-verified (pilot use only).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                        # e.g. "CNC Quote <noreply@yourdomain.com>"
    smtp_tls: bool = True                      # STARTTLS on port 587 (465 always uses TLS)

    # Microsoft 365 mailbox intake (Graph, application permissions)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_mailbox: str = ""                    # e.g. quotes@yourshop.com
    graph_webhook_url: str = ""                # public https URL of /api/intake/graph/notify
    graph_client_state: str = "change-me"      # shared secret echoed in notifications
    # The mailbox app belongs to ONE Microsoft 365 company. On a shared (multi-shop) server only shops whose
    # admins have proven an address at these domains may connect Microsoft 365 mailboxes, and only at
    # these domains. Comma list, e.g. "excel-cnc.com". Empty = nobody (except in dev mode).
    graph_shop_domains: str = ""
    # "Connect with Microsoft" for mailboxes (delegated sign-in; no admin PowerShell needed). A Web app
    # registration with redirect URI <APP_URL>/api/oauth/microsoft/callback and delegated permissions
    # offline_access, User.Read, Mail.Read, Mail.Read.Shared. Defaults to the mailbox app (GRAPH_*) and its
    # tenant; set MS_CONNECT_* to a multi-tenant app ("common") so other companies can connect too.
    ms_connect_client_id: str = ""
    ms_connect_client_secret: str = ""
    ms_connect_tenant: str = ""
    graph_folder: str = "inbox"                # "inbox", or a folder name such as "RFQ" (top level or under Inbox)
    # Shared mailboxes receive more than RFQs: only take emails that look like customer RFQs
    # (a 3D model attached, or RFQ wording plus a drawing). Uploads are never filtered.
    intake_filter: bool = True
    intake_keywords: str = "rfq,rfp,request for quote,request for quotation,quote request,please quote,please price,pricing request,enquiry,inquiry,bid request"

    # Generic mailbox (forwarding address) via IMAP
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # AI (extraction only; never sets prices)
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_enabled: bool = True

    max_attachment_mb: int = 50
    secret_key: str = ""  # encrypts stored mailbox passwords; set a long random value in production
    # which shop the configured mailbox belongs to: "entra:<tenant id>" in production, "dev:default" locally
    intake_tenant_key: str = "dev:default"
    cors_origins: str = "http://localhost:5173"
    static_dir: str = ""                       # built web app to serve (single-service deployments)

    @property
    def signup_domain_set(self) -> set[str]:
        return {d.strip().lower().lstrip("@") for d in self.signup_domains.split(",") if d.strip()}

    @property
    def dev(self) -> bool:
        return self.auth_mode == "dev"

    @property
    def webhook_url(self) -> str:
        if self.graph_webhook_url:
            return self.graph_webhook_url
        return self.app_url.rstrip("/") + "/api/intake/graph/notify" if self.app_url.startswith("https://") else ""

    @property
    def ms_connect(self) -> dict | None:
        cid = self.ms_connect_client_id or self.graph_client_id
        secret = self.ms_connect_client_secret if self.ms_connect_client_id else self.graph_client_secret
        if not (cid and secret and self.app_url):
            return None
        tenant = self.ms_connect_tenant or ("common" if self.ms_connect_client_id else self.graph_tenant_id or "common")
        return {"client_id": cid, "secret": secret, "tenant": tenant,
                "redirect_uri": self.app_url.rstrip("/") + "/api/oauth/microsoft/callback"}

    @property
    def sqlalchemy_url(self) -> str:
        """Hosting providers hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver."""
        u = self.database_url
        for pre in ("postgres://", "postgresql://"):
            if u.startswith(pre):
                return "postgresql+psycopg://" + u[len(pre):]
        return u


@lru_cache
def get_settings() -> Settings:
    return Settings()
