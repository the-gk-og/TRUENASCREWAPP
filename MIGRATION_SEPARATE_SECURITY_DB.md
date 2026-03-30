"""
MIGRATION GUIDE: Main DB + Separate Security DB
================================================

Summary of Changes:
This update separates the security database from the main application database,
allowing multiple ShowWise instances to share one centralized security system.
"""

# ============================================================================
# WHAT CHANGED
# ============================================================================

### NEW FILES CREATED:
  ✓ models_security.py
    - All security models moved here
    - Uses separate security_db
    - Models: IPBlacklist, IPQuarantine, SecurityLog, SecurityEvent

  ✓ SECURITY_DATABASE_SETUP.md
    - Complete multi-instance setup guide
    - Configuration examples
    - Troubleshooting

### MODIFIED FILES:

  ✓ extensions.py
    - Added: security_db = SQLAlchemy()
    - Separate from main db instance

  ✓ config.py
    - Added: SECURITY_DATABASE_URI env var
    - Defaults to sqlite:///security.db

  ✓ models.py
    - REMOVED: Security models (moved to models_security.py)
    - User, Event, Shift etc still here

  ✓ app.py
    - Updated imports: from extensions import db, security_db
    - Initialize security_db with separate URI
    - Configure SQLALCHEMY_BINDS for security database

  ✓ services/security_service.py
    - Updated imports: from models_security import ...
    - All db references changed to security_db
    - Added app_instance tracking (for multi-instance logging)
    - Removed user_id references (security is app-agnostic)

  ✓ routes/security.py
    - Updated imports: from models_security import ...
    - All db.session changed to security_db.session
    - Added sqlalchemy.func import


# ============================================================================
# MIGRATION STEPS
# ============================================================================

### STEP 1: Pull the Latest Code

$ git pull origin main


### STEP 2: Update .env File

Add the security database URL:

.env:
  DATABASE_URL=sqlite:///production_crew.db
  SECURITY_DATABASE_URL=sqlite:///security.db  # ← NEW
  SHOWWISE_INSTANCE_NAME=instance-1  # ← OPTIONAL


For PostgreSQL:
  DATABASE_URL=postgresql://user:pass@host/showwise_main
  SECURITY_DATABASE_URL=postgresql://sec_user:sec_pass@sec_host/showwise_security


### STEP 3: Copy Existing Security Data (if migrating)

IF you already have security tables in your main database:

$ python
>>> from app import create_app
>>> from models import IPBlacklist as OldBlacklist  # OLD location
>>> from models_security import IPBlacklist as NewBlacklist  # NEW location
>>> app = create_app()
>>> with app.app_context():
    ...
    old_records = OldBlacklist.query.all()
    for record in old_records:
        new_rec = NewBlacklist(
            ip_address=record.ip_address,
            reason=record.reason,
            blocked_by=record.blocked_by,
            created_at=record.created_at,
            expires_at=record.expires_at,
            is_active=record.is_active
        )
        security_db.session.add(new_rec)
    security_db.session.commit()

Repeat for: IPQuarantine, SecurityLog, SecurityEvent

### STEP 4: REMOVE OLD SECURITY TABLES from main DB

$ python
>>> from app import create_app
>>> from extensions import db
>>> app = create_app()
>>> with app.app_context():
    db.session.execute('DROP TABLE IF EXISTS ip_blacklist')
    db.session.execute('DROP TABLE IF EXISTS ip_quarantine')
    db.session.execute('DROP TABLE IF EXISTS security_log')
    db.session.execute('DROP TABLE IF EXISTS security_event')
    db.session.commit()

OR manually in SQL:

DROP TABLE ip_blacklist;
DROP TABLE ip_quarantine;
DROP TABLE security_log;
DROP TABLE security_event;


### STEP 5: Restart Application

$ python app.py

You should see:
  ✓ Main database initialized
  ✓ Security database initialized
  ✓ Both databases ready


### STEP 6: Verify

Check that both databases have tables:

Main DB (production_crew.db):
  - user
  - event
  - shift
  - equipment
  - etc. (no security tables!)

