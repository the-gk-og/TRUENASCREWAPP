"""services/notification_service.py — Discord notifications and scheduled reminders."""

import os, threading, requests
from datetime import datetime, timedelta

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')
notification_tracker: dict = {}


def send_discord_event_announcement(event) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        embed = {
            "title":       f"New Event: {event.title}",
            "description": event.description or "No description provided",
            "color":       6366239,
            "fields": [
                {"name": "📅 Date & Time", "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'), "inline": False},
                {"name": "📍 Location",   "value": event.location or "TBD", "inline": False},
                {"name": "🎟️ Event ID",    "value": str(event.id),           "inline": True},
            ],
            "footer": {"text": f"Event ID: {event.id}"},
        }
        r = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        if r.status_code == 204:
            notification_tracker.setdefault(event.id, {})['created'] = True
            print(f"✓ Posted new event to Discord: {event.title}")
            return True
    except Exception as exc:
        print(f"❌ Discord announcement error: {exc}")
    return False


def schedule_event_notifications(event) -> None:
    if not DISCORD_WEBHOOK_URL:
        return

    def _send(event_id, notification_type):
        try:
            from flask import current_app
            # Import inside thread to avoid app-context issues
            from app import app as _app
            with _app.app_context():
                from models import Event, User, CrewAssignment
                ev = Event.query.get(event_id)
                if not ev:
                    return
                crew_names = [a.crew_member for a in ev.crew_assignments]
                mentions   = []
                for name in crew_names:
                    u = User.query.filter_by(username=name).first()
                    if u and u.discord_id:
                        mentions.append(f"<@{u.discord_id}>")
                if notification_tracker.get(event_id, {}).get(notification_type):
                    return
                colour_map = {
                    '1_week_before': (16776960, f"📅 Event in 1 Week: {ev.title}",   "Your event is coming up next week!"),
                    '1_day_before':  (16753920, f"⏰ Event Tomorrow: {ev.title}",    "Your event is happening tomorrow!"),
                    'event_today':   (16711680, f"🎭 EVENT TODAY: {ev.title}",      "Your event is happening RIGHT NOW!"),
                }
                colour, title, desc = colour_map[notification_type]
                embed = {
                    "title": title, "description": desc, "color": colour,
                    "fields": [
                        {"name": "📅 Date & Time", "value": ev.event_date.strftime('%B %d, %Y at %I:%M %p'), "inline": False},
                        {"name": "📍 Location",    "value": ev.location or "TBD", "inline": False},
                    ],
                }
                content = " ".join(mentions) if mentions else "(no crew members linked to Discord)"
                r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content, "embeds": [embed]})
                if r.status_code == 204:
                    notification_tracker.setdefault(event_id, {})[notification_type] = True
        except Exception as exc:
            print(f"❌ Notification error ({notification_type}): {exc}")

    now        = datetime.utcnow()
    event_time = event.event_date
    delays = {
        '1_week_before': (event_time - timedelta(days=7)   - now).total_seconds(),
        '1_day_before':  (event_time - timedelta(days=1)   - now).total_seconds(),
        'event_today':   (event_time.replace(hour=8, minute=0, second=0) - now).total_seconds(),
    }
    for ntype, delay in delays.items():
        if delay > 0:
            t = threading.Timer(delay, _send, args=[event.id, ntype])
            t.daemon = True
            t.start()
