"""Cloudflare Integration Module"""
import requests
from flask import request, current_app


class CloudflareIntegration:
    """Cloudflare integration for security features"""
    
    @staticmethod
    def verify_turnstile_token(token):
        """Verify Cloudflare Turnstile CAPTCHA token"""
        try:
            secret = current_app.config.get('CLOUDFLARE_TURNSTILE_SECRET')
            if not secret or not token:
                return False, 'Missing secret or token'
            
            response = requests.post(
                'https://challenges.cloudflare.com/turnstile/v0/siteverify',
                data={
                    'secret': secret,
                    'response': token,
                },
                timeout=5
            )
            
            if response.status_code != 200:
                return False, 'Verification service unavailable'
            
            result = response.json()
            success = result.get('success', False)
            
            if success:
                return True, 'Token verified'
            else:
                error_codes = result.get('error-codes', [])
                return False, f'Token verification failed: {", ".join(error_codes)}'
        
        except Exception as e:
            current_app.logger.error(f'Turnstile verification error: {str(e)}')
            return False, 'Verification error'
    
    @staticmethod
    def get_cf_metadata():
        """Get Cloudflare metadata from request"""
        return {
            'cf_ray': request.headers.get('CF-Ray'),
            'cf_ip': request.headers.get('CF-Connecting-IP'),
            'cf_country': request.headers.get('CF-IPCountry'),
            'cf_threat_score': request.headers.get('CF-Threat-Score'),
            'cf_bot_score': request.headers.get('CF-Bot-Score'),
        }
    
    @staticmethod
    def is_cf_threat(threat_score_threshold=50):
        """Check if Cloudflare marks request as threat"""
        threat_score = request.headers.get('CF-Threat-Score', '0')
        try:
            return int(threat_score) >= threat_score_threshold
        except (ValueError, TypeError):
            return False
