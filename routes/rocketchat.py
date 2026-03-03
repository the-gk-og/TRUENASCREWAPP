"""routes/rocketchat.py — Rocket.Chat integration endpoints."""

from flask import Blueprint, jsonify, url_for
from flask_login import login_required, current_user

rocketchat_bp = Blueprint('rocketchat', __name__)


@rocketchat_bp.route('/api/rocketchat/info')
@login_required
def api_rocketchat_info():
    try:
        from rocketchat_client import get_rocketchat_client
        rc = get_rocketchat_client()
    except ImportError:
        return jsonify({'success': False, 'error': 'Rocket.Chat client not available', 'connected': False}), 503

    if not rc.is_connected():
        return jsonify({'success': False, 'error': 'Rocket.Chat is not available', 'connected': False}), 503

    try:
        rc_user_id = rc.get_or_create_user(
            current_user.username, email=current_user.email, name=current_user.username
        )
        if not rc_user_id:
            return jsonify({'success': False, 'error': 'Could not create Rocket.Chat user', 'connected': False}), 500
        return jsonify({
            'success': True, 'connected': True, 'url': rc.server_url,
            'username': current_user.username, 'user_id': rc_user_id,
            'iframe_url': f"{rc.server_url}/home",
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc), 'connected': False}), 500
