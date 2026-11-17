"""
running_order.py
================
An event's running order: the acts / segments on the bill (a band, a changeover, the interval),
each with an ordered set of songs, planned lengths, start times worked out from the order, and the
actual times taken from the live clock on the night.

Stored in ``CrewRunItem``: top-level rows are acts, rows with a ``parent_id`` are songs. Older run
lists are flat, so every row is simply an act with no songs.

Planned times
-------------
The running order starts at ``run_start_for(event)``. Each act lasts its own length if one is
typed, otherwise the sum of its songs' lengths. Songs start one after another from their act's
start. Rows with no length take no time (and are counted as "missing").

Live clock
----------
``go(item)`` starts a row now: anything else still running ends (except the act a song belongs
to, which is started too if it wasn't). ``stop`` ends everything; ``reset`` clears the actual
times. Drift ("running 4 min late") compares the actual start of the row that is on now (or the
last finish, once the show is over) with its planned time.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from extensions import db
from models import CrewRunItem
from services.report_service import duration_minutes, run_start_for

QUIET_KINDS = ('changeover', 'interval', 'break', 'intermission', 'doors', 'curfew')


def is_quiet(kind: str | None) -> bool:
    """Changeovers, intervals and other gaps between acts (drawn quieter than the acts)."""
    k = (kind or '').strip().lower()
    return any(q in k for q in QUIET_KINDS)


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def items_for(event_id: int) -> list[CrewRunItem]:
    return (CrewRunItem.query.filter_by(event_id=event_id)
            .order_by(CrewRunItem.order_number, CrewRunItem.id).all())


def tree(event_id: int, items: list[CrewRunItem] | None = None) -> list[tuple[CrewRunItem, list[CrewRunItem]]]:
    """[(act, [songs])] in order. A song whose act is missing is shown as an act."""
    items = items_for(event_id) if items is None else items
    ids = {i.id for i in items}
    songs: dict[int, list[CrewRunItem]] = {}
    acts = []
    for i in items:
        if i.parent_id and i.parent_id in ids:
            songs.setdefault(i.parent_id, []).append(i)
        else:
            acts.append(i)
    return [(a, songs.get(a.id, [])) for a in acts]


def sequence(event_id: int) -> list[CrewRunItem]:
    """Every row in show order: act, its songs, next act..."""
    out = []
    for act, songs in tree(event_id):
        out.append(act)
        out.extend(songs)
    return out


def _mins(a: datetime | None, b: datetime | None) -> float | None:
    return None if a is None or b is None else (b - a).total_seconds() / 60


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec='seconds') if dt else None


def plan(event) -> dict:
    """The running order with planned and actual times, ready for the page (JSON) or the PDF."""
    start = run_start_for(event)
    clock = start
    acts, missing, timed = [], 0, False

    def row(item, at, length, n):
        actual_len = _mins(item.started_at, item.ended_at)
        return {
            'id': item.id, 'n': n, 'parent_id': None,
            'title': item.title, 'duration': item.duration or '', 'kind': item.kind or '',
            'description': item.description or '', 'notes': item.notes or '',
            'minutes': duration_minutes(item.duration), 'length': length,
            'planned': at, 'planned_end': at + timedelta(minutes=length) if length is not None else None,
            'started_at': item.started_at, 'ended_at': item.ended_at,
            'late': _mins(at, item.started_at) if item.started_at else None,
            'actual_length': actual_len,
            'live': bool(item.started_at and not item.ended_at),
            'quiet': is_quiet(item.kind),
        }

    for n, (act, songs) in enumerate(tree(event.id), start=1):
        own = duration_minutes(act.duration)
        song_lengths = [duration_minutes(s.duration) for s in songs]
        song_sum = sum(m for m in song_lengths if m is not None) if any(m is not None for m in song_lengths) else None
        length = own if own is not None else song_sum
        if length is None:
            missing += 1
        else:
            timed = True
        a = row(act, clock, length, n)
        a['songs_length'] = song_sum
        a['songs'] = []
        at = clock
        for sn, (s, m) in enumerate(zip(songs, song_lengths), start=1):
            r = row(s, at, m, sn)
            r['parent_id'] = act.id
            a['songs'].append(r)
            at += timedelta(minutes=m or 0)
        acts.append(a)
        clock += timedelta(minutes=length or 0)

    flat = [x for a in acts for x in [a, *a['songs']]]
    live = [x for x in flat if x['live']]
    current = live[-1] if live else None                 # the song on now, else the act
    started = [x for x in flat if x['started_at']]
    drift = None
    if current:
        drift = current['late']
    elif started:
        last = max(started, key=lambda x: (x['ended_at'] or x['started_at']))
        if last['ended_at'] and last['planned_end']:
            drift = _mins(last['planned_end'], last['ended_at'])
        else:
            drift = last['late']
    nxt = next_item_id(flat)
    return {
        'start': start, 'end': clock, 'total': _mins(start, clock), 'timed': timed, 'missing': missing,
        'acts': acts, 'count': len(acts), 'songs': sum(len(a['songs']) for a in acts),
        'current_id': current['id'] if current else None,
        'next_id': nxt,
        'drift': drift,
        'expected_end': clock + timedelta(minutes=drift) if drift is not None and timed else None,
        'started': bool(started), 'live': bool(live),
        'finished': bool(started) and not live and nxt is None,
    }


def next_item_id(flat: list[dict]) -> int | None:
    """What "Next" starts: the row after the one on now, or after the last one that ran."""
    if not flat:
        return None
    last = None
    for i, x in enumerate(flat):
        if x['started_at']:
            last = i
    live = [i for i, x in enumerate(flat) if x['live']]
    if live:
        last = live[-1]
    if last is None:
        return flat[0]['id']
    return flat[last + 1]['id'] if last + 1 < len(flat) else None


def to_json(p: dict) -> dict:
    """plan() with datetimes as ISO strings and minutes rounded, for the page."""
    def conv(v):
        if isinstance(v, datetime):
            return _iso(v)
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    out = conv(p)
    out['now'] = _iso(now())
    return out


# ---------------------------------------------------------------- live clock

def go(item: CrewRunItem, at: datetime | None = None) -> None:
    """Start this row now: whatever else is running ends, and a song's act starts with it."""
    at = at or now()
    keep = {item.id}
    if item.parent:
        keep.add(item.parent.id)
        if not item.parent.started_at or item.parent.ended_at:
            item.parent.started_at, item.parent.ended_at = item.parent.started_at or at, None
    for other in CrewRunItem.query.filter_by(event_id=item.event_id).filter(
            CrewRunItem.started_at.isnot(None), CrewRunItem.ended_at.is_(None)).all():
        if other.id not in keep:
            other.ended_at = at
    item.started_at, item.ended_at = at, None


