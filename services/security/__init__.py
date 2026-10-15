"""Security initialization module"""

def init_security(app):
    """Initialize security features for Flask app"""
    
    # Set security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' challenges.cloudflare.com; style-src 'self' 'unsafe-inline'"
        return response
    
    # Initialize rate limiter
    from services.security.rate_limiter import rate_limiter
    rate_limiter.init_app(app)
    
    return app
