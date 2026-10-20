"""services/event_times.py — labeled times on an event (Bump-in, Show 1, Show 2 ...).

An event keeps its overall ``event_date`` / ``event_end_date``; when it has labeled
times those two columns are kept equal to the earliest start and latest end, so
every existing query (ordering, reminders, "upcoming", etc.) keeps working.
"""

from models import EventTime


def times_for(event) -> list:
    """The event's labeled times, earliest first."""
    return sorted(event.times, key=lambda t: (t.start_time, t.end_time, t.id or 0))


def sync_span(event) -> None:
    """Make the event's own start/end cover all of its labeled times."""
    ts = times_for(event)
    if not ts:
        return
    event.event_date = min(t.start_time for t in ts)
    event.event_end_date = max(t.end_time for t in ts)
    event.all_day = False


def time_title(event, t) -> str:
    """'{event} - {label}', as shown in calendars and lists."""
    return f'{event.title} - {t.label}'


def _t(dt):
    return dt.strftime('%I:%M %p').lstrip('0')


def _d(dt):
    return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}"


def range_text(t) -> str:
    """'Sat 4 Oct, 4:00 PM – 6:00 PM' for one labeled time."""
    if t.end_time.date() == t.start_time.date():
        return f'{_d(t.start_time)}, {_t(t.start_time)} – {_t(t.end_time)}'
    return f'{_d(t.start_time)}, {_t(t.start_time)} → {_d(t.end_time)}, {_t(t.end_time)}'


def times_text(event, fallback: str = '') -> str:
    """Multi-line text for Discord/email: one 'Label: when' line per time.

    Returns ``fallback`` when the event has no labeled times.
    """
    ts = times_for(event)
    if not ts:
        return fallback
    return '\n'.join(f'{t.label}: {range_text(t)}' for t in ts)


def times_json(event) -> list[dict]:
    return [{'id': t.id, 'label': t.label,
             'start': t.start_time.isoformat(timespec='minutes'),
             'end': t.end_time.isoformat(timespec='minutes')} for t in times_for(event)]


def upcoming_time_rows(events, now):
    """Expand events into display rows: one per labeled time, or one for a plain event.

    Each row: {'event', 'time' (EventTime|None), 'title', 'start', 'end'}.
    Past times are dropped; rows are sorted by start.
    """
    rows = []
    for e in events:
        ts = times_for(e)
        if ts:
            for t in ts:
                if t.end_time >= now:
                    rows.append({'event': e, 'time': t, 'title': time_title(e, t),
                                 'start': t.start_time, 'end': t.end_time})
        else:
            rows.append({'event': e, 'time': None, 'title': e.title,
                         'start': e.event_date, 'end': e.event_end_date or e.event_date})
    rows.sort(key=lambda r: r['start'])
    return rows


def when_text(event, sep: str = ' · ') -> str:
    """One display string for an event's date/time.

    Plain event  -> 'October 04, 2026 at 07:00 PM' (the format used everywhere before).
    With times   -> 'Bump-in: Sun 4 Oct, 4:00 PM – 6:00 PM · Show 1: ...'
    """
    ts = times_for(event)
    if not ts:
        return event.event_date.strftime('%B %d, %Y at %I:%M %p')
    return sep.join(f'{t.label}: {range_text(t)}' for t in ts)
