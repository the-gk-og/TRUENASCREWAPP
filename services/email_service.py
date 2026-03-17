"""
email_service.py
================
Centralised email service for ShowWise.

All email sending, template loading, and text-fallback generation lives here.
app.py should only call the public functions at the bottom of this file.

Template files live in the  email_templates/  folder.
Each template is a plain HTML file using {{ variable }} placeholders.
A tiny regex-based renderer is used so you don't need Jinja2 loaded separately
(Flask's Jinja env is used when available, falling back to simple substitution).

Usage in app.py:
    from email_service import (
        send_email,
        send_html_email,
        send_invite_email,
        send_crew_assignment_email,
        send_shift_assignment_email,
        send_cast_assignment_email,
        send_cast_welcome_email,
        send_password_reset_email,
        send_password_changed_email,
        send_event_reminder_email,
        send_welcome_email,
)

#Werkzeug
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

#Google
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oa
    )
"""

from __future__ import annotations

import os
import re
import json
from datetime import datetime
from typing import Optional

# Flask-Mail is injected at init time via init_email_service()
_mail = None
_app  = None

# Path to the email templates folder (relative to this file's directory)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "email_templates")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_email_service(app, mail):
    """Call this once in app.py after creating the Mail instance.

    Example:
        from email_service import init_email_service
        init_email_service(app, mail)
    """
    global _mail, _app
    _app  = app
    _mail = mail


# ---------------------------------------------------------------------------
# Template loading & rendering
# ---------------------------------------------------------------------------

def _load_template(name: str) -> str:
    """Load an HTML template file from email_templates/."""
    path = os.path.join(TEMPLATES_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Email template not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _render(template_name: str, context: dict) -> str:
    """Render a template with the given context dictionary.

    Supports:
      - {{ variable }}          — simple substitution
      - {% if condition %} ... {% elif ... %} ... {% else %} ... {% endif %}
      - {% for item in list %} ... {% endfor %}  (basic, no nested loops)
    """
    html = _load_template(template_name)

    # ---- for loops ----------------------------------------------------------
    def replace_for(match):
        var, iterable_name, body = match.group(1), match.group(2), match.group(3)
        items = context.get(iterable_name, [])
        result = []
        for item in items:
            inner_ctx = {**context, var: item}
            result.append(_simple_substitute(body, inner_ctx))
        return "".join(result)

    html = re.sub(
        r"\{%-?\s*for\s+(\w+)\s+in\s+(\w+)\s*-?%\}(.*?)\{%-?\s*endfor\s*-?%\}",
        replace_for,
        html,
        flags=re.DOTALL,
    )

    # ---- if / elif / else / endif -------------------------------------------
    def replace_if(match):
        full = match.group(0)
        # Tokenise the block into (condition, body) pairs + optional else body
        # Supports: {% if X %} ... {% elif Y %} ... {% else %} ... {% endif %}
        tokens = re.split(
            r"\{%-?\s*(?:elif\s+(.*?)|else)\s*-?%\}",
            full[full.index("%}") + 2 : full.rfind("{%")],
        )
        conditions_raw = re.findall(
            r"\{%-?\s*if\s+(.*?)\s*-?%\}|\{%-?\s*elif\s+(.*?)\s*-?%\}",
            full,
        )
        conds = [c[0] or c[1] for c in conditions_raw]

        for idx, cond in enumerate(conds):
            if _eval_condition(cond, context):
                parts = re.split(
                    r"\{%-?\s*(?:elif\b.*?|else)\s*-?%\}",
                    full[full.index("%}") + 2 :],
                    flags=re.DOTALL,
                )
                return parts[idx] if idx < len(parts) else ""

        # Try else branch
        else_match = re.search(
            r"\{%-?\s*else\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}",
            full,
            flags=re.DOTALL,
        )
        if else_match:
            return else_match.group(1)
        return ""

    html = re.sub(
        r"\{%-?\s*if\b.*?\{%-?\s*endif\s*-?%\}",
        replace_if,
        html,
        flags=re.DOTALL,
    )

    # ---- simple {{ variable }} substitution ---------------------------------
    html = _simple_substitute(html, context)
    return html


def _simple_substitute(text: str, ctx: dict) -> str:
    """Replace {{ key }} with ctx[key], leaving unknown keys empty."""
    def replacer(m):
        key = m.group(1).strip()
        val = ctx.get(key, "")
        return str(val) if val is not None else ""

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, text)


