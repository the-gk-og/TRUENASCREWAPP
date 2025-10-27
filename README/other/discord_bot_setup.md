# Discord Bot Setup Guide

Complete guide to set up the Discord bot for Production Crew Management System.

## What the Discord Bot Does

1. **Automatic Event Announcements** - Posts new events to Discord with reaction buttons
2. **React to Join** - Crew members can react with ✋ to add themselves to events
3. **Event Reminders** - Pings crew 1 week before and on day of event
4. **Account Linking** - Links Discord accounts to Production Crew accounts
5. **Real-time Updates** - All changes sync instantly

## Prerequisites

- Discord server (your school's server)
- Administrator access to the Discord server
- Discord Developer Account (free)
- Render hosting deployed (or local development URL)

## Step 1: Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**
3. Enter name: `Production Crew Manager`
4. Click **Create**
5. Go to **Bot** section
6. Click **Add Bot**
7. Under **TOKEN**, click **Copy** to copy your bot token
8. Save this token - you'll need it later!

⚠️ **IMPORTANT**: Keep this token SECRET! Never share it!

## Step 2: Configure Bot Permissions

1. In Developer Portal, go to **OAuth2** → **URL Generator**
2. Select **Scopes**:
   - ✅ bot
   - ✅ applications.commands

3. Select **Permissions**:
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Read Message History
   - ✅ Add Reactions
   - ✅ Read Reactions

4. Copy the generated URL at the bottom
5. Paste in browser to invite bot to your server

## Step 3: Set Up Webhook

A Webhook allows the web app to send messages to Discord:

1. In your Discord server, go to **Server Settings** → **Integrations** → **Webhooks**
2. Click **New Webhook**
3. Name it: `Production Crew`
4. Select the channel where events should post
5. Click **Copy Webhook URL**
6. Save this URL - you'll need it!

Example: `https://discordapp.com/api/webhooks/123456789/abcdefghij`

## Step 4: Set Environment Variables

### On Render:

1. Go to your Render service dashboard
2. Click **Environment**
3. Add these variables:

```
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_WEBHOOK_URL=your_webhook_url_here
DISCORD_BOT_SECRET=create_a_random_secret_string
DISCORD_GUILD_ID=your_server_id_here
```

### On Local Machine (create .env file):

```
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_WEBHOOK_URL=your_webhook_url_here
DISCORD_BOT_SECRET=create_a_random_secret_string
DISCORD_GUILD_ID=your_server_id_here
```

Then add to `prod_crew_app.py` (already in code):
```python
from dotenv import load_dotenv
load_dotenv()
```

## Step 5: Get Your Guild ID (Server ID)

1. Enable Developer Mode in Discord:
   - User Settings → Advanced → Developer Mode → ON
2. Right-click your server name
3. Click **Copy Server ID**
4. Paste as `DISCORD_GUILD_ID`

## Step 6: Link Discord Accounts

Each crew member needs to link their Discord account:

1. Login to Production Crew web app
2. Go to **Discord** in navigation
3. Follow the "How to Link" instructions
4. Use command: `/link-account` in Discord
5. Enter your Production Crew username
6. Account is linked!

## Step 7: Test the Integration

1. **Create a test event:**
   - Calendar → + Add Event
   - Fill in details
   - Click Create

2. **Check Discord:**
   - A message should appear in your channel
   - Shows event details
   - Has ✋ reaction button

3. **Test reaction:**
   - Click ✋ reaction in Discord
   - The bot should add you to the event
   - Check web app - you should be assigned!

## How It Works in Practice

### Event Creation Flow

1. **Admin creates event in web app**
   ↓
2. **Event details sent to Discord**
   ↓
3. **Message posted with reaction buttons**
   ↓
4. **Crew members can react to join**
   ↓
5. **Assignments synced back to web app**
   ↓
6. **Reminders sent 1 week before and on day**

### Crew Member Experience

1. **See new event in Discord:**
   ```
   🎭 New Event: Spring Musical
   📅 May 15, 2024 at 06:00 PM
   📍 School Auditorium
   React with ✋ to add yourself!
   ```

2. **React with ✋**
   ```
   ✅ You're added to the event!
   ```

3. **Get reminders:**
   - 1 week before: "Event happening in 1 week!"
   - Day of event: "Event happening TODAY!"

### Web App Integration

- All Discord joins appear in web app
- Crew members can also add themselves via web app
- Both methods sync perfectly
- Pick lists and stage plans available in both

## Commands for Crew Members

### `/link-account`
- Links your Discord account to web app
- One-time setup
- Required to receive notifications

### `/join-event [event_id]`
- Join an event via command instead of reaction
- Useful if you can't see reactions

### `/my-events`
- Lists all events you're assigned to
- Shows dates and locations

## Troubleshooting

### Bot not posting to Discord

**Problem:** Events created but no Discord message appears

**Solutions:**
- Check DISCORD_WEBHOOK_URL is correct
- Make sure webhook still exists (not deleted)
- Verify bot has Send Messages permission
- Check server logs for errors

### Reactions not working

**Problem:** Click ✋ but nothing happens

**Solutions:**
- Make sure account is linked (use `/link-account`)
- Bot needs Read Reactions permission
- Check bot has role in Discord
- Verify DISCORD_BOT_SECRET matches

### Account linking fails

**Problem:** `/link-account` command doesn't work

**Solutions:**
- Make sure bot is in your server
- Try slash command (/) not regular command
- Check that app is running (Render service live)
- Verify DISCORD_BOT_TOKEN is correct

### Reminders not sending

**Problem:** No pings 1 week before or on day of event

**Solutions:**
- Reminders need DISCORD_WEBHOOK_URL
- Crew must be assigned to events
- Discord must have proper permissions
- Check Render logs for scheduling errors

## Advanced Configuration

### Change Notification Channel

Different channels for different event types:

1. Create multiple webhooks in Discord
2. Set environment variables:
```
DISCORD_WEBHOOK_EVENTS=webhook_url_1
DISCORD_WEBHOOK_REMINDERS=webhook_url_2
```

3. Update code to use appropriate webhook

### Custom Messages

Customize the event message format:

1. Edit `send_discord_message()` function in `prod_crew_app.py`
2. Change embed title, description, color
3. Restart app

### Bot Status/Activity

Show what the bot is doing:

```
🎭 Production Crew Management
🎭 Managing upcoming events
🎭 Type /help for commands
```

## Security Best Practices

1. **Never share bot token** - Keep it secret!
2. **Use environment variables** - Don't hardcode tokens
3. **Limit permissions** - Only give what's needed
4. **Rotate secrets** - Change DISCORD_BOT_SECRET monthly
5. **Monitor bot activity** - Check audit logs regularly
6. **Restrict commands** - Some commands admin-only

## Privacy Considerations

- Discord IDs are stored with accounts
- No other Discord data is collected
- Discord usernames shown in admin panel
- All data encrypted at rest
- GDPR compliant

## Support

### Discord Developer Support
- Documentation: https://discord.com/developers/docs
- Community: Discord Developers server

### Production Crew Support
- Check logs in Render dashboard
- Review environment variables
- Test with simple event first

## Next Steps

1. ✅ Create Discord application
2. ✅ Set up webhook
3. ✅ Add environment variables
4. ✅ Link your account
5. ✅ Create test event
6. ✅ Test reactions
7. ✅ Brief crew on process
8. ✅ Go live!

## Example Setup Time

- Discord app creation: 5 minutes
- Webhook setup: 2 minutes
- Environment variables: 2 minutes
- Account linking: 1 minute per person
- Testing: 5 minutes

**Total: 15 minutes setup + training time**

## Common Questions

### Q: Can we use a personal Discord server?
**A:** Yes! The bot works in any server you have access to.

### Q: What if someone unlinks their account?
**A:** They won't receive notifications, but can still join events via web app.

### Q: Can multiple Discord servers connect to one web app?
**A:** Not currently, but it can be added with multiple webhooks.

### Q: What happens if the bot goes offline?
**A:** Web app still works fine. Reminders may be delayed.

### Q: Can crew edit events in Discord?
**A:** No, only view and join. Editing only in web app.

## Future Enhancements

Potential additions:
- Schedule posts to specific times
- Multiple Discord servers support
- Voice channel integration
- Emoji reactions for roles
- Event reminders in DMs
- Crew member mentions in posts

Start using Discord notifications today! 🎭