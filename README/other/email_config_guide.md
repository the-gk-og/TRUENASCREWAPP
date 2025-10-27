# Email Notification Setup Guide

Email notifications are **optional**. The app will work fine without them, but if you want to send notifications when crew members are assigned to events, follow these steps.

## Setting Up Email (Gmail Example)

### 1. Create a Gmail Account or Use Existing One

Use a dedicated email account for the system (not your personal email).

### 2. Enable App Password (Gmail)

1. Go to your Google Account settings
2. Navigate to Security
3. Enable 2-Factor Authentication if not already enabled
4. Go to "App passwords"
5. Generate an app password for "Mail"
6. Copy the 16-character password

### 3. Set Environment Variables

Create a file named `.env` in the same folder as `app.py`:

```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-16-char-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
```

### 4. Install python-dotenv

Already included in requirements.txt, but make sure it's installed:

```bash
pip install python-dotenv
```

### 5. Load Environment Variables

Add this to the top of your `app.py` (after imports):

```python
from dotenv import load_dotenv
load_dotenv()
```

## Alternative: Set Environment Variables Directly

### On Linux/Mac:
```bash
export MAIL_SERVER=smtp.gmail.com
export MAIL_PORT=587
export MAIL_USERNAME=your-email@gmail.com
export MAIL_PASSWORD=your-app-password
export MAIL_DEFAULT_SENDER=your-email@gmail.com
```

### On Windows (Command Prompt):
```cmd
set MAIL_SERVER=smtp.gmail.com
set MAIL_PORT=587
set MAIL_USERNAME=your-email@gmail.com
set MAIL_PASSWORD=your-app-password
set MAIL_DEFAULT_SENDER=your-email@gmail.com
```

### On Windows (PowerShell):
```powershell
$env:MAIL_SERVER="smtp.gmail.com"
$env:MAIL_PORT="587"
$env:MAIL_USERNAME="your-email@gmail.com"
$env:MAIL_PASSWORD="your-app-password"
$env:MAIL_DEFAULT_SENDER="your-email@gmail.com"
```

## Using Other Email Services

### Outlook/Hotmail:
```
MAIL_SERVER=smtp.office365.com
MAIL_PORT=587
```

### Yahoo Mail:
```
MAIL_SERVER=smtp.mail.yahoo.com
MAIL_PORT=587
```

### Custom SMTP Server:
Replace with your server's settings.

## How It Works

1. When you add users, include their email address
2. When you assign a crew member to an event, if they have an email, they'll automatically receive a notification
3. The notification includes:
   - Event name
   - Date and time
   - Location
   - Their assigned role

## Testing Email

After setup, try:
1. Add a user with your email address
2. Create an event
3. Assign yourself to the event
4. Check your email for the notification

## Troubleshooting

**No emails being sent?**
- Check that environment variables are set correctly
- Verify the email password (use App Password for Gmail, not your regular password)
- Check spam/junk folder
- Look at the Flask console for error messages

**"535 Authentication Failed" error:**
- You're using the wrong password. For Gmail, use an App Password, not your regular password
- Make sure 2-Factor Authentication is enabled on Gmail

**App works without email?**
- Yes! Email is completely optional. The app will work fine without it.
- If email credentials aren't configured, the app simply won't send notifications

## Disabling Email Notifications

To disable email completely, just don't set the environment variables. The app will detect that email isn't configured and skip sending notifications.