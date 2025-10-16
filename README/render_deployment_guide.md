# Deploying to Render

Complete guide to deploy your Production Crew Management System to Render for free hosting.

## Prerequisites

1. GitHub account (to host your code)
2. Render account (render.com)
3. Git installed on your computer

## Step 1: Prepare Your Code for Render

### Create a `render.yaml` file in your project root:

```yaml
services:
  - type: web
    name: production-crew
    env: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn -w 1 -b 0.0.0.0:$PORT prod_crew_app:app
    envVars:
      - key: SECRET_KEY
        value: your-secret-key-change-this-to-something-random
      - key: MAIL_SERVER
        value: smtp.gmail.com
      - key: MAIL_PORT
        value: 587
      - key: MAIL_USERNAME
        generateValue: false
      - key: MAIL_PASSWORD
        generateValue: false
```

### Create a `Procfile` in your project root:

```
web: gunicorn -w 1 -b 0.0.0.0:$PORT prod_crew_app:app
```

### Update `requirements.txt` to include gunicorn:

```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-Mail==0.9.1
Werkzeug==3.0.1
python-dotenv==1.0.0
requests==2.31.0
gunicorn==21.2.0
```

### Update `prod_crew_app.py` for production:

At the bottom, change:
```python
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
```

To:
```python
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
```

## Step 2: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/production-crew.git
git branch -M main
git push -u origin main
```

## Step 3: Create Render Service

1. Go to [render.com](https://render.com)
2. Sign up / Login
3. Click **New +** → **Web Service**
4. Connect your GitHub account
5. Select the `production-crew` repository
6. Fill in:
   - **Name**: `production-crew`
   - **Environment**: Python
   - **Region**: Choose closest to you
   - **Branch**: main
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -w 1 -b 0.0.0.0:$PORT prod_crew_app:app`
   - **Plan**: Free

## Step 4: Configure Environment Variables

1. In Render dashboard, go to your service
2. Click **Environment**
3. Add these variables:

```
SECRET_KEY: [Generate a random string - use https://randomkeygen.com/]
MAIL_SERVER: smtp.gmail.com
MAIL_PORT: 587
MAIL_USERNAME: your-email@gmail.com
MAIL_PASSWORD: your-app-password
MAIL_DEFAULT_SENDER: your-email@gmail.com
```

## Step 5: Deploy

1. Click **Create Web Service**
2. Render will automatically deploy
3. You'll get a URL like: `https://production-crew.onrender.com`

## Important Notes for Render

### Database Persistence

**⚠️ WARNING**: Render's free tier has **ephemeral storage**, meaning your database file will be deleted when the service restarts!

**Solutions:**

#### Option 1: Use a Real Database (Recommended)
Change `SQLALCHEMY_DATABASE_URI` in `prod_crew_app.py`:

```python
# Instead of SQLite:
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///production_crew.db'

# Use PostgreSQL (free tier available):
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
```

Then:
1. Create a PostgreSQL database on Render
2. Add `DATABASE_URL` to environment variables
3. Add to requirements.txt: `psycopg2-binary==2.9.9`

#### Option 2: Regular Backups
1. Regularly download database backups from Admin panel
2. Store them securely
3. Use the Admin panel to restore if needed

### Camera Barcode Scanning

**Important**: Camera scanning requires HTTPS (which Render provides automatically).

- ✅ Works on Render (HTTPS enabled by default)
- ✅ Camera permissions work on mobile and desktop
- ✅ Falls back to manual entry if camera unavailable

### Email Notifications

Email works on Render if configured properly:

1. **Gmail**: Use App Passwords (not regular password)
   - Enable 2FA on your Google account
   - Generate an App Password
   - Use that in `MAIL_PASSWORD`

2. **Alternative**: Use SendGrid, Mailgun, etc.

### File Uploads (Stage Plans)

Files uploaded are stored in `/uploads` folder, which will be deleted on redeploy.

**Solution**: Use Render's persistent disk for uploads:

1. In Render dashboard, add a Disk
2. Mount at `/var/data`
3. Update `app.config['UPLOAD_FOLDER'] = '/var/data/uploads'`

## Troubleshooting

### 502 Bad Gateway Error
- Check logs: `render.com → your service → Logs`
- Common cause: Missing dependencies
- Solution: Verify `requirements.txt` is complete

### Database Errors After Restart
- This is expected with free tier SQLite
- Use PostgreSQL database instead

### Camera Not Working
- Verify you're accessing via HTTPS (not HTTP)
- Check browser permissions
- Works on Render because it's HTTPS

### Email Not Sending
- Check MAIL_USERNAME and MAIL_PASSWORD
- For Gmail, use App Password (not regular password)
- Enable 2FA first

## Cost

- **Free tier**: 0.5 GB RAM, limited compute
- **Upgraded**: Starting at $7/month
- Sufficient for small production crews

## Upgrading Storage

For larger deployments:

1. Add PostgreSQL: ~$15/month
2. Add persistent disk: ~$10/month
3. Upgrade compute: ~$7+/month

Total: ~$32/month for reliable production use

## Next Steps

1. Visit your deployed app: `https://production-crew.onrender.com`
2. Login with admin/admin123
3. Change the password immediately
4. Start adding your equipment and events!

## Monitoring

Monitor your Render service:
- **Logs**: Check for errors
- **Metrics**: CPU, Memory usage
- **Deployments**: Track update history

## Auto-Deploy on GitHub Push

Render automatically redeploys when you push to GitHub. To disable:
1. Go to service settings
2. Disable auto-deploy in environment settings