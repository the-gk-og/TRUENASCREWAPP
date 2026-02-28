# Rocket.Chat Integration Guide for ShowWise

## Overview

ShowWise now integrates with **Rocket.Chat** for enterprise-grade messaging. This provides:

- **Persistent storage** of all messages server-side in Rocket.Chat
- **User management** through Rocket.Chat's user system
- **Channel/Group/DM organization** using Rocket.Chat's room system
- **Read receipts** and message history
- **Scalability** through Rocket.Chat's multi-process architecture
- **Admin console** for message management

## Architecture

```
ShowWise Frontend (Inbox/Chat UI)
           ↓
    Flask Backend (app.py)
           ↓
    Rocket.Chat Integration Module (rocketchat_client.py)
           ↓
    Rocket.Chat Server
           ↓
    Message Storage + User Management
```

## Setup Instructions

### 1. Install Rocket.Chat

#### Option A: Local Development (Docker)

```bash
# Pull and run Rocket.Chat with MongoDB
docker run -d --name rocketchat-mongo -v mongodb_data:/data/db mongo:5.0
docker run -d --name rocketchat \
  -p 3000:3000 \
  -e MONGO_URL=mongodb://rocketchat-mongo:27017/rocketchat \
  -e ROOT_URL=http://localhost:3000 \
  rocketchat/rocket.chat:latest
```

Visit http://localhost:3000 and complete initial setup

#### Option B: Rocket.Chat Cloud

1. Go to https://cloud.rocket.chat/
2. Create account and workspace
3. Copy your server URL (e.g., `https://org-name.rocket.chat`)

#### Option C: Self-Hosted

See https://docs.rocket.chat/deploy for full deployment options

### 2. Create Admin User and Generate API Token

**Via Rocket.Chat Admin Panel:**

1. Login as admin to Rocket.Chat
2. Go to **Administration > Users**
3. Find or create admin user
4. Click user → **View Full Profile**
5. Go to **Personal Access Tokens** section
6. Click **Generate Token**
7. Save the **Token** and **User ID**

### 3. Configure ShowWise

Add to your `.env` file:

```env
# Rocket.Chat Server URL
ROCKETCHAT_URL=http://localhost:3000

# Option 1: Username & Password
ROCKETCHAT_ADMIN_USER=admin
ROCKETCHAT_ADMIN_PASSWORD=your-password

# Option 2: Token (Recommended)
ROCKETCHAT_ADMIN_TOKEN=your-token-here
ROCKETCHAT_ADMIN_USER_ID=your-user-id-here
```

### 4. Install Python Dependencies

```bash
pip install requests  # Already included in requirements
```

### 5. Restart ShowWise

```bash
flask run
# or
python app.py
```

Check logs for:
```
✓ Connected to Rocket.Chat at http://localhost:3000
```

## How It Works

### Message Flow

#### 1. **Sending a Message**

User sends via ShowWise UI → `/api/chat/send` → 
- Ensures sender is Rocket.Chat user
- Creates/gets appropriate room (channel/DM/group)
- Sends message to Rocket.Chat
- Broadcasts SSE update to UI

#### 2. **Receiving Messages**

Frontend calls `/api/chat/inbox/<username>` →
- Gets user's Rocket.Chat rooms
- Fetches recent messages from each room
- Returns in ShowWise format
- Frontend renders Telegram-style inbox

#### 3. **Real-Time Updates**

- Connection established via `/api/chat/stream` (SSE)
- Rocket.Chat webhooks can trigger SSE broadcasts (advanced)
- Frontend auto-refreshes when new messages arrive

### Room Types

| Type | Created By | Visibility | Use Case |
|------|-----------|------------|----------|
| **Channel** | ShowWise API | Public | Team messages, General chat |
| **Private Group** | ShowWise API | Group members only | Group chats, Projects |
| **Direct Message** | ShowWise API | 1-on-1 | DMs between users |
| **Support** | ShowWise API | Admins + sender | Support tickets |

## API Endpoints

### Chat Operations

```
POST /api/chat/send
  Creates message in Rocket.Chat room
  
GET /api/chat/inbox/<username>
  Fetches user's messages from all rooms
  
GET /api/chat/stream
  SSE endpoint for real-time updates
  
POST /api/chat/mark-read
  Marks message as read (RC handles automatically)
  
GET /api/chat/unread-count/<username>
  Returns total unread count
  
POST /api/chat/mark-all-read
  Marks all messages as read
```

### Group Management

```
POST /api/chat/groups
  Creates private group in Rocket.Chat
  
GET /api/chat/groups/<username>
  Lists user's Rocket.Chat groups
  
GET /api/users
  Lists all users for DM/group creation
```

