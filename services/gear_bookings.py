"""services/gear_bookings.py — when an event holds its gear, and clashes between events.

A pick list line linked to equipment is a reservation for the event's time window;
a unit on a line (PickListUnit) is a reservation of that specific unit.
"""

from datetime import datetime, time as dtime


def event_window(event):
    """(start, end) the event holds its equipment for: its own time plus every labeled
    time (Bump-in, Show 1 ...). All-day events and events with no end hold gear until
    the end of their last day."""
    start = event.event_date
    end = event.event_end_date or event.event_date
    for t in getattr(event, 'times', []) or []:
        start, end = min(start, t.start_time), max(end, t.end_time)
    if event.all_day:
        start = datetime.combine(start.date(), dtime.min)
    if event.all_day or (not event.event_end_date and not getattr(event, 'times', None)):
        end = datetime.combine(end.date(), dtime.max)
    return start, max(start, end)


def overlaps(a, b):
    """Do two (start, end) windows share any time?"""
    return a[0] <= b[1] and b[0] <= a[1]


def unit_reserved_elsewhere(unit, event):
    """Other events whose pick lists reserve this unit and whose windows overlap `event`."""
    win = event_window(event)
    seen, out = set(), []
    for link in unit.pick_links:
        other = link.pick_list_item.event
        if other is None or other.id == event.id or other.id in seen:
            continue
        if overlaps(win, event_window(other)):
            seen.add(other.id)
            out.append(other)
    return out
