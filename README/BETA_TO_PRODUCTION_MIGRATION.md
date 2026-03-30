# MIGRATION FROM BETA (SQLite) TO PRODUCTION (PostgreSQL)

## Overview

After validating ShowWise in beta with file-based SQLite, this guide walks you through migrating to production with PostgreSQL databases.

**Timeline:**
- Local Development (SQLite)
- → Beta Testing (SQLite, staging environment)
- → Production (PostgreSQL, shared across instances)

## Pre-Migration Checklist

- [ ] Security system tested in beta (threats detected, dashboard works)
- [ ] Multiple offices/instances names assigned (if multi-instance)
- [ ] PostgreSQL admin access available
- [ ] Production secret key generated
- [ ] Email configuration tested
- [ ] Backup of beta SQLite files created

## Step 1: Prepare PostgreSQL

### Create Production Databases

```bash
# Connect to PostgreSQL
psql -U postgres

# Create main application database
CREATE DATABASE showwise_production;

# Create security database (can be on same or different PostgreSQL server)
CREATE DATABASE showwise_security;

# Create dedicated user (recommended)
CREATE USER showwise_prod WITH PASSWORD 'your-strong-password';

# Grant permissions
GRANT ALL PRIVILEGES ON DATABASE showwise_production TO showwise_prod;
GRANT ALL PRIVILEGES ON DATABASE showwise_security TO showwise_prod;
```

### Get Connection Strings

```
DATABASE_URL=postgresql://showwise_prod:your-strong-password@db.example.com:5432/showwise_production
SECURITY_DATABASE_URL=postgresql://showwise_prod:your-strong-password@secure-db.example.com:5432/showwise_security
```

If using same server:
```
DATABASE_URL=postgresql://showwise_prod:password@localhost:5432/showwise_production
SECURITY_DATABASE_URL=postgresql://showwise_prod:password@localhost:5432/showwise_security
```

## Step 2: Export Beta Data (Optional but Recommended)

**Note:** If starting fresh is acceptable, skip to Step 3.

### Export Users and Core Data

```bash
# Export beta application data to CSV
sqlite3 beta_crew.db << EOF
.mode csv
.output beta_users.csv
SELECT * FROM user;
.output beta_crews.csv
SELECT * FROM crew;
.output beta_shifts.csv
SELECT * FROM shift_members;
EOF
```

### Export Optional: Security Events

```bash
# Export beta security logs for audit/analysis
sqlite3 beta_security.db << EOF
.mode csv
.output beta_security_events.csv
SELECT * FROM security_event;
.output beta_security_logs.csv
SELECT * FROM security_log;
EOF
```

## Step 3: Initialize Production Databases

### Option A: Clean Start (Recommended for First Production Deployment)

```bash
# Set production environment
export FLASK_ENV=production
export DATABASE_URL=postgresql://showwise_prod:password@db.example.com:5432/showwise_production
export SECURITY_DATABASE_URL=postgresql://showwise_prod:password@secure-db.example.com:5432/showwise_security

# Initialize databases (creates all tables)
python app.py
# Press Ctrl+C after seeing "Running on..." message
```

This creates all tables from Flask-SQLAlchemy models.

### Option B: Use Migration Scripts

If you have existing migration scripts:

```bash
export FLASK_ENV=production
export DATABASE_URL=postgresql://...
export SECURITY_DATABASE_URL=postgresql://...

# Run main migration script
python Migration_scripts/migrate_master.py

# If additional migrations exist:
python Migration_scripts/migrate_full_schema.py
```

## Step 4: Restore Beta Data (If Exported)

### Restore Users and Core Data

```bash
# Start Python shell in production environment
export FLASK_ENV=production
export DATABASE_URL=postgresql://...
python

# In Python shell:
from app import app, db
from models import User, Crew, ShiftMember

app.app_context().push()

# Import CSV if you exported it
import csv

with open('beta_users.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        user = User(**row)
        db.session.add(user)
db.session.commit()

# Repeat for other tables as needed
exit()
```

Or use a migration script to load CSV files automatically.

### Skip Security Data

**Recommendation:** Do NOT restore security events from beta:
- Beta threats are from test environment
- Production should start fresh security log
- This prevents false historical alerts

## Step 5: Configure Production Environment

Create production `.env` file:

