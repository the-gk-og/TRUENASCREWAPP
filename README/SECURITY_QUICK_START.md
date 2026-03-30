# SECURITY SYSTEM QUICK START

Get ShowWise security features running in **5 minutes** with file-based testing.

## 1. Start with Beta (90 seconds)

```bash
# Just run this command
FLASK_ENV=beta python app.py
```

What happens:
- ✅ Creates `beta_crew.db` (main data)
- ✅ Creates `beta_security.db` (security data)
- ✅ Initializes all security tables
- ✅ Ready at `http://localhost:5001`

**That's it!** No database server needed.

## 2. Log In & View Dashboard (2 minutes)

1. Open `http://localhost:5001`
2. Sign up or log in with admin account
3. Go to `http://localhost:5001/security/dashboard`

You should see:
- 📊 Security stats (0 events, but system is ready)
- 🔒 Banned IPs count
- ⚠️ Quarantine queue
- 📅 Recent security events

## 3. Test Threat Detection (2 minutes)

### Test 1: SQL Injection Detection

```bash
# In another terminal, trigger SQL injection threat
curl "http://localhost:5001/?id=1' OR '1'='1"

# Check dashboard → Events
# You should see: "SQL Injection Detected"
```

### Test 2: Rate Limiting

```bash
# Hammer an endpoint 100+ times
for i in {1..150}; do curl "http://localhost:5001/" & done

# Check dashboard → Quarantine
# Your IP should be marked as suspicious
```

### Test 3: BurpSuite Blocking (If Using BurpSuite)

```bash
# Set BurpSuite as proxy on port 8080, then:
curl -x 127.0.0.1:8080 http://localhost:5001/

# Result: 403 Forbidden (blocked immediately!)
# Check dashboard → Events: "BurpSuite Scanner Detected"
```

## 4. Check Dashboard Features

After running tests above:

- **Dashboard** (`/security/dashboard`)
  - Real-time threat stats
  - Top suspicious IPs
  - Recent security events

- **Quarantine** (`/security/quarantine`)
  - Pending review queue
  - Click IP to see detailed logs
  - Approve/Reject/Blacklist actions

- **Blacklist** (`/security/blacklist`)
  - Permanently blocked IPs
  - Expiration dates
  - Manual blocking options

- **Events** (`/security/events`)
  - Timeline of all security incidents
  - Threat breakdown
  - Acknowledge/clear events

- **Logs** (`/security/logs`)
  - Request-level detail
  - Filter by threat type
  - Export for analysis

## What's Protected

✅ **BurpSuite & Security Scanners**
- Detects: BurpSuite, OWASP ZAP, SQLMap, Nikto, Acunetix, Metasploit, Nessus
- Action: Blocked immediately (403 Forbidden)

✅ **SQL Injection Attacks**
- Detects: UNION SELECT, DROP TABLE, comments, boolean logic
- Action: Quarantined for review

✅ **XSS Attacks**
- Detects: JavaScript tags, event handlers, iframe injection
- Action: Quarantined for review

✅ **Command Injection**
- Detects: Shell pipes, command substitution, chaining
- Action: Quarantined for review

✅ **Rate Limiting**
- Detects: 100+ requests in 5 minutes from single IP
- Action: Quarantined for review

## Dashboard Admin Features

Once a threat is detected:

