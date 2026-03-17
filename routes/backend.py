"""routes/backend.py — ShowWise backend integration: kill-switch ping scheduler and org config cache."""

import os
import json
import time
import atexit
import logging
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env-var config  (read once at import time)
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


PING_INTERVAL    = _env_int('PING_INTERVAL',   300)   # seconds between kill-switch pings
CONFIG_REFRESH   = _env_int('CONFIG_REFRESH', 3600)   # seconds between org-config cache refreshes
LICENSE_KEY_FILE = os.getenv('LICENSE_KEY_FILE', '.license_key')


# ---------------------------------------------------------------------------
# Kill-switch in-memory state
# Read by before_request in app.py — updated by the background scheduler below.
# ---------------------------------------------------------------------------

_kill_switch_enabled = False
_kill_switch_reason  = ''


def get_kill_switch_state() -> Tuple[bool, str]:
    """Return the current in-memory kill-switch state (no network call)."""
    return _kill_switch_enabled, _kill_switch_reason


# ---------------------------------------------------------------------------
# ShowWiseBackend client
# ---------------------------------------------------------------------------

class ShowWiseBackend:
    """
    Lightweight client for the ShowWise backend service.

    Kill-switch / licence-key model
    --------------------------------
    The backend issues a signed key + UTC expiry timestamp.
    The instance stores this to disk so it survives restarts.

    On every ping the backend returns:
        { "kill_switch_enabled": bool,
          "reason": str,
          "new_key": str | null,
          "new_expiry": int | null }   <- UNIX timestamp (UTC)

    A renewal is issued when remaining TTL <= 2 x PING_INTERVAL.

    If the backend is unreachable:
        - valid cached key  -> service stays up  (fail-open while valid)
        - expired/no key    -> kill switch fires  (fail-closed)
    """

    def __init__(self, backend_url: str, api_key: str, org_slug: str):
        self.backend_url = backend_url.rstrip('/')
        self.api_key     = api_key
        self.org_slug    = org_slug
        self.timeout     = 8

        # Org config cache
        self._org_cache:    Optional[dict] = None
        self._org_cache_at: float          = 0.0

        # Licence key state
        self._license_key:    Optional[str] = None
        self._license_expiry: Optional[int] = None   # UNIX timestamp UTC

        self._load_license_from_file()
        logger.info('ShowWise backend client initialised for %s', org_slug)

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _request(self, method: str, endpoint: str,
                 data: Optional[dict] = None,
                 use_api_key: bool = True) -> Optional[dict]:
        url     = f'{self.backend_url}{endpoint}'
        headers = {'Content-Type': 'application/json'}
        if use_api_key and self.api_key:
            headers['X-API-Key'] = self.api_key
        try:
            resp = requests.request(method, url, json=data,
                                    headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            logger.warning('Backend %s %s -> %s', method, endpoint, resp.status_code)
        except requests.exceptions.Timeout:
            logger.error('Backend timeout: %s', endpoint)
        except requests.exceptions.RequestException as exc:
            logger.error('Backend request error: %s', exc)
        return None

    # ------------------------------------------------------------------
    # Org config (cached)
    # ------------------------------------------------------------------

    def get_organization(self, force: bool = False) -> Optional[dict]:
        """
        Return org config dict.  Cached for CONFIG_REFRESH seconds.
        Pass force=True to bypass the cache.
        """
        now = time.time()
        if not force and self._org_cache and (now - self._org_cache_at) < CONFIG_REFRESH:
            return self._org_cache

        result = self._request('GET', f'/api/organizations/{self.org_slug}',
                               use_api_key=False)
        if result and result.get('success'):
            self._org_cache    = result.get('organization')
            self._org_cache_at = now
            logger.info('Org config refreshed for %s', self.org_slug)
            return self._org_cache

        logger.warning('Could not refresh org config; using cached copy')
        return self._org_cache

    # ------------------------------------------------------------------
    # Kill-switch / licence key
    # ------------------------------------------------------------------

    def check_kill_switch(self) -> Tuple[bool, str]:
        """
        Ping the backend, refresh the licence key if needed, and return
        (kill_switch_enabled, reason).

        Falls back to the on-disk key when the backend is unreachable.
        """
        now = int(time.time())

        payload = {
            'org_slug':      self.org_slug,
            'license_key':   self._license_key,
            'ping_interval': PING_INTERVAL,
        }
        result = self._request('POST', '/api/kill-switch/ping', data=payload)

        if result and result.get('success') is not False:
            enabled = bool(result.get('kill_switch_enabled', False))
            reason  = result.get('reason', '')

            new_key    = result.get('new_key')
            new_expiry = result.get('new_expiry')
            if new_key and new_expiry:
                # Backend issued a new / renewed key — update memory and disk
                self._license_key    = new_key
                self._license_expiry = int(new_expiry)
                logger.info(
                    'Licence key renewed, expires %s',
                    datetime.utcfromtimestamp(self._license_expiry).isoformat(),
                )

            # Always persist whatever key we currently hold after a successful
            # ping — this ensures the file exists even when no renewal was
            # issued (i.e. the key is still valid and not near expiry).
            if self._license_key:
                self._save_license_to_file()

            if enabled:
                logger.warning('Kill switch ENABLED: %s', reason)
            return enabled, reason

        # ---- backend unreachable ----
        logger.warning('Kill-switch ping failed — using cached licence key')

        if self._license_expiry and now < self._license_expiry:
            logger.info('Cached key still valid, allowing access')
            return False, ''

        if self._license_expiry:
            logger.error('Cached licence key EXPIRED — triggering kill switch')
            return True, 'Service licence could not be verified (key expired)'

        logger.warning('No licence key on file — allowing access (first-run grace)')
        return False, ''

    # ------------------------------------------------------------------
    # Licence key persistence
    # ------------------------------------------------------------------

    def _save_license_to_file(self):
        try:
            data = {
                'license_key':    self._license_key,
                'license_expiry': self._license_expiry,
                'org_slug':       self.org_slug,
                'saved_at':       int(time.time()),
            }
            key_path = Path(LICENSE_KEY_FILE).resolve()
            key_path.write_text(json.dumps(data))
            logger.debug('Licence key saved to %s', key_path)
        except Exception as exc:
            logger.error('Could not save licence key to %s: %s', LICENSE_KEY_FILE, exc)

    def _load_license_from_file(self):
        try:
            raw  = Path(LICENSE_KEY_FILE).read_text()
            data = json.loads(raw)
            if data.get('org_slug') == self.org_slug:
                self._license_key    = data.get('license_key')
                self._license_expiry = data.get('license_expiry')
                logger.info(
                    'Loaded licence key from %s (expires %s)',
                    LICENSE_KEY_FILE,
                    datetime.utcfromtimestamp(self._license_expiry).isoformat()
                    if self._license_expiry else 'unknown',
                )
        except FileNotFoundError:
            logger.info('No licence key file found at %s', LICENSE_KEY_FILE)
        except Exception as exc:
            logger.warning('Could not load licence key file: %s', exc)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = 'info',
            log_type: str = 'instance', metadata: Optional[dict] = None) -> bool:
        result = self._request('POST', '/api/log', data={
            'type':     log_type,
            'org_slug': self.org_slug,
            'message':  message,
            'level':    level,
            'metadata': metadata or {},
        })
        return bool(result and result.get('success'))

    def log_info    (self, msg, log_type='instance', metadata=None): self.log(msg, 'info',     log_type, metadata)
    def log_warning (self, msg, log_type='instance', metadata=None): self.log(msg, 'warning',  log_type, metadata)
    def log_error   (self, msg, log_type='instance', metadata=None): self.log(msg, 'error',    log_type, metadata)
    def log_critical(self, msg, log_type='instance', metadata=None): self.log(msg, 'critical', log_type, metadata)

    # ------------------------------------------------------------------
    # Uptime heartbeat — no-op (uptime moved to instatus)
    # Kept so any existing call-sites don't break.
    # ------------------------------------------------------------------

    def send_heartbeat(self, status: str = 'online',
                       metadata: Optional[dict] = None) -> bool:
        """No-op: uptime tracking has been moved to instatus."""
        return True


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_backend_client: Optional[ShowWiseBackend] = None