## User Management

Users are automatically created in Rocket.Chat when:

1. They first send a message
2. They're added to a group/channel
3. Someone starts a DM with them

ShowWise user credentials are **not** synced to Rocket.Chat. Users get random passwords in Rocket.Chat.

To manage Rocket.Chat users:
- Use Rocket.Chat admin panel
- Or modify `_get_or_create_rc_user()` in `rocketchat_client.py`

## Room Naming

- **Team channels**: `general`, `crew`, `cast`, etc. (from `team` parameter)
- **Support**: `support`
- **DMs**: Internal to Rocket.Chat (uses `dm.create` API)
- **Groups**: `group_<name>` (auto-generated)

## Troubleshooting

### "Rocket.Chat offline" Error

```
⚠️  Warning: Could not connect to Rocket.Chat. Check credentials and server URL.
```

**Fixes:**
1. Check `ROCKETCHAT_URL` is correct
2. Verify Rocket.Chat server is running: `curl http://localhost:3000`
3. Check `ROCKETCHAT_ADMIN_USER` and password/token
4. Check firewall/network connectivity

### Messages Not Appearing

1. Verify user was created in Rocket.Chat (see Admin > Users)
2. Check room exists in Rocket.Chat
3. Review browser console for API errors
4. Check app logs: `flask run` (verbose mode)

### "User already exists" Error

Rocket.Chat prevents duplicate usernames. If user exists but with different email:
- Update `.env` credentials for existing user
- Or manually delete user in Rocket.Chat admin panel

### SSE Not Working

Real-time updates fail silently if Rocket.Chat is offline:
- Frontend will auto-poll `/api/chat/inbox` instead
- Messages may appear delayed but will load on refresh

## Advanced Configuration

### Custom User Sync

Edit `rocketchat_client.py` `_get_or_create_rc_user()`:

```python
def _get_or_create_rc_user(username, email=None):
    # Add custom logic for user creation
    # Example: sync from LDAP, Active Directory, etc.
    rc = get_rocketchat_client()
    # ... custom implementation
```

### Webhook Notifications

To get real-time Rocket.Chat notifications in ShowWise:

1. Set up webhook in Rocket.Chat admin
2. Point to: `https://your-app/api/chat/webhook`
3. Add webhook handler in `app.py`:

```python
@app.route('/api/chat/webhook', methods=['POST'])
def chat_webhook():
    data = request.json
    msg_obj = {
        'from_name': data['user']['name'],
        'message': data['attachments'][0]['text'],
        'timestamp': datetime.utcnow().isoformat()
    }
    _broadcast_sse(msg_obj)
    return jsonify({'success': True})
```

### Database Backup

Rocket.Chat uses MongoDB. To backup:

```bash
# With Docker
docker exec rocketchat-mongo mongodump --out /backup

# Restore
docker exec rocketchat-mongo mongorestore /backup
```

## Performance Notes

- **Message fetching**: Limited to 50 messages per room per request
- **Room listing**: Depends on number of channels user joins
- **SSE scalability**: In-process queue only suitable for single-process deployments

For production with multiple worker processes, upgrade to:
- **Redis Pub/Sub** for distributed messaging
- **Socket.IO** for WebSocket support
- **Rocket.Chat webhooks** for server-push updates

## Migration from JSON Chat

The new Rocket.Chat integration replaces the old JSON-based chat:

**Old system:**
- Stored in `chat_messages.json` and `chat_groups.json`
- Single-process only
- Lost on app restart

**New system:**
- All data in Rocket.Chat server
- Multi-server capable
- Persistent and backed up

**To migrate existing chats:**

Export JSON messages and import to Rocket.Chat:

```python
import json
from rocketchat_client import get_rocketchat_client

# Load old messages
with open('chat_messages.json') as f:
    old_msgs = json.load(f)['messages']

rc = get_rocketchat_client()

# Send each old message to Rocket.Chat
for msg in old_msgs:
    room_id = rc.get_or_create_channel(msg['team'] or 'general')
    rc.send_message(room_id, msg['message'], metadata={
        'migrated': True,
        'original_date': msg['timestamp'],
        'sender': msg['from_name']
    })
```

## Support & Documentation

- **Rocket.Chat Docs**: https://docs.rocket.chat/
- **Rocket.Chat API**: https://developer.rocket.chat/reference/api
- **ShowWise Issues**: Create issue on your repository
- **Community**: Rocket.Chat community forums

## License & Attribution

- ShowWise: Your license here
- Rocket.Chat: Open Source (AGPL-3.0) - Community Edition free to use
