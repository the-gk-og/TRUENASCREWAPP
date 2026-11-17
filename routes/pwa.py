"""routes/pwa.py — the pieces that let ShowWise be installed and opened with no connection.

/sw.js       the service worker. It has to be served from the site root to cover every page.
/offline     the small page shown when a page was never saved on this device.
"""
import os

from flask import Blueprint, current_app, render_template, send_from_directory

pwa_bp = Blueprint('pwa', __name__)


@pwa_bp.route('/sw.js')
def service_worker():
    response = send_from_directory(os.path.join(current_app.static_folder, 'js'), 'service-worker.js',
                                   mimetype='application/javascript')
    # Always re-checked, so a new version of the worker is picked up straight away
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@pwa_bp.route('/offline')
def offline():
    return render_template('offline.html')


# ---------------------------------------------------------------------------
# Web Push: each device opts in from Settings (see services/push_service.py)
# ---------------------------------------------------------------------------
from flask import jsonify, request                                    # noqa: E402
from flask_login import current_user, login_required                  # noqa: E402

from extensions import db                                             # noqa: E402
from models import PushSubscription                                   # noqa: E402
from services import push_service                                     # noqa: E402


@pwa_bp.route('/push/key')
@login_required
def push_key():
    return jsonify({'publicKey': push_service.vapid_keys()[0]})


@pwa_bp.route('/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    sub = (request.get_json(silent=True) or {}).get('subscription') or {}
    endpoint, keys = str(sub.get('endpoint') or ''), sub.get('keys') or {}
    if not endpoint.startswith('https://') or len(endpoint) > 700 or not keys.get('p256dh') or not keys.get('auth'):
        return jsonify({'error': 'Invalid subscription'}), 400
    row = PushSubscription.query.filter_by(endpoint=endpoint).first() or PushSubscription(endpoint=endpoint)
    row.user_id = current_user.id                    # a shared phone moves to whoever opted in last
    row.p256dh, row.auth = str(keys['p256dh'])[:200], str(keys['auth'])[:100]
    row.user_agent = (request.headers.get('User-Agent') or '')[:300]
    db.session.add(row)
    db.session.commit()
    return jsonify({'success': True})


@pwa_bp.route('/push/unsubscribe', methods=['POST'])
@login_required
def push_unsubscribe():
    endpoint = str((request.get_json(silent=True) or {}).get('endpoint') or '')
    PushSubscription.query.filter_by(endpoint=endpoint, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'success': True})


@pwa_bp.route('/push/preferences', methods=['GET', 'PUT'])
@login_required
def push_preferences():
    if request.method == 'PUT':
        on = (request.get_json(silent=True) or {}).get('kinds') or {}
        off = push_service.disabled_kinds(current_user.id)       # only the kinds sent are changed
        off = {k for k in off if on.get(k) is not True} | {k for k, v in on.items() if v is False}
        push_service.set_disabled_kinds(current_user.id, off)
    off = push_service.disabled_kinds(current_user.id)
    return jsonify({'kinds': [{'key': k, 'label': label, 'hint': hint, 'on': k not in off}
                              for k, (label, hint) in push_service.KINDS.items()],
                    'devices': PushSubscription.query.filter_by(user_id=current_user.id).count()})


@pwa_bp.route('/push/test', methods=['POST'])
@login_required
def push_test():
    n = push_service.send_to_user(current_user.id, 'test', 'ShowWise notifications are on',
                                  'Tap to open your schedule.', '/crew/my-schedule')
    return jsonify({'success': n > 0, 'sent': n})