1. **Review** → See threat details, request logs
2. **Approve** → Mark as legitimate (won't be blocked again)
3. **Reject** → Mark as malicious (adds to quarantine)
4. **Blacklist** → Permanently block IP (with optional expiration)
5. **Acknowledge** → Clear event notification

## Next: Deploy to Production

When you're satisfied with beta testing:

See [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md) for step-by-step deployment to production with PostgreSQL.

## Multi-Instance Testing

Test central security monitoring with multiple instances:

```bash
# Terminal 1: NYC Office
FLASK_ENV=beta SHOWWISE_INSTANCE_NAME=nyc-office python app.py

# Terminal 2: LA Office (different port)
FLASK_ENV=beta SHOWWISE_INSTANCE_NAME=la-office python app.py -p 5002
```

In production, all instances point to same `SECURITY_DATABASE_URL`, so central security dashboard sees threats from all offices with instance name tracked.

## File Structure

Beta configuration creates:

```
ShowWise/
├── beta_crew.db           # Main application data (users, crews, shifts)
├── beta_security.db       # Security database (threats, quarantine, logs)
├── routes/
│   └── security.py        # Admin dashboard endpoints
├── services/
│   ├── security_service.py # Threat detection engine
│   └── ...
├── models_security.py     # Security models (Threat, Quarantine, etc)
├── config.py              # Configuration (FLASK_ENV=beta)
└── app.py                 # Flask app with security middleware
```

## Configuration Options

### Quick Commands

```bash
# Development (default, same as before)
python app.py

# Beta (file-based, separate DBs)
FLASK_ENV=beta python app.py

# Production (requires PostgreSQL URLs)
FLASK_ENV=production DATABASE_URL=postgresql://... python app.py
```

### Environment Variables

See `.env.example` for complete reference:

```bash
# Set Flask environment
FLASK_ENV=beta

# Optional: Override database paths
DATABASE_URL=sqlite:///my_app.db
SECURITY_DATABASE_URL=sqlite:///my_security.db

# Optional: Name this instance
SHOWWISE_INSTANCE_NAME=nyc-office

# Optional: Set secret for sessions
SECRET_KEY=your-secret-here
```

## Troubleshooting

**Q: "Module not found: models_security"**
- A: Make sure you're using the latest code with `models_security.py` in the root directory

**Q: "Security dashboard shows 'No data'"**
- A: Generate a test threat first (see Test 1-3 above)

**Q: "Database locked error"**
- A: SQLite is single-writer. Close other processes and try again:
  ```bash
  rm beta_crew.db beta_security.db
  FLASK_ENV=beta python app.py  # Fresh start
  ```

**Q: "How do I reset everything?"**
- A: Delete the `.db` files and restart:
  ```bash
  rm beta_crew.db beta_security.db
  FLASK_ENV=beta python app.py
  ```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ Flask Application (app.py)                              │
│                                                         │
│  ┌────────────────────────────────────────────────┐    │
│  │ Security Middleware (before_request hook)      │    │
│  ├────────────────────────────────────────────────┤    │
│  │ 1. Extract IP (Cloudflare or direct)           │    │
│  │ 2. Check if IP blacklisted → Block (403)       │    │
│  │ 3. Scan request for threats (SQLi, XSS, etc)   │    │
│  │ 4. If threat detected → Quarantine IP          │    │
│  │ 5. Log all suspicious requests                 │    │
│  └────────────────────────────────────────────────┘    │
│          ↓                                ↓             │
│   Process OK                      Threat Detected       │
│   Continue request                Log & Quarantine      │
└─────────────────────────────────────────────────────────┘
        ↓
┌───────────────────────────────────────────┐
│ Admin Dashboard (/security/*)              │
│ - View quarantine queue                    │
│ - Review threats & logs                    │
│ - Approve/Reject/Blacklist IPs             │
│ - Analytics & reporting                    │
└───────────────────────────────────────────┘
        ↓
┌───────────────────────────────────────────┐
│ Security Database (beta_security.db)       │
│ - security_event (incidents)               │
│ - security_log (request detail)            │
│ - ip_quarantine (pending review)           │
│ - ip_blacklist (permanent blocks)          │
└───────────────────────────────────────────┘
```

## Key Features at a Glance

| Feature | Status | Details |
|---------|--------|---------|
| BurpSuite Blocking | ✅ | Immediate 403 response |
| SQL Injection Detection | ✅ | UNION SELECT, DROP TABLE, comments |
| XSS Detection | ✅ | JavaScript, event handlers, iframes |
| Command Injection | ✅ | Pipes, backticks, substitution |
| Rate Limiting | ✅ | 100+ requests in 5 minutes |
| IP Quarantine | ✅ | Pending review queue |
| IP Blacklist | ✅ | Permanent blocking with expiration |
| Admin Dashboard | ✅ | 7 pages of management interfaces |
| Multi-Instance | ✅ | Shared security DB with instance tracking |
| Cloudflare Support | ✅ | Automatic CF-Connecting-IP extraction |

## Production Deployment Path

```
Local Dev          Beta Testing          Production
(FLASK_ENV=dev)    (FLASK_ENV=beta)      (FLASK_ENV=prod)
     ↓                   ↓                     ↓
sqlite:///        sqlite:///beta_      postgresql://
production_crew   crew.db              prod-db
                                       
                                       (shared security.db)
                                       postgresql://
                                       security-db
```

---

**Next Steps:**
1. ✅ Run `FLASK_ENV=beta python app.py`
2. ✅ Test threats in dashboard
3. ✅ Read [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md) for advanced config
4. ✅ When ready, see [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md)

**Questions?** Check the full documentation:
- [SECURITY_SYSTEM.md](SECURITY_SYSTEM.md) - Complete system overview
- [SECURITY_DATABASE_SETUP.md](SECURITY_DATABASE_SETUP.md) - Multi-instance setup
- [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md) - Advanced beta configuration
