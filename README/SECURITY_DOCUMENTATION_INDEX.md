# SECURITY DOCUMENTATION INDEX

Complete guide to ShowWise's enterprise-grade security system with IP blacklisting, threat detection, quarantine dashboard, and multi-instance support.

## Quick Navigation

### 🚀 **New to Security? Start Here**

1. **[SECURITY_QUICK_START.md](SECURITY_QUICK_START.md)** ⭐
   - **Time:** 5 minutes
   - **What:** Get security running immediately  
   - **Includes:** Basic beta setup, test threats, verify dashboard
   - **Best for:** "I want to see it working NOW"

### 🧪 **Testing & Beta Deployment**

2. **[BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md)**
   - **Time:** 15-30 minutes
   - **What:** In-depth beta testing configuration
   - **Includes:** File-based SQLite setup, security testing, data management, troubleshooting
   - **Best for:** "I want to thoroughly test in staging"

3. **[BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md)**
   - **Time:** 1-2 hours (deployment)
   - **What:** Step-by-step migration from SQLite to production PostgreSQL
   - **Includes:** Database setup, data migration, multi-instance configuration, deployment options
   - **Best for:** "I'm ready to go live to production"

### 📚 **Complete Reference**

4. **[SECURITY_SYSTEM.md](SECURITY_SYSTEM.md)** (if exists)
   - **What:** Comprehensive system documentation
   - **Includes:** Architecture, threat patterns, API details
   - **Best for:** "I need to understand everything"

5. **[SECURITY_DATABASE_SETUP.md](SECURITY_DATABASE_SETUP.md)** (if exists)
   - **What:** Database configuration for all scenarios
   - **Includes:** Multi-instance setups, backup/restore, query examples
   - **Best for:** "I'm setting up multi-instance deployment"

---

## Deployment Scenarios

### Scenario 1: Local Development (5 seconds)

**Goal:** Test on notebook

**Commands:**
```bash
python app.py
# Uses development config with SQLite
```

**Database:** `production_crew.db` + `security.db`

**Next:** See [SECURITY_QUICK_START.md](SECURITY_QUICK_START.md)

---

### Scenario 2: Beta Testing (5 minutes)

**Goal:** Validate in staging environment before production

**Commands:**
```bash
FLASK_ENV=beta python app.py
```

**Database:** `beta_crew.db` + `beta_security.db` (separate from dev)

**Features:**
- ✅ File-based SQLite (no database server needed)
- ✅ Separate database from development
- ✅ Easy to reset (`rm *.db && restart`)
- ✅ Perfect for UAT and QA testing
- ✅ Can be deployed to staging servers as-is

**Next:** See [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md)

---

### Scenario 3: Production Single Instance (1-2 hours)

**Goal:** Deploy to production with fully isolated security database

**Architecture:**
```
Main DB: PostgreSQL (showwise_production)
Security DB: PostgreSQL (showwise_security)
Instance: single-office or multiple-offices-separate
```

**Environment:**
```bash
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@db.example.com:5432/showwise_prod
SECURITY_DATABASE_URL=postgresql://user:pass@secure-db.example.com:5432/showwise_security
```

**Benefits:**
- ✅ Centralized threat monitoring
- ✅ Scalable for unlimited requests/IPs
- ✅ Backed by PostgreSQL
- ✅ Supports backups and replication

**Next:** See [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md)

---

### Scenario 4: Production Multi-Instance (1-2 hours setup + deployment)

**Goal:** Deploy multiple offices with central security monitoring

**Architecture:**
```
NYC Office:
  Main DB: PostgreSQL (showwise_nyc)
  Security DB: Shared PostgreSQL (showwise_security) ← ALL point here
  Instance Name: nyc-office

LA Office:
  Main DB: PostgreSQL (showwise_la)  
  Security DB: Shared PostgreSQL (showwise_security) ← SAME!
  Instance Name: la-office

London Office:
  Main DB: PostgreSQL (showwise_london)
  Security DB: Shared PostgreSQL (showwise_security) ← SAME!
  Instance Name: london-office
```

**Environment (per instance):**
```bash
# NYC Instance
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@nyc-db:5432/showwise_nyc
SECURITY_DATABASE_URL=postgresql://user:pass@central-security:5432/showwise_security
SHOWWISE_INSTANCE_NAME=nyc-office

# LA Instance  
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@la-db:5432/showwise_la
SECURITY_DATABASE_URL=postgresql://user:pass@central-security:5432/showwise_security
SHOWWISE_INSTANCE_NAME=la-office
```

**Central Security Dashboard Benefits:**
- ✅ Single admin dashboard sees all threats from all offices
- ✅ `app_instance` field shows which office detected threat
- ✅ Coordinated threat response across locations
- ✅ Centralized threat trends analysis
- ✅ Easy to detect coordinated attacks