```bash
# .env.production
FLASK_ENV=production
SECRET_KEY=generate-a-new-strong-secret-key-here

# Databases
DATABASE_URL=postgresql://showwise_prod:password@db.example.com:5432/showwise_production
SECURITY_DATABASE_URL=postgresql://showwise_prod:password@secure-db.example.com:5432/showwise_security

# Organization
ORGANIZATION_SLUG=your-org
MAIN_SERVER_URL=https://showwise.your-domain.com
SIGNUP_BASE_URL=https://showwise.your-domain.com

# Email
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=noreply@showwise.your-domain.com

# Multi-Instance Support
# If deploying 3 offices, each instance points to same SECURITY_DATABASE_URL:
SHOWWISE_INSTANCE_NAME=nyc-office  # Change this on other instances
# OR
SHOWWISE_INSTANCE_NAME=la-office
# OR
SHOWWISE_INSTANCE_NAME=london-office

# OAuth (if using)
GOOGLE_CLIENT_ID=your-prod-google-client-id
GOOGLE_CLIENT_SECRET=your-prod-client-secret
GOOGLE_REDIRECT_URI=https://showwise.your-domain.com/auth/google/callback

# Discord (if using)
DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/...
```

**Security Note:** Never commit `.env.production` to version control.

## Step 6: Verify Production Setup

### Test Connection

```bash
# Before deploying, verify databases connect
export FLASK_ENV=production
export DATABASE_URL=postgresql://...
export SECURITY_DATABASE_URL=postgresql://...

python -c "
from app import app, db
from extensions import security_db
app.app_context().push()
print('✓ Main DB connected:', db.engine.url)
print('✓ Security DB connected:', security_db.engine.url)
"
```

### Check Tables Created

```bash
# PostgreSQL - Main DB
psql $DATABASE_URL -c "\dt"  # Lists all tables

# PostgreSQL - Security DB
psql $SECURITY_DATABASE_URL -c "\dt"  # Should see: ip_blacklist, ip_quarantine, security_event, security_log
```

### Test Security System

```bash
# Start app
FLASK_ENV=production python app.py

# In another terminal, test threat detection
curl "http://localhost:5001/?id=1' OR '1'='1"

# Check security log
psql $SECURITY_DATABASE_URL -c "SELECT * FROM security_log ORDER BY timestamp DESC LIMIT 5;"
```

## Step 7: Deploy to Production

### Option A: Manual Deployment

```bash
# Ensure environment variables are set
export FLASK_ENV=production
export DATABASE_URL=postgresql://...
export SECURITY_DATABASE_URL=postgresql://...
export SECRET_KEY=your-production-secret

# Start application
python app.py

# Or with Gunicorn for production:
gunicorn --bind 0.0.0.0:5001 --workers 4 app:app
```

### Option B: Docker Deployment

```dockerfile
FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

ENV FLASK_ENV=production
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "app:app"]
```

Deploy:
```bash
docker build -t showwise:prod .

docker run \
  -e FLASK_ENV=production \
  -e DATABASE_URL=postgresql://... \
  -e SECURITY_DATABASE_URL=postgresql://... \
  -e SECRET_KEY=... \
  -p 5001:5001 \
  showwise:prod
```

### Option C: Systemd Service

```ini
[Unit]
Description=ShowWise Flask Application
After=network.target postgresql.service

[Service]
Type=notify
User=showwise
WorkingDirectory=/opt/showwise
Environment="FLASK_ENV=production"
Environment="DATABASE_URL=postgresql://..."
Environment="SECURITY_DATABASE_URL=postgresql://..."
Environment="SECRET_KEY=..."
ExecStart=/opt/showwise/venv/bin/python app.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable showwise
sudo systemctl start showwise
```

## Step 8: Multi-Instance Deployment (If Applicable)

If deploying to multiple offices with a shared security database:

### NYC Office
```bash
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@nyc-db:5432/showwise_nyc
SECURITY_DATABASE_URL=postgresql://user:pass@security-db:5432/showwise_security  # SHARED
SHOWWISE_INSTANCE_NAME=nyc-office
python app.py
```

### LA Office
```bash
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@la-db:5432/showwise_la
SECURITY_DATABASE_URL=postgresql://user:pass@security-db:5432/showwise_security  # SAME DB
SHOWWISE_INSTANCE_NAME=la-office
python app.py
```

