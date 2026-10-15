"""
services/settings_service.py
============================
Tiny admin-editable settings store (AppSetting table, JSON values).
"""

import json

from extensions import db
from models import AppSetting

# Defaults for every known setting
DEFAULTS = {
    'notify.shift_declined.enabled': True,
    'notify.shift_declined.user_ids': [],              # admins/users who get the email
    'notify.shift_declined.include_event_creator': False,
}


def get_setting(key: str, default=None):
    row = db.session.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key) if default is None else default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return DEFAULTS.get(key) if default is None else default


def set_setting(key: str, value, user: str | None = None) -> None:
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        db.session.add(row)
    row.value = json.dumps(value)
    row.updated_by = user
