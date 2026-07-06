"""
AccountManager — the runner's ONLY path to a real secret.

Fetches credentials on demand via the dedicated, audited credential-lookup
endpoint (never via claim()/heartbeat()). Never writes plaintext to disk —
this is the direct fix for VVRO's GeneratedOutlooks.csv / "Successful Outlook
mails.csv" plaintext-credential files.
"""

from __future__ import annotations

from typing import Any, Optional

from api_client import ApiClient
from logger import get_logger

log = get_logger(__name__)


class AccountManager:
    def __init__(self, api: ApiClient):
        self.api = api

    def load_account_credentials(self, account_id: str) -> Optional[dict[str, Any]]:
        """{ account_id, username, password, two_fa_secret } or None."""
        creds = self.api.get_account_credentials(account_id)
        if not creds:
            log.error("Could not fetch credentials for account %s", account_id)
        return creds

    def load_network_credentials(self, profile_id: str) -> Optional[dict[str, Any]]:
        """{ profile_id, provider, username, password } or None."""
        creds = self.api.get_network_credentials(profile_id)
        if not creds:
            log.error("Could not fetch network credentials for profile %s", profile_id)
        return creds
