"""
ShowWise Backend Integration Module

This module handles all communication with the ShowWise Backend:
- Organization configuration loading
- Centralized logging
- Uptime heartbeat pings
- Kill switch checking
- Chat messaging

Author: ShowWise Team
Version: 1.0.0
"""

import os
import requests
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ShowWiseBackend:
    """
    ShowWise Backend Integration Client
    
    This class provides all methods needed to integrate with ShowWise Backend.
    """
    
    def __init__(self, backend_url: str, api_key: str, org_slug: str):
        """
        Initialize the backend client
        
        Args:
            backend_url: Base URL of the backend (e.g., http://localhost:5001)
            api_key: Your API key from the backend dashboard
            org_slug: Your organization slug identifier
        """
        self.backend_url = backend_url.rstrip('/')
        self.api_key = api_key
        self.org_slug = org_slug
        self.timeout = 5  # seconds
        
        # Cache for organization data
        self._org_cache = None
        self._org_cache_time = None
        self._cache_duration = 300  # 5 minutes
        
        logger.info(f"ShowWise Backend client initialized for {org_slug}")
    
    def _make_request(self, method: str, endpoint: str, 
                     data: Optional[Dict] = None,
                     use_api_key: bool = True) -> Optional[Dict]:
        """
        Make HTTP request to backend
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: JSON data to send
            use_api_key: Whether to include API key header
            
        Returns:
            Response JSON or None on error
        """
        url = f"{self.backend_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if use_api_key and self.api_key:
            headers['X-API-Key'] = self.api_key
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Backend request failed: {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Backend request timeout: {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Backend request error: {e}")
            return None
    
    # ==================== ORGANIZATION API ====================
    
    def get_organization(self, force_refresh: bool = False) -> Optional[Dict]:
        """
        Get organization configuration from backend
        
        Args:
            force_refresh: Force refresh cache
            
        Returns:
            Organization configuration dict or None
        """
        # Check cache
        if not force_refresh and self._org_cache:
            if self._org_cache_time:
                age = (datetime.now() - self._org_cache_time).total_seconds()
                if age < self._cache_duration:
                    return self._org_cache
        
        # Fetch from backend
        result = self._make_request('GET', f'/api/organizations/{self.org_slug}', use_api_key=False)
        
        if result and result.get('success'):
            self._org_cache = result.get('organization')
            self._org_cache_time = datetime.now()
            logger.info(f"Organization config loaded: {self._org_cache.get('name')}")
            return self._org_cache
        
        logger.error("Failed to load organization config")
        return None
    
    # ==================== LOGGING API ====================
    
    def log(self, message: str, level: str = 'info', 
            log_type: str = 'instance', metadata: Optional[Dict] = None) -> bool:
        """
        Send log entry to backend
        
        Args:
            message: Log message
            level: Log level (info, warning, error, critical)
            log_type: Log type (api, auth, system, user, instance, chat)
            metadata: Additional metadata dict
            
        Returns:
            True if logged successfully
        """
        data = {
            'type': log_type,
            'org_slug': self.org_slug,
            'message': message,
            'level': level,
            'metadata': metadata or {}
        }
        
        result = self._make_request('POST', '/api/log', data=data)
        return result is not None and result.get('success', False)
    
    def log_info(self, message: str, log_type: str = 'instance', metadata: Optional[Dict] = None):
        """Log info level message"""
        self.log(message, 'info', log_type, metadata)
    
    def log_warning(self, message: str, log_type: str = 'instance', metadata: Optional[Dict] = None):
        """Log warning level message"""
        self.log(message, 'warning', log_type, metadata)
    
    def log_error(self, message: str, log_type: str = 'instance', metadata: Optional[Dict] = None):
        """Log error level message"""
        self.log(message, 'error', log_type, metadata)
    
    def log_critical(self, message: str, log_type: str = 'instance', metadata: Optional[Dict] = None):
        """Log critical level message"""
        self.log(message, 'critical', log_type, metadata)
    
    # ==================== UPTIME API ====================
    
    def send_heartbeat(self, status: str = 'online', metadata: Optional[Dict] = None) -> bool:
        """
        Send uptime heartbeat ping
        
        Args:
            status: Instance status (online, degraded, maintenance)
            metadata: Additional metadata (server stats, version, etc.)
            
        Returns:
            True if ping sent successfully
        """
        data = {
            'org_slug': self.org_slug,
            'status': status,
            'metadata': metadata or {}
        }
        
        result = self._make_request('POST', '/api/uptime/ping', data=data)
        
        if result and result.get('success'):
            logger.debug("Heartbeat sent successfully")
            return True
        
        logger.warning("Failed to send heartbeat")
        return False
    
    # ==================== KILL SWITCH API ====================
    
    def check_kill_switch(self) -> tuple:
        """
        Check if kill switch is enabled
        
        Returns:
            Tuple of (is_enabled, reason)
        """
        result = self._make_request('GET', f'/api/kill-switch/{self.org_slug}', use_api_key=False)
        
        if result and result.get('success'):
            enabled = result.get('kill_switch_enabled', False)
            reason = result.get('reason', 'Service suspended')
            
            if enabled:
                logger.warning(f"Kill switch is ENABLED: {reason}")
            
            return enabled, reason
        
        # If backend is unreachable, allow access (fail open)
        logger.warning("Could not check kill switch - allowing access")
        return False, ''
    
    # ==================== CHAT API ====================
    
    def send_chat_message(self, user_name: str, message: str, 
                         user_email: Optional[str] = None) -> Optional[int]:
        """
        Send chat message to backend
        
        Args:
            user_name: Customer name
            message: Message content
            user_email: Customer email (optional)
            
        Returns:
            Message ID if sent successfully, None otherwise
        """
        data = {
            'org_slug': self.org_slug,
            'user_name': user_name,
            'user_email': user_email,
            'message': message
        }
        
        result = self._make_request('POST', '/api/chat/send', data=data, use_api_key=False)
        
        if result and result.get('success'):
            msg_id = result.get('message_id')
            logger.info(f"Chat message sent: {msg_id}")
            return msg_id
        
        logger.error("Failed to send chat message")
        return None
    
    def get_chat_messages(self, limit: int = 50) -> List[Dict]:
        """
        Get recent chat messages
        
        Args:
            limit: Maximum number of messages (max 50)
            
        Returns:
            List of message dicts
        """
        result = self._make_request('GET', f'/api/chat/messages/{self.org_slug}', use_api_key=False)
        
        if result and result.get('success'):
            messages = result.get('messages', [])
            return messages[-limit:] if len(messages) > limit else messages
        
        return []


# ==================== FLASK DECORATORS ====================

def log_route(log_type: str = 'api'):
    """
    Decorator to automatically log route access
    
    Usage:
        @app.route('/my-route')
        @log_route('api')
        def my_route():
            return 'Hello'
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            backend = get_backend_client()
            if backend:
                from flask import request
                backend.log_info(
                    f"{request.method} {request.path}",
                    log_type=log_type,
                    metadata={'ip': request.remote_addr}
                )
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== GLOBAL CLIENT INSTANCE ====================

_backend_client = None

def init_backend_client(app):
    """
    Initialize backend client from Flask app config
    
    Call this in your app factory or after app creation:
        backend = init_backend_client(app)
    """
    global _backend_client
    
    backend_url = app.config.get('BACKEND_URL') or os.getenv('BACKEND_URL')
    api_key = app.config.get('BACKEND_API_KEY') or os.getenv('BACKEND_API_KEY')
    org_slug = app.config.get('ORG_SLUG') or os.getenv('ORG_SLUG')
    
    if not all([backend_url, org_slug]):
        logger.error("Backend configuration incomplete - integration disabled")
        return None
    
    _backend_client = ShowWiseBackend(backend_url, api_key, org_slug)
    return _backend_client

def get_backend_client() -> Optional[ShowWiseBackend]:
    """Get the global backend client instance"""
    return _backend_client
