# BETA TESTING SETUP GUIDE

## Quick Start: Zero-Setup Beta Testing

The beta configuration lets you test ShowWise in a staging/UAT environment **without any database servers**. Everything uses file-based SQLite.

### 1. Quick Test Run (30 seconds)

```bash
# Start in beta mode
FLASK_ENV=beta python app.py
```

That's it! ShowWise will:
- Create `beta_crew.db` (main application data)
- Create `beta_security.db` (security system data)
- Automatically initialize both databases
- Be ready for testing at `http://localhost:5001`

### 2. Access Security Dashboard

Once running, you can access the security features:
- **Dashboard:** `http://localhost:5001/security/dashboard`
- **Quarantine:** `http://localhost:5001/security/quarantine`
- **Blacklist:** `http://localhost:5001/security/blacklist`
- **Events:** `http://localhost:5001/security/events`

(Requires admin login)

## Configuration Options

### Default Beta Setup (Recommended)

```bash
FLASK_ENV=beta python app.py
```

Uses:
- `sqlite:///beta_crew.db` (main data)
- `sqlite:///beta_security.db` (security data)
- No secure cookies (easier for testing)
- Creates separate database files from development

Benefits:
- ✅ No database server needed
- ✅ Separate from development data
- ✅ Easy to reset (just delete `.db` files)
- ✅ Perfect for staging/UAT

### Advanced: PostgreSQL for Beta

If you want to test with PostgreSQL without going to production:

```bash
FLASK_ENV=beta \
  DATABASE_URL=postgresql://user:pass@localhost:5432/beta_showwise \
  SECURITY_DATABASE_URL=postgresql://user:pass@localhost:5432/beta_security \
  python app.py
```

## Deployment Scenarios

### Scenario 1: Local UAT (Laptop/Desktop)
```bash
FLASK_ENV=beta python app.py
```
- Zero setup
- Perfect for QA testing
- Single machine

### Scenario 2: Staging Server
```bash
# Option A: File-based (simplest)
FLASK_ENV=beta \
  SECRET_KEY=your-staging-secret \
  python app.py

# Option B: PostgreSQL (if you prefer)
FLASK_ENV=beta \
  DATABASE_URL=postgresql://... \
  SECURITY_DATABASE_URL=postgresql://... \
  SECRET_KEY=your-staging-secret \
  python app.py
```

### Scenario 3: Docker Staging
```dockerfile
FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
ENV FLASK_ENV=beta
CMD ["python", "app.py"]
```

Then run:
```bash
docker run -e FLASK_ENV=beta -p 5001:5001 showwise:beta
```

## Security Testing

### Test BurpSuite Blocking

With BurpSuite running locally on port 8080:

```bash
# This will be blocked immediately (403 Forbidden)
curl -x 127.0.0.1:8080 http://localhost:5001/

# In dashboard, you'll see:
# - IP marked as quarantined (suspicious activity)
# - Threat flags: "BurpSuite Scanner Detected"
# - Request logged in security log
```

### Test SQL Injection Detection

```bash
# This will be detected and quarantined
curl "http://localhost:5001/?id=1' OR '1'='1"

# In dashboard, security event shows:
# - Threat: "SQL Injection Detected"
# - Can be reviewed/blacklisted/approved
```

## Data Management

### Reset Beta Databases

```bash
# Remove beta database files
rm beta_crew.db beta_security.db

# Next run will create fresh databases
FLASK_ENV=beta python app.py
```

### Backup Beta Data

```bash
# Copy databases before major testing
cp beta_crew.db beta_crew.db.backup
cp beta_security.db beta_security.db.backup

# Restore if needed
cp beta_crew.db.backup beta_crew.db
cp beta_security.db.backup beta_security.db
```

### Inspect Beta Databases

```bash
# View security events in beta
sqlite3 beta_security.db "SELECT * FROM security_event LIMIT 10;"

# View blacklisted IPs in beta
sqlite3 beta_security.db "SELECT * FROM ip_blacklist;"

# View quarantine queue
sqlite3 beta_security.db "SELECT * FROM ip_quarantine WHERE status='pending';"
```

## Migration to Production

Once you've validated everything in beta, upgrading to production is straightforward:

1. **Export Beta Data** (optional):
   ```bash
   # Backup your beta databases
   cp beta_crew.db beta_crew.db.final_backup
   cp beta_security.db beta_security.db.final_backup
   ```

2. **Set Production Databases**:
   ```bash
   # Create PostgreSQL databases and get their URLs
   # Then set environment:
   export FLASK_ENV=production
   export DATABASE_URL=postgresql://user:pass@prod-db:5432/showwise
   export SECURITY_DATABASE_URL=postgresql://user:pass@prod-security-db:5432/showwise-security
   ```

3. **Run Migrations** (if schema changed):
   ```bash
   # If you have migration scripts
   python Migration_scripts/migrate_master.py
   ```

4. **Deploy**:
   ```bash
   FLASK_ENV=production python app.py
   ```

## Troubleshooting

### "sqlite3.DatabaseError: database disk image is malformed"

Delete the beta databases and start fresh:
```bash
rm beta_crew.db beta_security.db
FLASK_ENV=beta python app.py
```

### Security dashboard shows "no data"

1. Check you're logged in as admin
2. Verify beta setup is running
3. Try generating test threat:
   ```bash
   curl "http://localhost:5001/?id=1' OR '1'='1"
   ```

### Beta databases not being created

```bash
# Check FLASK_ENV is set correctly
echo $FLASK_ENV  # Should print: beta

# Check write permissions
ls -la | grep beta_crew  # Should exist after first run

# Start with verbose output
FLASK_ENV=beta python app.py --debug
```

## Configuration File Reference

See `.env.example` for complete environment variable documentation.

Key variables for beta:
- `FLASK_ENV=beta` - Enables beta configuration
- `DATABASE_URL` - Override beta_crew.db path (optional)
- `SECURITY_DATABASE_URL` - Override beta_security.db path (optional)
- `SECRET_KEY` - Set for security (optional, has dev default)
- `SHOWWISE_INSTANCE_NAME` - Identify this instance in multi-instance setups (optional)

## Next Steps

- ✅ Test in beta with file-based SQLite
- ✅ Validate security detection (BurpSuite, SQLi, XSS)
- ✅ Test with multiple instances (point SHOWWISE_INSTANCE_NAME to different names)
- ➡️ When ready, migrate to production PostgreSQL