### London Office
```bash
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@london-db:5432/showwise_london
SECURITY_DATABASE_URL=postgresql://user:pass@security-db:5432/showwise_security  # SAME DB
SHOWWISE_INSTANCE_NAME=london-office
python app.py
```

**Benefits:**
- Each office has its own main database (crew data)
- All offices share security database (centralized threat monitoring)
- Security dashboard sees threats from all offices (`app_instance` field)
- Central admin can review all instances from one security dashboard

## Step 9: Post-Deployment Validation

```bash
# Check logs for errors
tail -f /var/log/showwise/app.log

# Verify instances connected (if multi-instance)
psql $SECURITY_DATABASE_URL -c "
  SELECT DISTINCT app_instance FROM security_log;
"

# Should show: nyc-office, la-office, london-office (if deployed to all 3)

# Check security dashboard
curl https://showwise.your-domain.com/security/dashboard  # Requires login

# Monitor first threats
psql $SECURITY_DATABASE_URL -c "
  SELECT timestamp, ip_address, threat_flags, app_instance 
  FROM security_log 
  ORDER BY timestamp DESC 
  LIMIT 10;
"
```

## Step 10: Rollback Plan

If production deployment has issues:

### Quick Reverting to Beta

```bash
# Stop production
systemctl stop showwise

# Revert to beta with backup
FLASK_ENV=beta python app.py

# Investigate issue, then re-deploy to production
```

### Data Backup Locations

```bash
# Backup PostgreSQL databases after successful production deployment
pg_dump showwise_production > backup_production_$(date +%Y%m%d).sql
pg_dump showwise_security > backup_security_$(date +%Y%m%d).sql

# Store backups safely
mkdir -p /backups/showwise
mv backup_*.sql /backups/showwise/
```

## Monitoring Checklist

After going live to production:

- [ ] Application loads (check HTTPS certificate)
- [ ] Database connectivity verified
- [ ] Admin can log in
- [ ] Security dashboard accessible
- [ ] Threat detection working (test from staging)
- [ ] Email notifications sending (if configured)
- [ ] Backups running daily
- [ ] Error logs monitored
- [ ] Performance acceptable

## Common Issues & Solutions

### "FATAL: Ident authentication failed"

PostgreSQL permission issue:
```bash
# Update pg_hba.conf to use md5 or trust
sudo nano /etc/postgresql/12/main/pg_hba.conf
# Change ident to md5
sudo systemctl restart postgresql
```

### "Connection refused" to PostgreSQL

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check port is correct (default 5432)
netstat -tuln | grep 5432

# Verify DATABASE_URL format
echo $DATABASE_URL
# Should be: postgresql://user:pass@host:5432/dbname
```

### "Separate security DB not connecting"

```bash
# Verify SECURITY_DATABASE_URL is set
echo $SECURITY_DATABASE_URL

# Check it's different from DATABASE_URL
echo $DATABASE_URL
echo $SECURITY_DATABASE_URL

# Manually test connection
psql $SECURITY_DATABASE_URL -c "SELECT 1"
```

### Threats not showing in dashboard after migration

```bash
# Verify security_log table is empty (fresh start intended)
psql $SECURITY_DATABASE_URL -c "SELECT COUNT(*) FROM security_log;"

# Generate a test threat
curl "http://localhost:5001/?id=1' OR '1'='1"

# Check if it was logged
psql $SECURITY_DATABASE_URL -c "SELECT * FROM security_log ORDER BY timestamp DESC LIMIT 1;"
```

## Success Indicators

✅ Production Successfully Deployed When:
- Main application database has all current data
- Security database initialized and empty (fresh start)
- BurpSuite immediately blocked (403)
- SQL injection detected and logged
- Admin dashboard shows threat stats
- Multi-instance setup shows correct app_instance names in security logs
- PostgreSQL databases backing up daily

## Next Steps

After successful production deployment:
1. Continue monitoring security logs
2. Train team on admin dashboard
3. Set up alerts for critical threats
4. Schedule regular security log reviews
5. Plan periodic backups

---

**Questions?** Reference:
- [SECURITY_SYSTEM.md](SECURITY_SYSTEM.md) - Full security system documentation
- [SECURITY_DATABASE_SETUP.md](SECURITY_DATABASE_SETUP.md) - Multi-instance examples
- [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md) - Beta environment guide
