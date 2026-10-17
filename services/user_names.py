"""
services/user_names.py
======================
Everything about *who someone is called*.

* ``username``     - what a person types to log in. Not case-sensitive.
* ``display_name`` - "Name" in the UI: what other people see on shifts, events, notes...
                     Falls back to the username when it has not been set.
* ``email``        - can also be used to log in. Not case-sensitive.

Several tables remember a person by their username string (``crew_member``,
``created_by``, ``added_by`` ...). :func:`name_for` turns those into a display name, and
:func:`rename_user_references` keeps them pointing at the right person if a username changes.
"""

import re

from flask import g, has_request_context
from sqlalchemy import func
from sqlalchemy.orm import ColumnProperty

from extensions import db
from models import User

DISPLAY_NAME_MIN = 2
DISPLAY_NAME_MAX = 60
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f<>]')

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Columns that store a username string rather than a user id
REFERENCE_COLUMNS = ('created_by', 'crew_member', 'added_by', 'assigned_by',
                     'uploaded_by', 'updated_by', 'assigned_to')


# ---------------------------------------------------------------------------
# Lookups (case-insensitive)
# ---------------------------------------------------------------------------

def _one_or_none(rows):
    return rows[0] if len(rows) == 1 else None


def find_user_by_username(username: str):
    """Exact match wins; otherwise a case-insensitive match (only if it is unambiguous)."""
    username = (username or '').strip()
    if not username:
        return None
    exact = User.query.filter(User.username == username).first()
    if exact:
        return exact
    return _one_or_none(User.query.filter(func.lower(User.username) == username.lower()).limit(2).all())


def find_user_by_email(email: str):
    email = (email or '').strip()
    if not email:
        return None
    exact = User.query.filter(User.email == email).first()
    if exact:
        return exact
    return _one_or_none(User.query.filter(func.lower(User.email) == email.lower()).limit(2).all())


def find_user_by_login(identifier: str):
    """Log in with a username *or* an email address, in any letter case."""
    return find_user_by_username(identifier) or find_user_by_email(identifier)


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or '').strip()))


def username_problem(username: str, minimum: int = 3, maximum: int = 80):
    """Return a message if this username isn't allowed, else None.

    "@" is not allowed: people can log in with an email address too, and a username that
    looks like someone else's email would get in the way of them signing in.
    """
    username = (username or '').strip()
    if not (minimum <= len(username) <= maximum):
        return f'Username must be {minimum}–{maximum} characters'
    if '@' in username:
        return 'Usernames cannot contain "@" (you can log in with your email instead)'
    if _CONTROL_CHARS.search(username):
        return 'Username contains characters that are not allowed'
    return None


def username_taken(username: str, exclude_id: int | None = None) -> bool:
    q = User.query.filter(func.lower(User.username) == (username or '').strip().lower())
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.first() is not None


def email_taken(email: str, exclude_id: int | None = None) -> bool:
    q = User.query.filter(func.lower(User.email) == (email or '').strip().lower())
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.first() is not None


# ---------------------------------------------------------------------------
# Display name
# ---------------------------------------------------------------------------

def clean_display_name(raw):
    """Return ``(name_or_None, error_or_None)``. Blank is allowed and means "use my username"."""
    name = ' '.join(str(raw or '').split())            # trim + collapse runs of whitespace
    if not name:
        return None, None
    if _CONTROL_CHARS.search(name):
        return None, 'Name cannot contain < > or control characters'
    if not (DISPLAY_NAME_MIN <= len(name) <= DISPLAY_NAME_MAX):
        return None, f'Name must be {DISPLAY_NAME_MIN}–{DISPLAY_NAME_MAX} characters'
    return name, None


def name_for(username):
    """Display name for a username string stored on a record (``created_by`` etc.).

    Looked up once per request. Unknown names (e.g. "Discord Bot", deleted users) come back unchanged.
    """
    if not username:
        return username or ''
    if not has_request_context():
        user = find_user_by_username(username)
        return user.shown_name if user else username
    cache = getattr(g, '_display_names', None)
    if cache is None:
        cache = g._display_names = {}
        for uname, dname in User.query.with_entities(User.username, User.display_name).all():
            cache[(uname or '').lower()] = (dname or '').strip() or uname
    return cache.get(str(username).lower(), username)


def sync_cast_names(user: User):
    """Cast cards keep a copy of the actor's name; keep it in step with the person's Name."""
    from models import CastMember
    CastMember.query.filter_by(user_id=user.id).update({'actor_name': user.shown_name})


# ---------------------------------------------------------------------------
# Username changes
# ---------------------------------------------------------------------------

def rename_user_references(old: str, new: str) -> int:
    """Re-point every record that remembers this person by username. Returns rows changed.

    Without this, renaming someone would orphan their shifts-by-name, event ownership, notes, etc.
    """
    if not old or old == new:
        return 0
    changed = 0
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        for col in REFERENCE_COLUMNS:
            attr = getattr(cls, col, None)
            prop = getattr(attr, 'property', None)
            if isinstance(prop, ColumnProperty):
                changed += (db.session.query(cls).filter(attr == old)
                            .update({col: new}, synchronize_session=False))
    return changed
