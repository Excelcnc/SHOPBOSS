"""Application settings, read from environment variables (see .env.example)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://cnc:cnc@localhost:5432/cncquote"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./data/files"          # local file storage; swap for Azure Blob/S3 in production
    run_jobs_inline: bool = False              # True = run analysis in the request (tests/dev without a worker)

    # Auth: "dev" trusts an X-Dev-User header (local only); "entra" validates Microsoft Entra ID tokens
    auth_mode: str = "dev"
    entra_tenant_id: str = ""
    entra_client_id: str = ""                  # API app registration (audience)

    # Microsoft 365 mailbox intake (Graph, application permissions)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_mailbox: str = ""                    # e.g. quotes@yourshop.com
    graph_webhook_url: str = ""                # public https URL of /api/intake/graph/notify
    graph_client_state: str = "change-me"      # shared secret echoed in notifications

    # Generic mailbox (forwarding address) via IMAP
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # AI (extraction only; never sets prices)
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_enabled: bool = True

    # Linked mailboxes (read-only OAuth). Tokens are encrypted with TOKEN_ENCRYPTION_KEY (a Fernet key:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").
    token_encryption_key: str = ""
    file_link_secret: str = ""                 # signs short-lived file links; falls back to TOKEN_ENCRYPTION_KEY
    file_link_ttl_s: int = 300
    public_base_url: str = "http://localhost:8000"   # where /api is reachable (OAuth redirect URIs)
    app_url: str = "http://localhost:5173"           # the web app (where OAuth sends the user back)
    google_client_id: str = ""
    google_client_secret: str = ""
    ms_oauth_client_id: str = ""               # Entra app with delegated Mail.Read (per-user mailbox linking)
    ms_oauth_client_secret: str = ""
    ms_oauth_tenant: str = "organizations"
    poll_interval_s: int = 300                 # scheduled mailbox check (5 minutes)
    max_backfill_days: int = 30

    max_attachment_mb: int = 50
    # which shop the configured mailbox belongs to: "entra:<tenant id>" in production, "dev:default" locally
    intake_tenant_key: str = "dev:default"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