def init_backend_client(app) -> Optional[ShowWiseBackend]:
    """Initialise the global backend client from Flask app config."""
    global _backend_client

    backend_url = app.config.get('BACKEND_URL') or os.getenv('BACKEND_URL')
    api_key     = app.config.get('BACKEND_API_KEY') or os.getenv('BACKEND_API_KEY')
    org_slug    = (
        app.config.get('ORG_SLUG')
        or os.getenv('ORG_SLUG')
        or app.config.get('ORGANIZATION_SLUG')
        or os.getenv('ORGANIZATION_SLUG')
    )

    if not backend_url or not org_slug:
        logger.warning('Backend integration disabled (BACKEND_URL / ORG_SLUG not set)')
        return None

    _backend_client = ShowWiseBackend(backend_url, api_key or '', org_slug)
    return _backend_client


def get_backend_client() -> Optional[ShowWiseBackend]:
    """Return the global backend client instance."""
    return _backend_client


# ---------------------------------------------------------------------------
# Background ping scheduler
# ---------------------------------------------------------------------------

def start_ping_scheduler(app, backend: ShowWiseBackend):
    """
    Start a background APScheduler job that pings the backend every
    PING_INTERVAL seconds to refresh the kill-switch / licence-key state.

    - Updates the module-level _kill_switch_enabled / _kill_switch_reason
      globals so before_request in app.py can read them at zero network cost.
    - Automatically stores any renewed licence key to disk.
    - Does NOT send uptime data — use instatus for that.

    Runs once immediately at startup so the flag is populated before the
    first request is served.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    global _kill_switch_enabled, _kill_switch_reason

    def _ping():
        global _kill_switch_enabled, _kill_switch_reason
        with app.app_context():
            try:
                enabled, reason = backend.check_kill_switch()
                _kill_switch_enabled = enabled
                _kill_switch_reason  = reason
            except Exception as exc:
                logger.error('Ping scheduler error: %s', exc)

    # Populate state immediately before serving any requests
    _ping()

    scheduler = BackgroundScheduler()
    scheduler.add_job(_ping, 'interval', seconds=PING_INTERVAL)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    print(f'✓ Kill-switch ping scheduler started (interval {PING_INTERVAL}s)')