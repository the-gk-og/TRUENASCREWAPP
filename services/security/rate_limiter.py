"""Rate Limiting and Throttling Module"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import current_app, request
from extensions import db
from datetime import datetime, timedelta
import requests


class RateLimiter:
    """Rate limiting manager"""
    
    def __init__(self):
        self.limiter = None
    
    def init_app(self, app):
        """Initialize rate limiter with Flask app"""
        self.limiter = Limiter(
            app=app,
            key_func=lambda: self._get_ip(),
            storage_uri=app.config.get('REDIS_URL', 'memory://'),
            default_limits=["200 per day", "50 per hour"],
        )
    
    @staticmethod
    def _get_ip():
        """Get IP address from Cloudflare or proxies"""
        if request.headers.get('CF-Connecting-IP'):
            return request.headers.get('CF-Connecting-IP')
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        if request.headers.get('X-Real-IP'):
            return request.headers.get('X-Real-IP')
        return get_remote_address()
    
    def report_rate_limit_to_backend(self, ip_address, endpoint, status_code=429):
        """Report rate limit hit to security backend"""
        try:
            backend_url = current_app.config.get('SECURITY_BACKEND_URL', 'http://localhost:5001')
            api_key = current_app.config.get('API_INTEGRATION_KEY', '')
            
            if not api_key or not backend_url:
                return False
            
            data = {
                'ip_address': ip_address,
                'endpoint': endpoint,
                'status_code': status_code,
                'service': current_app.config.get('APP_INSTANCE_NAME', 'main'),
            }
            
            headers = {'X-API-Key': api_key}
            
            response = requests.post(
                f'{backend_url}/api/ip/rate-limit',
                json=data,
                headers=headers,
                timeout=5
            )
            
            return response.status_code == 200
        except Exception as e:
            current_app.logger.error(f'Failed to report rate limit: {str(e)}')
            return False


# Global rate limiter instance
rate_limiter = RateLimiter()
