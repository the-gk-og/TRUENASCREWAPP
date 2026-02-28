# Rocket.Chat Integration - Quick Start Guide

## What Changed

Your ShowWise chat feature has been upgraded from **JSON file storage** to **Rocket.Chat**, an enterprise messaging platform.

### Before (JSON-based)
- ❌ Single-process only
- ❌ Messages lost on restart
- ❌ No built-in user management
- ❌ Limited scalability

### After (Rocket.Chat)
- ✅ Multi-process ready
- ✅ Persistent, backed-up messages
- ✅ Full user management system
- ✅ Scales to thousands of users
- ✅ Professional admin console
- ✅ Message history & search
- ✅ Read receipts & notifications

## Files Modified

```
✅ app.py
   - Added Rocket.Chat import
   - Replaced JSON chat helpers with RC API calls
   - Updated all chat endpoints: /api/chat/send, /api/chat/inbox, etc.
   - Auto-creates Rocket.Chat users and rooms

✅ rocketchat_client.py (NEW)
   - Rocket.Chat API wrapper class
   - Handles authentication (token or credentials)
   - User, channel, group, DM management
   - Message sending/receiving

✅ .env.example
   - Added Rocket.Chat configuration options
   - Copy to .env and update with your credentials

✅ README/rocketchat_integration.md
   - Full integration documentation
   - Setup instructions
   - Architecture diagrams
   - Troubleshooting guide
```

## Quickest Path to Production (5 minutes)

### 1. Setup Rocket.Chat Locally (Docker)

```bash
docker-compose up -d
# Runs at http://localhost:3000
```

Create file `docker-compose.yml`:
```yaml
version: '3.8'
services:
  mongodb:
    image: mongo:5.0
    volumes:
      - mongodb_data:/data/db
  
  rocketchat:
    image: rocketchat/rocket.chat:latest
    ports:
      - "3000:3000"
    depends_on:
      - mongodb
    environment:
      MONGO_URL: mongodb://mongodb:27017/rocketchat
      ROOT_URL: http://localhost:3000
    volumes:
      - rocketchat_data:/app/uploads

volumes:
  mongodb_data:
  rocketchat_data:
```

### 2. Create Admin & Token

1. Visit http://localhost:3000
2. Setup admin account
3. Go to **Administration > Users**
4. Click admin user → **Personal Access Tokens**
5. Generate token, copy it

### 3. Update .env

```bash
cp .env.example .env
```

Then edit `.env`:
```env
ROCKETCHAT_URL=http://localhost:3000
ROCKETCHAT_ADMIN_TOKEN=your-token-from-step-2
ROCKETCHAT_ADMIN_USER_ID=your-user-id-from-step-2
```

### 4. Restart ShowWise

```bash
flask run
# Check for: ✓ Connected to Rocket.Chat at http://localhost:3000
```

**Done!** Your chat is now using Rocket.Chat.

## Production Deployment

### Option 1: Rocket.Chat Cloud (Easiest)

1. Go to https://cloud.rocket.chat
2. Create workspace → get URL
3. Create admin user
4. Get API token (same as local)
5. Update `.env` with cloud URL

```env
ROCKETCHAT_URL=https://org-name.rocket.chat
ROCKETCHAT_ADMIN_TOKEN=cloud-token
ROCKETCHAT_ADMIN_USER_ID=cloud-user-id
```

### Option 2: Self-Hosted (Full Control)

See `README/rocketchat_integration.md` for:
- Kubernetes deployment
- Docker Swarm setup
- Ubuntu/CentOS installation
- AWS/Azure deployment

## Key Features Now Available

| Feature | What It Does |
|---------|------------|
| **DMs** | Send direct messages between users |
| **Group Chats** | Create groups and chat together |
| **Team Channels** | Organized by team (general, crew, cast) |
| **Support DM** | Special support channel for tickets |
| **Unread Counts** | See how many unread messages |
| **Message History** | All messages backed up in Rocket.Chat |
| **User Auto-Creation** | Users created automatically on first message |
| **Real-Time Updates** | SSE streaming for live inbox |
| **Admin Console** | Manage users/channels in Rocket.Chat UI |

## Backward Compatibility

- **Old JSON files**: Not migrated automatically
- **Existing messages**: Lost (Rocket.Chat is fresh start)
- **User credentials**: Not synced to Rocket.Chat
- **Frontend**: Same UI, seamless switch

To migrate old messages:

```bash
python3 << 'EOF'
import json
from rocketchat_client import get_rocketchat_client

with open('chat_messages.json') as f:
    old_msgs = json.load(f)['messages']

rc = get_rocketchat_client()
for msg in old_msgs:
    room_id = rc.get_or_create_channel(msg.get('team', 'general'))
    rc.send_message(room_id, f"[Migrated] {msg['message']}")
    print(f"Migrated: {msg['from_name']} - {msg['message'][:30]}...")

print(f"✓ Migrated {len(old_msgs)} messages")
EOF
```

## What's the Same

Users won't notice the change because:
- 📱 **UI unchanged**: Same Telegram-style inbox/chat
- 💬 **Messages work**: Same send/receive flow
- 👥 **Users same**: ShowWise users map to Rocket.Chat automatically
- 🔄 **Real-time**: Still have SSE streaming for live updates

## Troubleshooting

### "Rocket.Chat offline" in logs

**Check:**
```bash
curl http://localhost:3000/api/info
# Should see Rocket.Chat version info
```

**Fix:**
1. Start Rocket.Chat: `docker-compose up rocketchat`
2. Check `.env` `ROCKETCHAT_URL`
3. Check credentials/token valid

### "User already exists"

Rocket.Chat prevents duplicate usernames:
- Each user must have unique username
- Email can be shared
- Solution: Use different username or delete old user in Rocket.Chat

### SSE not updating

Real-time updates are optional:
- Messages still load on refresh
- Webhook support coming later
- Fallback: Frontend polls `/api/chat/inbox`

### Messages not appearing

1. Check user exists: Rocket.Chat **Administration > Users**
2. Check room created: Rocket.Chat **Channels**
3. Check permissions: User in correct channel/group
4. View browser console for errors

## Next Steps

1. ✅ **Test locally** with Docker setup above
2. 📚 **Read full docs**: `README/rocketchat_integration.md`
3. 🚀 **Deploy to production**: Cloud or self-hosted
4. 👥 **Invite team**: Users will auto-create in Rocket.Chat
5. 🎉 **Enable webhooks** (optional): Real-time notifications

## Support

- 📖 **Full Documentation**: See `README/rocketchat_integration.md`
- 🐛 **Issues**: Email support or create GitHub issue
- 💬 **Community**: Rocket.Chat has active community forums
- 📞 **Enterprise**: Contact Rocket.Chat for business support

---

**Congratulations!** 🎉 You now have enterprise-grade messaging in ShowWise.
