"""
services/shift_notifications.py
===============================
Emails sent when something happens to a shift.

Right now: a crew member declines a shift -> the people chosen in
Admin Console -> Notifications are emailed.
"""

from html import escape

from models import User
from services.settings_service import get_setting


def shift_decline_recipients(assignment) -> list[User]:
    """Users who should be told about this decline (deduplicated, with an email)."""
    if not get_setting('notify.shift_declined.enabled'):
        return []
    ids = list(get_setting('notify.shift_declined.user_ids') or [])
    users = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
    out = [users[i] for i in ids if i in users]
    if get_setting('notify.shift_declined.include_event_creator'):
        ev = assignment.shift.event
        creator = User.query.filter_by(username=ev.created_by).first() if ev and ev.created_by else None
        if creator and creator.id not in users:
            out.append(creator)
    seen, result = set(), []
    for u in out:
        if u.email and u.id not in seen and u.id != assignment.user_id:
            seen.add(u.id)
            result.append(u)
    return result


def _when(shift) -> str:
    s, e = shift.shift_date, shift.shift_end_date
    fmt = lambda d: d.strftime('%a %d %b %Y, %I:%M %p').replace(' 0', ' ')
    return f"{fmt(s)} – {e.strftime('%I:%M %p').lstrip('0')}" if s.date() == e.date() else f"{fmt(s)} → {fmt(e)}"


def build_decline_email(assignment) -> tuple[str, str, str]:
    """(subject, html, text) for a declined shift."""
    shift, user = assignment.shift, assignment.user
    event = shift.event
    role = shift.role or 'Shift'
    reason = (assignment.decline_reason or '').strip()
    subject = f"Shift declined: {user.username} – {event.title if event else 'event'}"
    rows = [('Person', user.username), ('Event', event.title if event else ''), ('Role', role),
            ('When', _when(shift))]
    if event and event.location:
        rows.append(('Where', event.location))
    if reason:
        rows.append(('Reason', reason))
    table = ''.join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#6b7280">{escape(k)}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(v)}</td></tr>' for k, v in rows)
    html = (f'<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px">'
            f'<h2 style="margin:0 0 12px;color:#991b1b">Shift declined</h2>'
            f'<p>{escape(user.username)} has declined a shift. It may need to be covered.</p>'
            f'<table style="border-collapse:collapse">{table}</table>'
            f'<p style="color:#6b7280;font-size:13px;margin-top:24px">Sent by ShowWise. You get this because you are '
            f'listed under Admin Console → Notifications.</p></div>')
    text = f"Shift declined\n\n" + '\n'.join(f'{k}: {v}' for k, v in rows)
    return subject, html, text


def notify_shift_declined(assignment) -> int:
    """Email everyone configured to hear about a declined shift.  Never raises.
    Returns the number of emails that were sent successfully."""
    sent = 0
    try:
        from services.email_service import send_html_email
        recipients = shift_decline_recipients(assignment)
        if not recipients:
            return 0
        subject, html, text = build_decline_email(assignment)
        for u in recipients:
            if send_html_email(subject, u.email, html, text):
                sent += 1
    except Exception as exc:
        print(f'⚠️  Shift decline notification failed: {exc}')
    return sent
