"""Security initialisation: response headers and cross-site request protection."""
from urllib.parse import urlparse

from flask import request, jsonify

_UNSAFE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
# The Discord bot is a server-to-server client authenticated by a shared secret, not a browser session.
_EXEMPT_ENDPOINT_PREFIXES = ('discord.',)


def init_security(app):
    """Register security headers and the same-origin check on *app*."""

    @app.before_request
    def reject_cross_site_writes():
        """
        CSRF defence for cookie-authenticated routes without per-form tokens:
        a state-changing request from a browser must come from our own origin.
        Cookies are SameSite=Lax as well, so this is defence in depth.
        Non-browser clients (no Origin / Sec-Fetch-Site) are unaffected; they carry no ambient cookies.
        """
        if request.method not in _UNSAFE_METHODS:
            return None
        endpoint = request.endpoint or ''
        if endpoint.startswith(_EXEMPT_ENDPOINT_PREFIXES):
            return None
        origin = request.headers.get('Origin')
        if origin and origin != 'null':
            if urlparse(origin).netloc.lower() != request.host.lower():
                return jsonify({'error': 'Cross-site request blocked'}), 403
        elif origin == 'null' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return jsonify({'error': 'Cross-site request blocked'}), 403
        return None

    @app.after_request
    def set_security_headers(response):
        h = response.headers
        h.setdefault('X-Content-Type-Options', 'nosniff')
        h.setdefault('X-Frame-Options', 'SAMEORIGIN')
        h.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # Does not restrict scripts/styles (the templates use inline JS and CDNs), but blocks
        # clickjacking, <base> hijacking and plugin content.
        h.setdefault('Content-Security-Policy', "frame-ancestors 'self'; base-uri 'self'; object-src 'none'")
        if request.is_secure:
            h.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    return app
