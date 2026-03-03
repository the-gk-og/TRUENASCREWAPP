"""routes/calendar.py — Calendar view and ICS export."""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, Response
from flask_login import login_required
from models import Event, User, Shift, ShiftAssignment
from decorators import crew_required

calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/calendar')
@login_required
@crew_required
def calendar():
    events     = Event.query.order_by(Event.event_date).all()
    crew_users = User.query.filter_by(user_role='crew').order_by(User.username).all()
    shifts     = Shift.query.all()
    shifts_data = []
    for shift in shifts:
        assignments  = ShiftAssignment.query.filter_by(shift_id=shift.id).all()
        assigned_cnt = sum(1 for a in assignments if a.status in ('accepted', 'confirmed'))
        shifts_data.append({
            'id': shift.id, 'event_id': shift.event_id,
            'shift_date': shift.shift_date.isoformat(),
            'title': shift.title, 'role': shift.role,
            'positions_needed': shift.positions_needed,
            'assigned_count': assigned_cnt, 'is_open': shift.is_open,
        })
    return render_template('/crew/calendar.html', events=events, now=datetime.now(),
                           crew_users=crew_users, shifts_data=shifts_data)


@calendar_bp.route('/calendar/ics')
def calendar_ics():
    events = Event.query.all()

    ical  = "BEGIN:VCALENDAR\r\n"
    ical += "VERSION:2.0\r\n"
    ical += "PRODID:-//ShowWise//EN\r\n"
    ical += "CALSCALE:GREGORIAN\r\n"
    ical += "METHOD:PUBLISH\r\n"
    ical += "X-WR-CALNAME:ShowWise sync\r\n"
    ical += "X-WR-TIMEZONE:Australia/Sydney\r\n"
    ical += "REFRESH-INTERVAL;VALUE=DURATION:PT1H\r\n"
    ical += (
        "BEGIN:VTIMEZONE\r\nTZID:Australia/Sydney\r\n"
        "BEGIN:STANDARD\r\nDTSTART:20240407T030000\r\nTZOFFSETFROM:+1100\r\n"
        "TZOFFSETTO:+1000\r\nTZNAME:AEST\r\nEND:STANDARD\r\n"
        "BEGIN:DAYLIGHT\r\nDTSTART:20241006T020000\r\nTZOFFSETFROM:+1000\r\n"
        "TZOFFSETTO:+1100\r\nTZNAME:AEDT\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
    )

    def esc(text):
        return (text or '').replace('\n', '\\n').replace(',', '\\,') \
                           .replace(';', '\\;').replace('\\', '\\\\')

    created_time = datetime.now().strftime('%Y%m%dT%H%M%S')

    for event in events:
        start_time = event.event_date.strftime('%Y%m%dT%H%M%S')
        end_time   = ((event.event_end_date if event.event_end_date
                       else event.event_date + timedelta(hours=3))
                      .strftime('%Y%m%dT%H%M%S'))

        desc_parts = [esc(event.description)] if event.description else []
        if getattr(event, 'schedules', None):
            desc_parts.append("\\n\\n--- SCHEDULE ---")
            for s in sorted(event.schedules, key=lambda x: x.scheduled_time):
                desc_parts.append(f"\\n• {s.scheduled_time.strftime('%I:%M %p')} - {esc(s.title)}")
        if event.crew_assignments:
            desc_parts.append("\\n\\n--- CREW ---")
            for a in event.crew_assignments:
                desc_parts.append(f"\\n• {esc(a.crew_member)}" +
                                  (f" ({esc(a.role)})" if a.role else ""))

        ical += "BEGIN:VEVENT\r\n"
        ical += f"UID:{event.id}-showwise@localhost\r\n"
        ical += f"DTSTAMP;TZID=Australia/Sydney:{created_time}\r\n"
        ical += f"DTSTART;TZID=Australia/Sydney:{start_time}\r\n"
        ical += f"DTEND;TZID=Australia/Sydney:{end_time}\r\n"
        ical += f"SUMMARY:{esc(event.title)}\r\n"
        if desc_parts:
            ical += f"DESCRIPTION:{''.join(desc_parts)}\r\n"
        if event.location:
            ical += f"LOCATION:{esc(event.location)}\r\n"
        ical += "STATUS:CONFIRMED\r\nEND:VEVENT\r\n"

        for s in getattr(event, 'schedules', []):
            s_start = s.scheduled_time.strftime('%Y%m%dT%H%M%S')
            s_end   = (s.scheduled_time + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%S')
            ical += "BEGIN:VEVENT\r\n"
            ical += f"UID:{event.id}-schedule-{s.id}@localhost\r\n"
            ical += f"DTSTAMP;TZID=Australia/Sydney:{created_time}\r\n"
            ical += f"DTSTART;TZID=Australia/Sydney:{s_start}\r\n"
            ical += f"DTEND;TZID=Australia/Sydney:{s_end}\r\n"
            ical += f"SUMMARY:{esc(event.title)} - {esc(s.title)}\r\n"
            if s.description:
                ical += f"DESCRIPTION:{esc(s.description)}\r\n"
            ical += "STATUS:CONFIRMED\r\nEND:VEVENT\r\n"

    ical += "END:VCALENDAR\r\n"
    return Response(ical, mimetype='text/calendar',
                    headers={'Content-Disposition': 'inline; filename="showwise_sync.ics"',
                             'Cache-Control': 'no-cache, must-revalidate'})
