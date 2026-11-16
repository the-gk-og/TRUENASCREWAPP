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