**Next:** See [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md) section "Multi-Instance Deployment"

---

## Configuration Quick Reference

### FLASK_ENV Variable

| Env | Database | DB URLs | Use Case |
|-----|----------|---------|----------|
| `development` | SQLite | defaults | Local dev, zero setup |
| `beta` | SQLite | beta_*.db | Staging/UAT testing |
| `production` | PostgreSQL | Required | Production deployment |
| `testing` | SQLite `:memory:` | n/a | Unit tests (automated) |

### Environment Variables

**All Environments:**
```bash
FLASK_ENV=beta  # or development, production, testing

# Optional
SECRET_KEY=your-secret-key-here
SESSION_DURATION=1w  # 1w, 1d, 1h, 30m
SHOWWISE_INSTANCE_NAME=office-name  # for multi-instance
```

**Production Only:**
```bash
DATABASE_URL=postgresql://...  # Required in production
SECURITY_DATABASE_URL=postgresql://...  # Required in production
```

**Optional (All):**
```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-password

ORGANIZATION_SLUG=your-org
MAIN_SERVER_URL=https://showwise.example.com
SIGNUP_BASE_URL=https://showwise.example.com

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

DISCORD_BOT_TOKEN=...
DISCORD_WEBHOOK_URL=...
```

See `.env.example` for complete reference.

---

## Security Features Overview

### 🛡️ Threat Detection (Automatic)

| Threat | Detection | Action |
|--------|-----------|--------|
| **BurpSuite & Scanners** | User-Agent pattern matching | Immediate 403 Block |
| **SQL Injection** | UNION SELECT, DROP TABLE, comments | Quarantine |
| **XSS** | JavaScript tags, event handlers | Quarantine |
| **Command Injection** | Pipes, backticks, substitution | Quarantine |
| **Rate Limiting** | 100+ requests/5min from IP | Quarantine |

### 📊 Admin Dashboard

Access via: `/security/dashboard` (requires admin login)

**Pages:**
1. **Dashboard** - Real-time stats and top threats
2. **Quarantine** - Review pending suspicious IPs
3. **Blacklist** - Manage permanently blocked IPs
4. **Events** - Timeline of security incidents
5. **Logs** - Request-level audit trail
6. **Logs by IP** - Per-IP request history

**Admin Actions:**
- ✅ Approve quarantined IP (whitelist)
- ✅ Reject quarantined IP (keep blocked)
- ✅ Manually blacklist IP with expiration
- ✅ Override threat decisions
- ✅ Export logs for analysis

### 🌐 Cloudflare Tunnel Support

✅ Automatic! ShowWise detects Cloudflare tunnels via `CF-Connecting-IP` header.

No configuration needed - works seamlessly.

---

## File Structure

```
ShowWise/
├── .env.example                              # Configuration reference
├── config.py                                 # Configuration (DevelopmentConfig, BetaConfig, ProductionConfig)
├── app.py                                    # Flask app with security middleware
├── models_security.py                        # Security models (separate from main app)
├── routes/
│   └── security.py                           # Admin dashboard endpoints
├── services/
│   └── security_service.py                   # Threat detection engine
├── README/
│   ├── SECURITY_QUICK_START.md               # ⭐ Start here (5 min)
│   ├── SECURITY_SYSTEM.md                    # Full documentation (if exists)
│   ├── BETA_TESTING_SETUP.md                 # Beta configuration guide
│   ├── SECURITY_DATABASE_SETUP.md            # Database setup (if exists)
│   └── BETA_TO_PRODUCTION_MIGRATION.md       # Migration guide
└── templates/
    └── security/                             # Admin dashboard HTML
        ├── dashboard.html
        ├── quarantine_list.html
        ├── quarantine_detail.html
        ├── blacklist.html
        ├── events.html
        ├── logs.html
        └── logs_by_ip.html
```

---

## Decision Tree

**Use this to find the right guide:**

```
Q: "I'm new, how do I get started?"
├─ A: Read SECURITY_QUICK_START.md (5 min)

Q: "I want to test thoroughly before production"
├─ A: Read BETA_TESTING_SETUP.md

Q: "I'm ready for production"
├─ A: Read BETA_TO_PRODUCTION_MIGRATION.md

Q: "I need to deploy multiple offices"
├─ A: Read BETA_TO_PRODUCTION_MIGRATION.md → Multi-Instance section

Q: "I need complete technical details"
├─ A: Read SECURITY_SYSTEM.md

Q: "How do I configure databases?"
├─ A: Read SECURITY_DATABASE_SETUP.md

Q: "How do I set up `.env`?"
├─ A: See .env.example (complete reference)
```

---

## Deployment Timeline