def stop(event_id: int, at: datetime | None = None) -> None:
    at = at or now()
    for other in CrewRunItem.query.filter_by(event_id=event_id).filter(
            CrewRunItem.started_at.isnot(None), CrewRunItem.ended_at.is_(None)).all():
        other.ended_at = at


def reset(event_id: int) -> None:
    for i in CrewRunItem.query.filter_by(event_id=event_id).all():
        i.started_at = i.ended_at = None


# ---------------------------------------------------------------- ordering

def renumber(event_id: int) -> None:
    """1, 2, 3... for the acts, and again within each act's songs."""
    for n, (act, songs) in enumerate(tree(event_id), start=1):
        act.order_number = n
        for sn, s in enumerate(songs, start=1):
            s.order_number = sn


def next_number(event_id: int, parent_id: int | None) -> int:
    q = db.session.query(db.func.max(CrewRunItem.order_number)).filter_by(event_id=event_id)
    q = q.filter(CrewRunItem.parent_id.is_(None)) if parent_id is None else q.filter(CrewRunItem.parent_id == parent_id)
    return (q.scalar() or 0) + 1


def apply_tree(event_id: int, order: list) -> None:
    """Reorder from [{'id': act, 'songs': [ids]}, ...]. Unknown ids are ignored; rows left out keep
    their place after the ones given. Songs can move between acts; an act can't become a song."""
    items = {i.id: i for i in CrewRunItem.query.filter_by(event_id=event_id).all()}
    seen = set()
    n = 0
    for entry in order:
        aid = entry.get('id') if isinstance(entry, dict) else entry
        act = items.get(aid if isinstance(aid, int) else None)
        if not act or aid in seen:
            continue
        seen.add(aid)
        n += 1
        act.parent_id, act.order_number = None, n
        sn = 0
        for sid in (entry.get('songs') or [] if isinstance(entry, dict) else []):
            song = items.get(sid if isinstance(sid, int) else None)
            if not song or sid in seen or song.songs:
                continue                                  # an act with songs can't go inside another
            seen.add(sid)
            sn += 1
            song.parent_id, song.order_number = act.id, sn
    for act, songs in tree(event_id, sorted(items.values(), key=lambda i: (i.order_number, i.id))):
        if act.id not in seen:
            n += 1
            act.order_number = n
    db.session.flush()
    renumber(event_id)


def copy_to(src_event_id: int, dst_event_id: int) -> None:
    """Copy a running order to another event (planned parts only, not the actual times)."""
    for act, songs in tree(src_event_id):
        new = CrewRunItem(event_id=dst_event_id, order_number=act.order_number, title=act.title,
                          description=act.description, duration=act.duration, kind=act.kind, notes=act.notes)
        db.session.add(new)
        db.session.flush()
        for s in songs:
            db.session.add(CrewRunItem(event_id=dst_event_id, parent_id=new.id, order_number=s.order_number,
                                       title=s.title, description=s.description, duration=s.duration,
                                       kind=s.kind, notes=s.notes))
