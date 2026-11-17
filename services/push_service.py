"""services/push_service.py — Web Push notifications (pywebpush).

VAPID keys come from VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (base64url raw keys) and
VAPID_SUBJECT (mailto:… or https://…). If unset, a key pair is generated on first use and
kept in AppSetting 'push.vapid', so it survives restarts (subscriptions are tied to it).
Dead subscriptions (404/410 from the push service) are deleted.  Never raises to callers.
"""
import base64, json, os, threading

from extensions import db
from models import PushPreference, PushSubscription

KINDS = {
    'shift_assigned': ('New shifts', "When you're given a shift"),
    'shift_reminder': ('Shift reminders', 'The day before a shift'),
    'shift_declined': ('Declined shifts', 'When someone turns down a shift you look after'),
    'event_assigned': ('Added to an event', "When you're added to an event's crew"),
}
_keys = None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def vapid_keys() -> tuple[str, str, str]:
    """(public, private, subject); generates and stores a pair if none is configured."""
    global _keys
    subject = os.environ.get('VAPID_SUBJECT') or 'mailto:admin@showwise.local'
    pub, priv = os.environ.get('VAPID_PUBLIC_KEY'), os.environ.get('VAPID_PRIVATE_KEY')
    if pub and priv:
        return pub, priv, subject
    if _keys:
        return (*_keys, subject)
    from services.settings_service import get_setting, set_setting
    stored = get_setting('push.vapid', {}) or {}
    if not stored.get('public'):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization as ser
        k = ec.generate_private_key(ec.SECP256R1())
        stored = {'private': _b64(k.private_numbers().private_value.to_bytes(32, 'big')),
                  'public': _b64(k.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint))}
        set_setting('push.vapid', stored, 'system')
        db.session.commit()
    _keys = (stored['public'], stored['private'])
    return (*_keys, subject)


def _webpush(subscription_info, data, private_key, claims):
    """The only thing that touches the network; tests replace it."""
    from pywebpush import webpush
    return webpush(subscription_info=subscription_info, data=data, vapid_private_key=private_key,
                   vapid_claims=claims, timeout=10, ttl=24 * 3600)


def disabled_kinds(user_id) -> set:
    row = db.session.get(PushPreference, user_id)
    try:
        return set(json.loads(row.disabled_kinds)) if row else set()
    except ValueError:
        return set()


def set_disabled_kinds(user_id, kinds) -> None:
    row = db.session.get(PushPreference, user_id) or PushPreference(user_id=user_id)
    row.disabled_kinds = json.dumps(sorted(k for k in kinds if k in KINDS))
    db.session.add(row)
    db.session.commit()


def send_to_user(user_id, kind, title, body='', url='/dashboard', tag=None) -> int:
    """Push to every device of this user who wants `kind`. Returns how many got it."""
    try:
        if kind in disabled_kinds(user_id):
            return 0
        subs = PushSubscription.query.filter_by(user_id=user_id).all()
        if not subs:
            return 0
        _, priv, subject = vapid_keys()
        data = json.dumps({'title': title, 'body': body, 'url': url, 'tag': tag or kind})
        sent = 0
        for s in subs:
            try:
                _webpush({'endpoint': s.endpoint, 'keys': {'p256dh': s.p256dh, 'auth': s.auth}},
                         data, priv, {'sub': subject})
                sent += 1
            except Exception as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status in (404, 410):
                    db.session.delete(s)
                else:
                    print(f'⚠️  Push to user {user_id} failed: {exc}')
        db.session.commit()
        return sent
    except Exception as exc:
        db.session.rollback()
        print(f'⚠️  Push failed: {exc}')
        return 0


def send_async(jobs: list[dict]) -> None:
    """Run send_to_user(**job) for each job after the request (inline when TESTING)."""
    from flask import current_app
    if not jobs:
        return
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            for job in jobs:
                send_to_user(**job)
    if app.config.get('TESTING'):
        run()
    else:
        threading.Thread(target=run, daemon=True, name='web-push').start()
