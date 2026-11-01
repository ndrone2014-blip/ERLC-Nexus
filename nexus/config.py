"""Configuration loading.

Settings come from environment variables, falling back to ``config.env`` in the
project root. A tiny built-in parser is used (no python-dotenv dependency) so the
Windows install stays minimal. Secrets are never logged: ``Settings.safe_dict``
masks them.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / "config.env"

SECRET_FIELDS = {
    "discord_bot_token",
    "discord_client_secret",
    "erlc_server_key",
    "erlc_global_key",
    "secret_key",
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file. Supports comments, blank lines and quoted values."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


class Settings(BaseModel):
    # Discord
    discord_bot_token: str = ""
    discord_application_id: str = ""
    discord_client_secret: str = ""
    discord_guild_id: str = ""
    discord_redirect_uri: str = ""

    # ERLC / PRC API
    erlc_server_key: str = ""
    erlc_global_key: str = ""
    erlc_api_base_url: str = "https://api.erlc.gg"
    erlc_sync_interval: int = Field(default=20, ge=10, le=600)
    erlc_cache_ttl: int = Field(default=15, ge=1, le=600)
    erlc_request_timeout: float = Field(default=10.0, ge=1, le=60)
    erlc_webhook_enabled: bool = False

    # Web
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8420, ge=1, le=65535)
    public_url: str = ""
    secret_key: str = ""
    session_hours: int = Field(default=12, ge=1, le=24 * 30)
    cookie_secure: bool = False
    dev_login: bool = False

    # Platform
    database_url: str = ""
    initial_admin_discord_id: str = ""
    log_level: str = "INFO"
    data_dir: str = ""

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "INFO").upper()

    # ---- derived values -------------------------------------------------
    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir) if self.data_dir else ROOT_DIR / "data"
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_path / 'nexus.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def base_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        host = "localhost" if self.web_host in ("0.0.0.0", "127.0.0.1") else self.web_host
        return f"http://{host}:{self.web_port}"

    @property
    def oauth_redirect(self) -> str:
        return self.discord_redirect_uri or f"{self.base_url}/auth/callback"

    @property
    def oauth_configured(self) -> bool:
        return bool(self.discord_application_id and self.discord_client_secret)

    def safe_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self.model_dump().items():
            out[k] = ("configured" if v else "not set") if k in SECRET_FIELDS else v
        return out

    def problems(self, component: str = "all") -> list[str]:
        """Human-readable configuration problems for the start scripts."""
        issues: list[str] = []
        if not self.secret_key or self.secret_key.startswith("change-me"):
            issues.append("SECRET_KEY is not set. Run install.bat again or set a long random value.")
        if component in ("all", "bot") and not self.discord_bot_token:
            issues.append("DISCORD_BOT_TOKEN is missing (the Discord bot cannot start).")
        if component in ("all", "web") and not self.oauth_configured and not self.dev_login:
            issues.append(
                "DISCORD_APPLICATION_ID / DISCORD_CLIENT_SECRET missing: website login will not work."
            )
        if not self.erlc_server_key:
            issues.append(
                "ERLC_SERVER_KEY is not set: live ERLC data is disabled until you add it "
                "(config.env or System > API Configuration)."
            )
        return issues


def load_settings(env_file: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    file_values = parse_env_file(env_file or DEFAULT_ENV_FILE)
    data: dict[str, Any] = {}
    for name in Settings.model_fields:
        env_key = name.upper()
        if env_key in os.environ:
            data[name] = os.environ[env_key]
        elif env_key in file_values:
            data[name] = file_values[env_key]
    # Empty strings for typed fields fall back to defaults.
    for name, field in Settings.model_fields.items():
        if name in data and data[name] == "" and field.annotation is not str:
            data.pop(name)
    if overrides:
        data.update(overrides)
    return Settings(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def generate_secret() -> str:
    return secrets.token_urlsafe(48)