Security DB (security.db):
  - ip_blacklist
  - ip_quarantine
  - security_log
  - security_event


# ============================================================================
# VALIDATION CHECKLIST
# ============================================================================

After migration, verify:

[ ] .env includes SECURITY_DATABASE_URL
[ ] app.py initializes security_db
[ ] models_security.py exists with 4 models
[ ] models.py does NOT have security models
[ ] Flask app starts without errors
[ ] Security dashboard loads: /security/dashboard
[ ] Security logs appear when accessing site
[ ] Can approve/reject IPs in quarantine queue
[ ] BurpSuite is still blocked immediately
[ ] Multi-instance instances read from same security DB


# ============================================================================
# ZERO DOWNTIME MIGRATION (for production)
# ============================================================================

If you need zero downtime:

1. Keep old setup running
2. Set up new security database
3. Deploy app with new code
4. Migrate data gradually (see STEP 3)
5. Monitor both databases
6. Switch over at low-traffic time
7. Remove old tables after verification


# ============================================================================
# MULTI-INSTANCE SETUP (Advanced)
# ============================================================================

To set up 3 instances sharing one security DB:

INSTANCE 1 (nyc):
  - DATABASE_URL=postgresql://ny_user:pass@ny-host/showwise_ny
  - SECURITY_DATABASE_URL=postgresql://sec_user:pass@sec-host/showwise_security

INSTANCE 2 (la):
  - DATABASE_URL=postgresql://la_user:pass@la-host/showwise_la
  - SECURITY_DATABASE_URL=postgresql://sec_user:pass@sec-host/showwise_security

INSTANCE 3 (london):
  - DATABASE_URL=postgresql://uk_user:pass@uk-host/showwise_uk
  - SECURITY_DATABASE_URL=postgresql://sec_user:pass@sec-host/showwise_security

Result: All instances see threats from all locations!

See SECURITY_DATABASE_SETUP.md for detailed examples.


# ============================================================================
# STRUCTURE DIAGRAM
# ============================================================================

Before:
┌─────────────────────────┐
│   Main Database         │
│  ┌───────────────────┐  │
│  │ users             │  │
│  │ events            │  │
│  │ shifts            │  │
│  │ equipment         │  │
│  │ ip_blacklist      │  │
│  │ ip_quarantine     │  │
│  │ security_log      │  │  ← Mixed together
│  │ security_event    │  │
│  └───────────────────┘  │
└─────────────────────────┘

After:
┌──────────────────┐         ┌─────────────────────┐
│  Main Database   │         │ Security Database   │
│  ┌────────────┐  │         │ ┌─────────────────┐ │
│  │ users      │  │         │ │ ip_blacklist    │ │
│  │ events     │  │         │ │ ip_quarantine   │ │
│  │ shifts     │  │         │ │ security_log    │ │
│  │ equipment  │  │         │ │ security_event  │ │
│  └────────────┘  │         │ └─────────────────┘ │
└──────────────────┘         └─────────────────────┘
       ↑ app data                  ↑ threat data
    Instance 1          Instance 1, 2, 3 → SHARED!
    Instance 2
    Instance 3


# ============================================================================
# ROLLBACK (if needed)
# ============================================================================

To revert to single database:

1. Restore old code (previous git commit)
2. Manually move security tables back to main DB
3. Update imports back to main db
4. Restart app
5. Delete security.db file

But you won't need to! ✓


# ============================================================================
# PERFORMANCE NOTES
# ============================================================================

Benefits:
  ✓ Main app queries unaffected by security logs
  ✓ Can use different DB types (main=PostgreSQL, security=SQLite)
  ✓ Security DB can be read-only for most users
  ✓ Can add indexes only for security access patterns

Considerations:
  ✓ Two DB connections consume slightly more memory
  ✓ Ensure DB credentials kept secure
  ✓ Monitor both DB growth over time
  ✓ Archive old security logs periodically (30 days?)


# ============================================================================
# SUPPORT
# ============================================================================

Issues? Check:
  - SECURITY_DATABASE_SETUP.md (comprehensive guide)
  - models_security.py (all security models)
  - app.py (initialization code)
  - .env configuration

"""
