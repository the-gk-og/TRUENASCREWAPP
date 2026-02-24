"""
Rocket.Chat Integration Module
Handles all communication with Rocket.Chat API for messaging
"""

import os
import requests
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RocketChatClient:
    """Client for Rocket.Chat API integration"""
    
    def __init__(self):
        self.server_url = os.environ.get('ROCKETCHAT_URL', 'http://localhost:3000')
        self.admin_user = os.environ.get('ROCKETCHAT_ADMIN_USER', '')
        self.admin_password = os.environ.get('ROCKETCHAT_ADMIN_PASSWORD', '')
        self.admin_token = os.environ.get('ROCKETCHAT_ADMIN_TOKEN', '')
        self.admin_user_id = os.environ.get('ROCKETCHAT_ADMIN_USER_ID', '')
        
        self.auth_token = None
        self.user_id = None
        self.session = requests.Session()
        
        # Authenticate on init
        self._authenticate()
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None, headers: Dict = None) -> Dict:
        """Make HTTP request to Rocket.Chat API"""
        url = f"{self.server_url}/api/v1{endpoint}"
        
        req_headers = {
            'Content-Type': 'application/json',
            'X-Auth-Token': self.auth_token,
            'X-User-Id': self.user_id
        }
        
        if headers:
            req_headers.update(headers)
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=req_headers, json=data, timeout=10)
            elif method == 'POST':
                response = self.session.post(url, headers=req_headers, json=data, timeout=10)
            elif method == 'PUT':
                response = self.session.put(url, headers=req_headers, json=data, timeout=10)
            elif method == 'DELETE':
                response = self.session.delete(url, headers=req_headers, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Rocket.Chat API error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _authenticate(self):
        """Authenticate with Rocket.Chat using token or credentials"""
        try:
            if self.admin_token and self.admin_user_id:
                # Use provided token and user ID
                self.auth_token = self.admin_token
                self.user_id = self.admin_user_id
                logger.info("✓ Rocket.Chat authenticated with token")
            
            elif self.admin_user and self.admin_password:
                # Login with credentials
                response = self.session.post(
                    f"{self.server_url}/api/v1/login",
                    json={
                        'user': self.admin_user,
                        'password': self.admin_password
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success':
                        self.auth_token = data['data']['authToken']
                        self.user_id = data['data']['userId']
                        logger.info(f"✓ Rocket.Chat authenticated as {self.admin_user}")
                    else:
                        logger.error(f"✗ Rocket.Chat auth failed: {data}")
                else:
                    logger.error(f"✗ Rocket.Chat login failed: {response.status_code}")
            
            else:
                logger.warning("⚠️  No Rocket.Chat credentials provided")
        
        except Exception as e:
            logger.error(f"Rocket.Chat authentication error: {e}")
    
    def is_connected(self) -> bool:
        """Check if authenticated with Rocket.Chat"""
        return bool(self.auth_token and self.user_id)
    
    # ==================== USER METHODS ====================
    
    def get_or_create_user(self, username: str, email: str = None, name: str = None) -> Optional[str]:
        """Get user ID or create user if doesn't exist"""
        try:
            # Try to get existing user
            result = self._make_request('GET', f'/users.info?username={username}')
            
            if result.get('success'):
                return result['user']['_id']
            
            # User doesn't exist, create one
            if email or username:
                create_result = self._make_request(
                    'POST',
                    '/users.create',
                    {
                        'username': username,
                        'email': email or f'{username}@showwise.local',
                        'name': name or username,
                        'password': os.urandom(16).hex(),  # Random password
                        'requirePasswordChange': False
                    }
                )
                
                if create_result.get('success'):
                    logger.info(f"Created Rocket.Chat user: {username}")
                    return create_result['user']['_id']
        
        except Exception as e:
            logger.error(f"Error getting/creating user {username}: {e}")
        
        return None
    
    # ==================== CHANNEL METHODS ====================
    
    def get_or_create_channel(self, channel_name: str, topic: str = None) -> Optional[str]:
        """Get or create a public channel"""
        try:
            # Try to get existing channel
            result = self._make_request('GET', f'/channels.info?roomName={channel_name}')
            
            if result.get('success'):
                return result['channel']['_id']
            
            # Channel doesn't exist, create one
            create_result = self._make_request(
                'POST',
                '/channels.create',
                {
                    'name': channel_name,
                    'topic': topic or f'{channel_name} team channel',
                }
            )
            
            if create_result.get('success'):
                logger.info(f"Created Rocket.Chat channel: {channel_name}")
                return create_result['channel']['_id']
        
        except Exception as e:
            logger.error(f"Error getting/creating channel {channel_name}: {e}")
        
        return None
    
    def add_user_to_channel(self, channel_id: str, username: str) -> bool:
        """Add user to channel"""
        try:
            result = self._make_request(
                'POST',
                '/channels.addAll',
                {
                    'roomId': channel_id,
                    'username': username
                }
            )
            return result.get('success', False)
        except Exception as e:
            logger.error(f"Error adding {username} to channel: {e}")
            return False
    
    # ==================== PRIVATE GROUP METHODS ====================
    
    def get_or_create_group(self, group_name: str, members: List[str] = None) -> Optional[str]:
        """Get or create a private group"""
        try:
            # Try to get existing group
            result = self._make_request('GET', f'/groups.info?roomName={group_name}')
            
            if result.get('success'):
                return result['group']['_id']
            
            # Group doesn't exist, create one
            create_result = self._make_request(
                'POST',
                '/groups.create',
                {
                    'name': group_name,
                }
            )
            
            if create_result.get('success'):
                group_id = create_result['group']['_id']
                
                # Add members to group
                if members:
                    for member in members:
                        self.add_user_to_group(group_id, member)
                
                logger.info(f"Created Rocket.Chat group: {group_name}")
                return group_id
        
        except Exception as e:
            logger.error(f"Error getting/creating group {group_name}: {e}")
        
        return None
    
    def add_user_to_group(self, group_id: str, username: str) -> bool:
        """Add user to group"""
        try:
            result = self._make_request(
                'POST',
                '/groups.addAll',
                {
                    'roomId': group_id,
                    'username': username
                }
            )
            return result.get('success', False)
        except Exception as e:
            logger.error(f"Error adding {username} to group: {e}")
            return False
    
    # ==================== DIRECT MESSAGE METHODS ====================
    
    def get_or_create_direct_message(self, username: str) -> Optional[str]:
        """Get or create direct message with user"""
        try:
            result = self._make_request(
                'POST',
                '/dm.create',
                {'username': username}
            )
            
            if result.get('success'):
                return result['room']['_id']
        
        except Exception as e:
            logger.error(f"Error creating DM with {username}: {e}")
        
        return None
    
    # ==================== MESSAGE METHODS ====================
    
    def send_message(self, room_id: str, text: str, metadata: Dict = None) -> Optional[str]:
        """Send message to room/channel/group/DM"""
        try:
            payload = {
                'roomId': room_id,
                'text': text
            }
            
            # Add metadata if provided
            if metadata:
                payload['attachments'] = [{
                    'text': json.dumps(metadata),
                    'color': '#6366f1'
                }]
            
            result = self._make_request('POST', '/chat.postMessage', payload)
            
            if result.get('success'):
                return result['ts']  # Timestamp (message ID)
        
        except Exception as e:
            logger.error(f"Error sending message to room {room_id}: {e}")
        
        return None
    
    def get_messages(self, room_id: str, count: int = 50, offset: int = 0) -> List[Dict]:
        """Get messages from room"""
        try:
            result = self._make_request(
                'GET',
                f'/channels.messages?roomId={room_id}&count={count}&offset={offset}'
            )
            
            if result.get('success'):
                return result.get('messages', [])
        
        except Exception as e:
            logger.error(f"Error fetching messages from room {room_id}: {e}")
        
        return []
    
    def delete_message(self, room_id: str, msg_id: str) -> bool:
        """Delete message"""
        try:
            result = self._make_request(
                'POST',
                '/chat.delete',
                {
                    'roomId': room_id,
                    'msgId': msg_id
                }
            )
            return result.get('success', False)
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False
    
    # ==================== ROOM INFO METHODS ====================
    
    def get_room_info(self, room_id: str) -> Optional[Dict]:
        """Get room information"""
        try:
            result = self._make_request('GET', f'/channels.info?roomId={room_id}')
            
            if result.get('success'):
                return result.get('channel')
        
        except Exception as e:
            logger.error(f"Error fetching room info: {e}")
        
        return None
    
    def list_user_rooms(self, username: str) -> List[Dict]:
        """List all rooms user is member of"""
        try:
            result = self._make_request('GET', f'/channels.list?updatedSince={datetime.utcnow().isoformat()}')
            
            if result.get('success'):
                return result.get('channels', [])
        
        except Exception as e:
            logger.error(f"Error listing rooms: {e}")
        
        return []


# Create global client instance
_rc_client = None


def init_rocketchat():
    """Initialize Rocket.Chat client"""
    global _rc_client
    _rc_client = RocketChatClient()
    return _rc_client


def get_rocketchat_client() -> RocketChatClient:
    """Get Rocket.Chat client instance"""
    global _rc_client
    if _rc_client is None:
        _rc_client = RocketChatClient()
    return _rc_client
