"""Per-process runtime: settings, database and ERLC client.

Both the website process and the bot process create one ``Runtime``. They
share the database, so state (and the cross-process event outbox) is shared.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid

from nexus.config import Settings, get_settings
from nexus.core.crypto import decrypt_secret
from nexus.core.seed import seed_all
from nexus.core.settings_store import get_setting
from nexus.db.base import Database
from nexus.erlc.client import ErlcClient
from nexus.logging_setup import register_secret

log = logging.getLogger("nexus.runtime")


class Runtime:
    def __init__(self, settings: Settings | None = None, *, component: str = "web",
                 erlc_transport=None) -> None:
        self.settings = settings or get_settings()
        self.component = component
        self.instance_id = f"{component}-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.db = Database(self.settings.db_url)
        self._db_key: str | None = None
        for secret in (self.settings.discord_bot_token, self.settings.discord_client_secret,
                       self.settings.erlc_server_key, self.settings.erlc_global_key, self.settings.secret_key):
            register_secret(secret)
        self.erlc = ErlcClient(
            self.current_server_key,
            base_url=self.settings.erlc_api_base_url,
            global_key=self.settings.erlc_global_key,
            timeout=self.settings.erlc_request_timeout,
            cache_ttl=self.settings.erlc_cache_ttl,
            transport=erlc_transport,
        )

    def current_server_key(self) -> str | None:
        """Dashboard-set key (encrypted in DB) takes precedence over config.env."""
        return self._db_key or self.settings.erlc_server_key or None

    async def refresh_server_key(self) -> None:
        async with self.db.session() as s:
            token = await get_setting(s, "erlc.server_key_encrypted")
        key = decrypt_secret(self.settings.secret_key, token) if token else None
        if key:
            register_secret(key)
        if key != self._db_key:
            self._db_key = key
            self.erlc.reset_key_state()

    async def startup(self, *, run_migrations: bool = True) -> None:
        self.settings.data_path.mkdir(parents=True, exist_ok=True)
        (self.settings.data_path / "backups").mkdir(exist_ok=True)
        if run_migrations:
            from nexus.db.migrate import upgrade_to_head

            await upgrade_to_head(self.db)
        else:
            await self.db.create_all()
        async with self.db.session() as s:
            await seed_all(s, self.settings.initial_admin_discord_id)
        await self.refresh_server_key()

    async def shutdown(self) -> None:
        await self.erlc.close()
        await self.db.dispose()