def _eval_condition(cond: str, ctx: dict) -> bool:
    """Very simple condition evaluator for template if-blocks.
    Supports:  variable_name  and  not variable_name
    """
    cond = cond.strip()
    if cond.startswith("not "):
        return not bool(ctx.get(cond[4:].strip()))
    return bool(ctx.get(cond))


# ---------------------------------------------------------------------------
# Core send helpers
# ---------------------------------------------------------------------------

def send_email(subject: str, recipient: str, body: str) -> bool:
    """Send a plain-text email."""
    if not _app or not _app.config.get("MAIL_USERNAME"):
        print(f"⚠️  Email not configured – skipping: {subject}")
        return False
    try:
        from flask_mail import Message
        msg = Message(subject, recipients=[recipient])
        msg.body = body
        _mail.send(msg)
        return True
    except Exception as exc:
        print(f"❌ Failed to send email to {recipient}: {exc}")
        return False


def send_html_email(
    subject: str,
    recipient: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """Send an HTML email with an optional plain-text fallback."""
    if not _app or not _app.config.get("MAIL_USERNAME"):
        print(f"⚠️  Email not configured – skipping: {subject}")
        return False
    try:
        from flask_mail import Message
        msg = Message(subject, recipients=[recipient])
        msg.html = html_body
        if text_body:
            msg.body = text_body
        _mail.send(msg)
        return True
    except Exception as exc:
        print(f"❌ Failed to send HTML email to {recipient}: {exc}")
        return False


def _org_defaults(org: Optional[dict] = None) -> dict:
    if org is None:
        org = {}
    return {
        "org_name":      org.get("name", os.getenv("ORG_NAME", "ShowWise")),
        "primary_color": org.get("primary_color", "#6366f1"),
        "static_url":    org.get("static_url", os.getenv("STATIC_URL", "/static")),
    }


# ---------------------------------------------------------------------------
# Public email-sending functions
# ---------------------------------------------------------------------------

def send_invite_email(
    recipient_email: str,
    recipient_name: str,
    signup_url: str,
    invite_code: str,
    role_label: str,
    expires_at,          # datetime or ISO string
    org: Optional[dict] = None,
) -> bool:
    """Send a beautifully formatted invite email."""
    org_ctx = _org_defaults(org)

    # Format expiry
    expires_str = ""
    if expires_at:
        try:
            dt = (
                datetime.fromisoformat(expires_at)
                if isinstance(expires_at, str)
                else expires_at
            )
            expires_str = dt.strftime("%B %d, %Y at %I:%M %p UTC")
        except Exception:
            expires_str = str(expires_at)

    signup_url_base  = signup_url.split("?")[0]
    signup_url_short = signup_url_base.replace("https://", "").replace("http://", "")

    context = {
        **org_ctx,
        "recipient_name":  recipient_name,
        "signup_url":      signup_url,
        "signup_url_base": signup_url_base,
        "signup_url_short": signup_url_short,
        "invite_code":     invite_code,
        "role_label":      role_label,
        "expires_str":     expires_str,
    }

    html_body = _render("invite.html", context)

    text_body = (
        f"Hi {recipient_name},\n\n"
        f"You've been invited to join {org_ctx['org_name']} on ShowWise!\n"
        f"Role: {role_label}\n\n"
        f"Sign up here: {signup_url}\n"
        + (f"Expires: {expires_str}\n" if expires_str else "")
        + f"\nOr visit {signup_url_base} and enter code: {invite_code}\n\n"
        f"This is a single-use invite — please don't share it.\n\n"
        f"See you on the crew,\n{org_ctx['org_name']} · Powered by ShowWise"
    )

    subject = f"You're invited to join {org_ctx['org_name']} on ShowWise"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_crew_assignment_email(
    recipient_email: str,
    username: str,
    event_title: str,
    event_date: str,
    event_location: str,
    role: str,
    event_description: str = "",
    org: Optional[dict] = None,
) -> bool:
    """Notify a crew member they've been assigned to an event."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username":          username,
        "event_title":       event_title,
        "event_date":        event_date,
        "event_location":    event_location or "TBD",
        "role":              role or "Crew Member",
        "event_description": event_description,
    }

    html_body = _render("crew_assignment.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"You have been assigned to: {event_title}\n\n"
        f"Date: {event_date}\n"
        f"Location: {event_location or 'TBD'}\n"
        f"Role: {role or 'Crew Member'}\n"
        + (f"Description: {event_description}\n" if event_description else "")
        + f"\nLog in to ShowWise to view details.\n\n"
        f"ShowWise Team"
    )

    subject = f"🎭 You're assigned to: {event_title}"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_shift_assignment_email(
    recipient_email: str,
    username: str,
    event_title: str,
    shift_title: str,
    shift_date: str,
    shift_end_time: str,
    role: str,
    location: str,
    positions_needed: int,
    description: str = "",
    org: Optional[dict] = None,
) -> bool:
    """Notify a crew member they've been assigned to a shift."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username":         username,
        "event_title":      event_title,
        "shift_title":      shift_title,
        "shift_date":       shift_date,
        "shift_end_time":   shift_end_time,
        "role":             role or "General Crew",
        "location":         location or "TBD",
        "positions_needed": str(positions_needed),
        "description":      description,
    }

    html_body = _render("shift_assignment.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"You have been assigned to a shift for {event_title}!\n\n"
        f"Shift: {shift_title}\n"
        f"Date: {shift_date} – {shift_end_time}\n"
        f"Role: {role or 'General Crew'}\n"
        f"Location: {location or 'TBD'}\n"
        f"Positions Needed: {positions_needed}\n"
        + (f"Notes: {description}\n" if description else "")
        + f"\nLog in to ShowWise to accept or reject this assignment.\n\n"
        f"ShowWise Team"
    )

    subject = f"🎬 Shift Assignment: {shift_title} – {event_title}"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_cast_assignment_email(
    recipient_email: str,
    username: str,
    event_title: str,
    event_date: str,
    event_location: str,
    character_name: str,
    role_type: str,
    org: Optional[dict] = None,
) -> bool:
    """Notify a cast member they've been cast in a production."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username":        username,
        "event_title":     event_title,
        "event_date":      event_date,
        "event_location":  event_location or "TBD",
        "character_name":  character_name,
        "role_type":       role_type or "Cast",
    }

    html_body = _render("cast_assignment.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"You have been cast in: {event_title}\n"
        f"Character: {character_name}\n"
        f"Role: {role_type}\n"
        f"Date: {event_date}\n"
        f"Location: {event_location or 'TBD'}\n\n"
        f"Log in to ShowWise Cast Portal to view details.\n\n"
        f"Break a leg!\nShowWise Production Team"
    )

    subject = f"🎭 You've been cast in: {event_title}"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_cast_welcome_email(
    recipient_email: str,
    username: str,
    password: str,
    org: Optional[dict] = None,
) -> bool:
    """Send account credentials to a newly created cast member."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username": username,
        "password": password,
    }

    html_body = _render("cast_welcome.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"Welcome to the ShowWise Cast Portal!\n\n"
        f"Your account has been created by your production team.\n\n"
        f"Username: {username}\n"
        f"Password: {password}\n\n"
        f"IMPORTANT: Please change your password after your first login.\n\n"
        f"Break a leg!\nShowWise Production Team"
    )

    subject = "🎭 Welcome to ShowWise Cast Portal"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_password_reset_email(
    recipient_email: str,
    username: str,
    reset_url: str,
    org: Optional[dict] = None,
) -> bool:
    """Send a password-reset link."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username":  username,
        "reset_url": reset_url,
    }

    html_body = _render("password_reset.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"You requested a password reset for your ShowWise account.\n\n"
        f"Click here to reset your password:\n{reset_url}\n\n"
        f"This link expires in 24 hours.\n\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"ShowWise Team"
    )

    subject = f"Password Reset Request – {org_ctx['org_name']}"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_password_changed_email(
    recipient_email: str,
    username: str,
    changed_at: Optional[str] = None,
    org: Optional[dict] = None,
) -> bool:
    """Confirm that a password has been changed."""
    org_ctx = _org_defaults(org)
    if changed_at is None:
        changed_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    context = {
        **org_ctx,
        "username":   username,
        "changed_at": changed_at,
    }

    html_body = _render("password_changed.html", context)

    text_body = (
        f"Hello {username},\n\n"
        f"Your ShowWise password has been successfully changed.\n\n"
        f"Changed at: {changed_at}\n\n"
        f"If you did not make this change, please contact your administrator immediately.\n\n"
        f"ShowWise Team"
    )

    subject = "Password Changed – ShowWise"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_event_reminder_email(
    recipient_email: str,
    username: str,
    event_title: str,
    event_date: str,
    event_location: str,
    role: str,
    reminder_type: str = "1_week",   # 'today' | 'tomorrow' | '1_week'
    org: Optional[dict] = None,
) -> bool:
    """Send an event reminder email (1 week / tomorrow / today)."""
    org_ctx = _org_defaults(org)
    context = {
        **org_ctx,
        "username":       username,
        "event_title":    event_title,
        "event_date":     event_date,
        "event_location": event_location or "TBD",
        "role":           role or "Crew Member",
        "reminder_type":  reminder_type,
    }

    html_body = _render("event_reminder.html", context)

    if reminder_type == "today":
        headline = "🚨 EVENT TODAY"
        blurb    = "Your event is happening TODAY!"
    elif reminder_type == "tomorrow":
        headline = "⏰ Event Tomorrow"
        blurb    = "Your event is tomorrow – get ready!"
    else:
        headline = "📅 Event in 1 Week"
        blurb    = "Your event is coming up in one week."

    text_body = (
        f"Hello {username},\n\n"
        f"{blurb}\n\n"
        f"Event: {event_title}\n"
        f"Date:  {event_date}\n"
        f"Location: {event_location or 'TBD'}\n"
        f"Role: {role or 'Crew Member'}\n\n"
        f"ShowWise Team"
    )

    subject = f"{headline}: {event_title}"
    return send_html_email(subject, recipient_email, html_body, text_body)


def send_welcome_email(
    recipient_email: str,
    username: str,
    user_role: str,
    login_url: str,
    org: Optional[dict] = None,
) -> bool:
    """Send a simple welcome email after signup (invite-code flow)."""
    org_ctx = _org_defaults(org)

    subject   = f"Welcome to {org_ctx['org_name']}!"
    text_body = (
        f"Hello {username},\n\n"
        f"Your account has been created successfully!\n\n"
        f"Username: {username}\n"
        f"Role: {user_role.capitalize()}\n\n"
        f"You can log in at: {login_url}\n\n"
        f"Welcome to the team!\nShowWise"
    )

    # Reuse a minimal HTML version (no separate template needed for welcome)
    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f3f4f6;padding:40px 0;margin:0;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:14px;overflow:hidden;
                  box-shadow:0 4px 20px rgba(0,0,0,0.07);">
      <tr><td style="background:linear-gradient(135deg,{org_ctx['primary_color']},#a855f7);
                     padding:36px 44px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:28px;">🎉 Welcome to ShowWise!</h1>
      </td></tr>
      <tr><td style="padding:36px 44px;">
        <p style="font-size:16px;color:#374151;">Hi <strong>{username}</strong>,</p>
        <p style="font-size:15px;color:#4b5563;line-height:1.7;">
          Your <strong>{org_ctx['org_name']}</strong> account has been created.
          You've joined as <strong>{user_role.capitalize()}</strong>.
        </p>
        <p style="margin:28px 0 0;font-size:14px;color:#6b7280;">
          Log in at: <a href="{login_url}" style="color:{org_ctx['primary_color']};">{login_url}</a>
        </p>
      </td></tr>
      <tr><td style="background:#f9fafb;padding:18px 44px;text-align:center;">
        <p style="margin:0;font-size:12px;color:#d1d5db;">
          &copy; {org_ctx['org_name']} &middot; Powered by ShowWise
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    return send_html_email(subject, recipient_email, html_body, text_body)