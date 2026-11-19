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
    # which shop the configured mailbox belongs to: "entra:<tenant id>" in production, "dev:default" locally
    intake_tenant_key: str = "dev:default"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
