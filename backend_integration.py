"""
ShowWise Backend Integration Module
====================================
Handles all communication with the ShowWise Backend:
  - Organisation configuration loading (cached, refresh interval from env)
  - Kill-switch licence-key model (file-backed, auto-renewal)
  - Centralised logging
  - Chat messaging (kept for compatibility)

Key env vars
------------
BACKEND_URL          Base URL of the backend  (e.g. https://backend.example.com)
BACKEND_API_KEY      Your API key
ORG_SLUG             Your organisation slug
PING_INTERVAL        Seconds between kill-switch pings          (default 300)
CONFIG_REFRESH       Seconds between org-config cache refreshes (default 3600)
LICENSE_KEY_FILE     Path to persist the licence key            (default .license_key)

Author: ShowWise Team
Version: 2.0.0
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults / env helpers
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


PING_INTERVAL    = _env_int("PING_INTERVAL",   300)   # seconds
CONFIG_REFRESH   = _env_int("CONFIG_REFRESH", 3600)   # seconds
LICENSE_KEY_FILE = os.getenv("LICENSE_KEY_FILE", ".license_key")


# ---------------------------------------------------------------------------
# ShowWiseBackend
# ---------------------------------------------------------------------------

class ShowWiseBackend:
    """
    Lightweight backend client.

    Kill-switch model
    -----------------
    The backend issues a signed key + UTC expiry timestamp.  The instance
    stores this to disk so it survives process restarts.

    On every ping the backend returns:
      { "kill_switch_enabled": bool,
        "reason": str,
        "new_key": str | null,
        "new_expiry": int | null }   <- UNIX timestamp (UTC)

    A new key is issued when the remaining TTL is <= 2 x PING_INTERVAL.

    If the backend cannot be reached the instance uses the cached key: if the
    key is still valid the service stays up; if it has expired the kill switch
    triggers (fail-closed on expired licence).
    """

    def __init__(self, backend_url: str, api_key: str, org_slug: str):
        self.backend_url      = backend_url.rstrip("/")
        self.api_key          = api_key
        self.org_slug         = org_slug
        self.timeout          = 8

        # --- org config cache ---
        self._org_cache:      Optional[Dict] = None
        self._org_cache_at:   float          = 0.0   # time.time()

        # --- licence key state ---
        self._license_key:    Optional[str]  = None
        self._license_expiry: Optional[int]  = None  # UNIX timestamp UTC
        self._last_ping_at:   float          = 0.0

        self._load_license_from_file()
        logger.info("ShowWise backend client initialised for %s", org_slug)

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _request(self, method: str, endpoint: str,
                 data: Optional[Dict] = None,
                 use_api_key: bool = True) -> Optional[Dict]:
        url     = f"{self.backend_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if use_api_key and self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            resp = requests.request(method, url, json=data,
                                    headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Backend %s %s -> %s", method, endpoint, resp.status_code)
        except requests.exceptions.Timeout:
            logger.error("Backend timeout: %s", endpoint)
        except requests.exceptions.RequestException as exc:
            logger.error("Backend request error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Organisation config (cached)
    # ------------------------------------------------------------------

    def get_organization(self, force: bool = False) -> Optional[Dict]:
        """
        Return the org config dict.  Results are cached for CONFIG_REFRESH
        seconds (env var).  Pass force=True to bypass the cache.
        """
        now = time.time()
        if not force and self._org_cache and (now - self._org_cache_at) < CONFIG_REFRESH:
            return self._org_cache

        result = self._request("GET", f"/api/organizations/{self.org_slug}",
                               use_api_key=False)
        if result and result.get("success"):
            self._org_cache    = result.get("organization")
            self._org_cache_at = now
            logger.info("Org config refreshed for %s", self.org_slug)
            return self._org_cache

        logger.warning("Could not refresh org config; using cached copy")
        return self._org_cache   # might be None on first boot if backend unreachable

    # ------------------------------------------------------------------
    # Kill-switch / licence key
    # ------------------------------------------------------------------

    def check_kill_switch(self) -> Tuple[bool, str]:
        """
        Ping the backend to check the kill switch.

        - Sends the current licence key so the backend can validate it.
        - If the TTL is <= 2 x PING_INTERVAL, the backend returns a new key.
        - The new key is persisted to disk immediately.
        - If the backend is unreachable we fall back to the cached key:
            * valid key  -> allow (False = not suspended)
            * expired    -> kill switch triggers (fail-closed)
        """
        now = int(time.time())

        payload = {
            "org_slug":      self.org_slug,
            "license_key":   self._license_key,
            "ping_interval": PING_INTERVAL,
        }
        result = self._request("POST", "/api/kill-switch/ping", data=payload)

        if result and result.get("success") is not False:
            enabled = bool(result.get("kill_switch_enabled", False))
            reason  = result.get("reason", "")

            # Store any newly issued key
            new_key    = result.get("new_key")
            new_expiry = result.get("new_expiry")
            if new_key and new_expiry:
                self._license_key    = new_key
                self._license_expiry = int(new_expiry)
                self._save_license_to_file()
                logger.info(
                    "Licence key renewed, expires %s",
                    datetime.utcfromtimestamp(self._license_expiry).isoformat(),
                )

            self._last_ping_at = time.time()

            if enabled:
                logger.warning("Kill switch ENABLED: %s", reason)
            return enabled, reason

        # ---- backend unreachable ----
        logger.warning("Kill-switch ping failed — using cached licence key")

        if self._license_expiry and now < self._license_expiry:
            logger.info("Cached key still valid, allowing access")
            return False, ""

        if self._license_expiry:
            logger.error("Cached licence key EXPIRED — triggering kill switch")
            return True, "Service licence could not be verified (key expired)"

        # No key at all -> fail open (first-run grace)
        logger.warning("No licence key on file — allowing access (first-run grace)")
        return False, ""

    # ------------------------------------------------------------------
    # Licence key persistence
    # ------------------------------------------------------------------

    def _save_license_to_file(self):
        try:
            data = {
                "license_key":    self._license_key,
                "license_expiry": self._license_expiry,
                "org_slug":       self.org_slug,
                "saved_at":       int(time.time()),
            }
            Path(LICENSE_KEY_FILE).write_text(json.dumps(data))
        except Exception as exc:
            logger.error("Could not save licence key: %s", exc)

    def _load_license_from_file(self):
        try:
            raw  = Path(LICENSE_KEY_FILE).read_text()
            data = json.loads(raw)
            if data.get("org_slug") == self.org_slug:
                self._license_key    = data.get("license_key")
                self._license_expiry = data.get("license_expiry")
                logger.info(
                    "Loaded licence key from %s (expires %s)",
                    LICENSE_KEY_FILE,
                    datetime.utcfromtimestamp(self._license_expiry).isoformat()
                    if self._license_expiry else "unknown",
                )
        except FileNotFoundError:
            logger.info("No licence key file found at %s", LICENSE_KEY_FILE)
        except Exception as exc:
            logger.warning("Could not load licence key file: %s", exc)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "info",
            log_type: str = "instance", metadata: Optional[Dict] = None) -> bool:
        result = self._request("POST", "/api/log", data={
            "type":     log_type,
            "org_slug": self.org_slug,
            "message":  message,
            "level":    level,
            "metadata": metadata or {},
        })
        return bool(result and result.get("success"))

    def log_info    (self, msg, log_type="instance", metadata=None): self.log(msg, "info",     log_type, metadata)
    def log_warning (self, msg, log_type="instance", metadata=None): self.log(msg, "warning",  log_type, metadata)
    def log_error   (self, msg, log_type="instance", metadata=None): self.log(msg, "error",    log_type, metadata)
    def log_critical(self, msg, log_type="instance", metadata=None): self.log(msg, "critical", log_type, metadata)

    # ------------------------------------------------------------------
    # Uptime heartbeat — no-op, uptime tracking moved to instatus
    # Kept so existing call-sites don't break.
    # ------------------------------------------------------------------

    def send_heartbeat(self, status: str = "online",
                       metadata: Optional[Dict] = None) -> bool:
        """No-op: uptime tracking has been moved to instatus."""
        return True


# ---------------------------------------------------------------------------
# Flask route decorator
# ---------------------------------------------------------------------------

def log_route(log_type: str = "api"):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            backend = get_backend_client()
            if backend:
                from flask import request
                backend.log_info(
                    f"{request.method} {request.path}",
                    log_type=log_type,
                    metadata={"ip": request.remote_addr},
                )
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_backend_client: Optional[ShowWiseBackend] = None


def init_backend_client(app) -> Optional[ShowWiseBackend]:
    global _backend_client

    backend_url = app.config.get("BACKEND_URL") or os.getenv("BACKEND_URL")
    api_key     = app.config.get("BACKEND_API_KEY") or os.getenv("BACKEND_API_KEY")
    org_slug    = (
        app.config.get("ORG_SLUG")
        or os.getenv("ORG_SLUG")
        or app.config.get("ORGANIZATION_SLUG")
        or os.getenv("ORGANIZATION_SLUG")
    )

    if not backend_url or not org_slug:
        logger.warning("Backend integration disabled (BACKEND_URL / ORG_SLUG not set)")
        return None

    _backend_client = ShowWiseBackend(backend_url, api_key or "", org_slug)
    return _backend_client


def get_backend_client() -> Optional[ShowWiseBackend]:
    return _backend_client