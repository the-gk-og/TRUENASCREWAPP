"""Keep the test suite hermetic.

config.py calls load_dotenv(), which walks up from the source tree and loads the
first .env it finds (in a git worktree that is the main checkout's .env). That
silently injected a real SECRET_KEY / MAIL_* config into the tests, so results
depended on the developer's machine. Disable .env loading and drop app-config
variables inherited from the shell before any app module is imported.
"""
import os

import pytest

os.environ['PYTHON_DOTENV_DISABLED'] = '1'

_APP_ENV_VARS = (
    'SECRET_KEY', 'FLASK_ENV', 'DATABASE_URL', 'SECURITY_DATABASE_URL',
    'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USE_TLS', 'MAIL_USERNAME', 'MAIL_PASSWORD',
    'MAIL_DEFAULT_SENDER',
)
for _k in list(os.environ):
    if _k in _APP_ENV_VARS or _k.startswith('SUPPORT_'):
        del os.environ[_k]


@pytest.fixture(autouse=True)
def _restore_environ():
    """Undo any os.environ changes a test makes, so they can't leak into later tests."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