```
Day 1:
└─ 15 min: Read SECURITY_QUICK_START.md and run test
└─ 15 min: Validate threats detected in dashboard

Day 2-3 (Optional Beta/Staging):
└─ 30 min: Deploy with FLASK_ENV=beta to staging
└─ QA tests threats in staging environment
└─ Validate dashboard functionality

Day 4+ (Production Deployment):
└─ 2-4 hours: Follow BETA_TO_PRODUCTION_MIGRATION.md
└─ Set up PostgreSQL databases
└─ Run database migrations
└─ Deploy with FLASK_ENV=production
└─ Monitor security logs continuously
```

---

## Support Matrix

| Scenario | Time | Guide | Database |
|----------|------|-------|----------|
| Local development | 5 sec | QUICK_START | SQLite |
| Quick testing | 5 min | QUICK_START | SQLite |
| Beta/staging | 15-30 min | BETA_TESTING_SETUP | SQLite |
| Production single | 1-2h | BETA_TO_PRODUCTION | PostgreSQL |
| Production multi | 1-2h | BETA_TO_PRODUCTION | PostgreSQL |
| Multi-office central monitoring | 1-2h | BETA_TO_PRODUCTION | PostgreSQL |

---

## Key Concepts

### 1. **Separate Security Database**
- **Why:** Security data isolated from application data - can be shared across multiple ShowWise instances
- **Benefit:** Central security monitoring for multi-office deployments
- **Implementation:** `security_db` instance in app.py, models in `models_security.py`

### 2. **IP Quarantine**
- **What:** Suspicious IPs placed in review queue for admin approval
- **Actions:** Approve (whitelist), Reject (keep blocked), Blacklist (permanent)
- **Result:** Admin makes final call on each threat

### 3. **IP Blacklist**
- **What:** Permanently blocked IPs get 403 Forbidden
- **Expiration:** Optional time-based expiration (e.g., 30 days)
- **Whitelist:** Approved IPs automatically excluded

### 4. **Threat Flags**
- **Multiple:** An IP can have multiple threat types (e.g., "SQL Injection + Rate Limiting")
- **Tracked:** Every threat logged for pattern analysis
- **Dashboard:** Visual breakdown of threat types

### 5. **App Instance Tracking**
- **For Multi-Instance:** Each instance named (e.g., "nyc-office", "la-office")
- **In Logs:** Every threat includes instance name
- **Central Dashboard:** Filters threats by instance

---

## Common Paths

### "I just want to verify it works" (5 min)
```bash
FLASK_ENV=beta python app.py
# Then visit http://localhost:5001/security/dashboard
```
→ Read: [SECURITY_QUICK_START.md](SECURITY_QUICK_START.md)

### "I want to test in staging before production" (30 min)
```bash
# Set up beta on staging server
FLASK_ENV=beta python app.py
```
→ Read: [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md)

### "I'm deploying to production now" (2 hours)
```bash
# Follow migration guide step-by-step
# Switch from SQLite to PostgreSQL
```
→ Read: [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md)

### "I need multiple offices with shared security DB" (2 hours)
```bash
# Deploy multiple instances, all pointing to same SECURITY_DATABASE_URL
# Each with unique SHOWWISE_INSTANCE_NAME
```
→ Read: [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md) → Multi-Instance Deployment section

---

## What's Included

✅ **Core Security:**
- BurpSuite blocking
- SQL injection detection
- XSS detection
- Command injection detection
- Rate limiting
- IP quarantine workflow
- IP blacklist management

✅ **Admin Dashboard:**
- Real-time threat visualization
- Quarantine review queue
- Blacklist management
- Request audit logs
- Per-IP request history
- Export capabilities

✅ **Multi-Instance Support:**
- Separate main databases per instance
- Shared security database
- Instance identification in logs
- Centralized threat monitoring

✅ **Deployment Flexibility:**
- Development (SQLite, zero setup)
- Beta testing (file-based SQLite, separate from dev)
- Production (PostgreSQL, fully scalable)
- Multi-instance (PostgreSQL with instance tracking)

✅ **Cloudflare Support:**
- Automatic CF-Connecting-IP extraction
- Works with Cloudflare tunnels
- No special configuration needed

---

## Next Steps

1. **Right Now:** Read [SECURITY_QUICK_START.md](SECURITY_QUICK_START.md) and run `FLASK_ENV=beta python app.py`
2. **Today:** Generate test threats and verify dashboard
3. **This Week:** Read [BETA_TESTING_SETUP.md](BETA_TESTING_SETUP.md) for advanced options
4. **When Ready:** Follow [BETA_TO_PRODUCTION_MIGRATION.md](BETA_TO_PRODUCTION_MIGRATION.md) for production deployment

---

**Questions?** All answers are in the guides linked above.

**Want the full technical reference?** See [SECURITY_SYSTEM.md](SECURITY_SYSTEM.md) (if available) or [SECURITY_DATABASE_SETUP.md](SECURITY_DATABASE_SETUP.md)
