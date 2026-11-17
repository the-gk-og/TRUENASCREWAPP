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


def shift_decline_recipients(assignment, need_email: bool = True) -> list[User]:
    """Users who should be told about this decline (deduplicated; with an email unless need_email=False)."""
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
        if (u.email or not need_email) and u.id not in seen and u.id != assignment.user_id:
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
    subject = f"Shift declined: {user.shown_name} – {event.title if event else 'event'}"
    rows = [('Person', user.shown_name), ('Event', event.title if event else ''), ('Role', role),
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
            f'<p>{escape(user.shown_name)} has declined a shift. It may need to be covered.</p>'
            f'<table style="border-collapse:collapse">{table}</table>'
            f'<p style="color:#6b7280;font-size:13px;margin-top:24px">Sent by ShowWise. You get this because you are '
            f'listed under Admin Console → Notifications.</p></div>')
    text = f"Shift declined\n\n" + '\n'.join(f'{k}: {v}' for k, v in rows)
    return subject, html, text


def notify_shift_declined(assignment) -> int:
    """Email everyone configured to hear about a declined shift.  Never raises.
    Returns the number of emails that were sent successfully."""
    sent = 0
    try:                                               # Web Push to anyone who opted in (email or not)
        from services.push_service import send_async
        shift, who = assignment.shift, assignment.user
        ev = shift.event
        send_async([dict(user_id=u.id, kind='shift_declined', title=f'Shift declined: {who.shown_name}',
                         body=f"{ev.title if ev else 'Event'} · {shift.role or 'Shift'} · {_when(shift)}",
                         url=f'/events/{ev.id}' if ev else '/shifts/management')
                    for u in shift_decline_recipients(assignment, need_email=False)])
    except Exception as exc:
        print(f'⚠️  Shift decline push failed: {exc}')
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


# --- Shift swaps ---------------------------------------------------------------

def _swap_email(heading: str, intro: str, swap, colour: str = '#1f2937') -> tuple[str, str]:
    """(html, text) for a shift-swap email."""
    shift = swap.assignment.shift
    event = shift.event
    rows = [('Event', event.title if event else ''), ('Role', shift.role or 'Shift'), ('When', _when(shift)),
            ('Offered by', swap.offered_by.shown_name if swap.offered_by else '')]
    if swap.claimed_by:
        rows.append(('Taken by', swap.claimed_by.shown_name))
    if swap.note:
        rows.append(('Note', swap.note))
    table = ''.join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#6b7280">{escape(k)}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(v)}</td></tr>' for k, v in rows)
    html = (f'<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px">'
            f'<h2 style="margin:0 0 12px;color:{colour}">{escape(heading)}</h2><p>{escape(intro)}</p>'
            f'<table style="border-collapse:collapse">{table}</table>'
            f'<p style="color:#6b7280;font-size:13px;margin-top:24px">Sent by ShowWise. See My schedule for details.</p></div>')
    text = f"{heading}\n\n{intro}\n\n" + '\n'.join(f'{k}: {v}' for k, v in rows)
    return html, text


def _send_all(users, subject, html, text) -> int:
    sent = 0
    try:
        from services.email_service import send_html_email
        seen = set()
        for u in users:
            if u and u.email and u.id not in seen:
                seen.add(u.id)
                if send_html_email(subject, u.email, html, text):
                    sent += 1
    except Exception as exc:
        print(f'⚠️  Shift swap notification failed: {exc}')
    return sent


def swap_admin_recipients(swap) -> list[User]:
    """Who approves swaps: the people chosen under Admin Console → Notifications for shift
    cover, or every admin when nobody is chosen."""
    ids = list(get_setting('notify.shift_declined.user_ids') or [])
    users = User.query.filter(User.id.in_(ids)).all() if ids else []
    if not users:
        users = User.query.filter_by(is_admin=True).all()
    return [u for u in users if u.id not in (swap.offered_by_id, swap.claimed_by_id)]


def notify_swap_offered(swap) -> int:
    """Offered to chosen people: tell them.  (Open-to-anyone offers just show on My schedule.)"""
    try:
        from services.shift_swaps import offered_to_ids
        ids = offered_to_ids(swap)
        if not ids:
            return 0
        who = swap.offered_by.shown_name
        html, text = _swap_email('Can you take a shift?', f'{who} is offering you their shift.', swap)
        return _send_all(User.query.filter(User.id.in_(ids)).all(), f'Shift offered to you by {who}', html, text)
    except Exception as exc:
        print(f'⚠️  Shift swap notification failed: {exc}')
        return 0


def notify_swap_claimed(swap) -> int:
    """Someone claimed an offer: the admins approve it; the offerer hears it's in progress."""
    try:
        who = swap.claimed_by.shown_name
        html, text = _swap_email('Shift swap waiting for approval',
                                 f'{who} wants to take this shift. Approve or reject it on My schedule.', swap)
        n = _send_all(swap_admin_recipients(swap), f'Shift swap to approve: {who}', html, text)
        html, text = _swap_email('Someone wants your shift',
                                 f'{who} has claimed the shift you offered. An admin will approve it.', swap)
        return n + _send_all([swap.offered_by], 'Your shift has been claimed', html, text)
    except Exception as exc:
        print(f'⚠️  Shift swap notification failed: {exc}')
        return 0


def notify_swap_decided(swap) -> int:
    """Approved or rejected: tell both people."""
    try:
        if swap.status == 'approved':
            html, text = _swap_email('Shift swap approved', 'The shift has moved to its new person.', swap, '#166534')
            subject = 'Shift swap approved'
        else:
            html, text = _swap_email('Shift swap not approved',
                                     'The shift stays with the person who offered it.', swap, '#991b1b')
            subject = 'Shift swap not approved'
        return _send_all([swap.offered_by, swap.claimed_by], subject, html, text)
    except Exception as exc:
        print(f'⚠️  Shift swap notification failed: {exc}')
        return 0
