"""
SEPARATE SECURITY DATABASE SETUP GUIDE
========================================

ShowWise now uses TWO separate databases:
1. Main Application Database (for users, events, shifts, etc.)
2. Security Database (for IP logs, blacklist, quarantine, events)

This architecture allows multiple ShowWise instances to share the same
centralized security database while maintaining separate application data.
"""

# ============================================================================
# ENVIRONMENT VARIABLE CONFIGURATION
# ============================================================================

# Add to your .env file:

# Main application database
DATABASE_URL=postgresql://user:pass@host:5432/showwise_main
# or for SQLite:
# DATABASE_URL=sqlite:///production_crew.db

# SEPARATE security database (can be on different server!)
SECURITY_DATABASE_URL=postgresql://user:pass@security-host:5432/showwise_security
# or for SQLite:
# SECURITY_DATABASE_URL=sqlite:///security.db

# Optional: Set instance name for tracking in logs
SHOWWISE_INSTANCE_NAME=instance-1


# ============================================================================
# BENEFITS OF SEPARATE SECURITY DATABASE
# ============================================================================

✓ Centralized Security Monitoring
  - All instances report to single security database
  - See threats across the entire organization
  - One admin dashboard for all instances

✓ Scalability
  - Main database can scale independently
  - Security database optimized for read-heavy access
  - Can use different database types/providers

✓ Data Isolation
  - Security logs never mix with business data
  - Easy to rotate/backup security data separately
  - Can restrict access to security DB

✓ Performance
  - Main app not impacted by security queries
  - Security logging doesn't slow down application
  - Can use read replicas for analytics

✓ Multi-Instance Deployment
  - 3 ShowWise instances → 3 main DBs
  - All 3 → 1 shared security DB
  - Centralized threat detection


# ============================================================================
# DATABASE SETUP INSTRUCTIONS
# ============================================================================

### SETUP 1: Both SQLite (Simple Development)

# .env file:
DATABASE_URL=sqlite:///production_crew.db
SECURITY_DATABASE_URL=sqlite:///security.db

# Just run your app, databases are created automatically


### SETUP 2: PostgreSQL Main + PostgreSQL Security

# Create databases on YOUR PostgreSQL server:

createdb showwise_main
createdb showwise_security

# .env file:
DATABASE_URL=postgresql://user:password@localhost:5432/showwise_main
SECURITY_DATABASE_URL=postgresql://user:password@localhost:5432/showwise_security

# Run migrations (see below)


### SETUP 3: PostgreSQL Main + Remote Security DB

# Remote security database (different server):

On security-server.com:
  createdb showwise_security

# On your ShowWise host:
DATABASE_URL=postgresql://user:pass@localhost:5432/showwise_main
SECURITY_DATABASE_URL=postgresql://user:pass@security-server.com:5432/showwise_security


### SETUP 4: Multi-Instance with Shared Security DB

Instance 1:
DATABASE_URL=postgresql://user:pass@host1:5432/showwise_instance1
SECURITY_DATABASE_URL=postgresql://security-user:security-pass@security-server:5432/shared-security

Instance 2:
DATABASE_URL=postgresql://user:pass@host2:5432/showwise_instance2
SECURITY_DATABASE_URL=postgresql://security-user:security-pass@security-server:5432/shared-security

Instance 3:
DATABASE_URL=postgresql://user:pass@host3:5432/showwise_instance3
SECURITY_DATABASE_URL=postgresql://security-user:security-pass@security-server:5432/shared-security

Result: All 3 instances feed into ONE centralized security database


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

### Option 1: Automatic (Recommended)

Just restart your Flask application:

  python app.py

Both databases will be created and initialized automatically.


### Option 2: Manual Flask Shell

  $ python
  >>> from app import create_app
  >>> from extensions import db, security_db
  >>> app = create_app()
  >>> with app.app_context():
  ...     db.create_all()              # Create main tables
  ...     security_db.create_all()    # Create security tables


### Option 3: Flask-Migrate (for Production)

If using Flask-Migrate migrations:

  # Create security database tables
  flask db upgrade

  # Security models don't need migration (static schema)
  # They're created directly via security_db.create_all()


# ============================================================================
# MODELS LOCATION
# ============================================================================

Main Application Models:
  → Location: models.py
  → Database: db (main DATABASE_URL)
  → Includes: User, Event, Shift, Equipment, etc.

Security Models:
  → Location: models_security.py
  → Database: security_db (SECURITY_DATABASE_URL)
  → Includes: IPBlacklist, IPQuarantine, SecurityLog, SecurityEvent

This separation is INTENTIONAL and CLEAN.


# ============================================================================
# MULTI-INSTANCE SCENARIO - DETAILED EXAMPLE
# ============================================================================

You have 3 ShowWise deployments:

Scenario: Theater Organization
- NYC Office (Instance 1)
- LA Office (Instance 2)  
- London Office (Instance 3)

Setup:

On NYC host (instance1.company.com):
  .env:
    DATABASE_URL=postgresql://ny_user:pass@ny-db.company.com:5432/showwise_ny
    SECURITY_DATABASE_URL=postgresql://sec_user:sec_pass@security.company.com:5432/showwise_security
    SHOWWISE_INSTANCE_NAME=nyc-office

On LA host (instance2.company.com):
  .env:
    DATABASE_URL=postgresql://la_user:pass@la-db.company.com:5432/showwise_la
    SECURITY_DATABASE_URL=postgresql://sec_user:sec_pass@security.company.com:5432/showwise_security
    SHOWWISE_INSTANCE_NAME=la-office

On London host (instance3.company.com):
  .env:
    DATABASE_URL=postgresql://uk_user:pass@uk-db.company.com:5432/showwise_uk
    SECURITY_DATABASE_URL=postgresql://sec_user:sec_pass@security.company.com:5432/showwise_security
    SHOWWISE_INSTANCE_NAME=london-office


Result:
=======

NYC user accesses: instance1.company.com/security/dashboard
LA user accesses: instance2.company.com/security/dashboard
London user accesses: instance3.company.com/security/dashboard

BUT: All three dashboards connect to the SAME security database!

So you see:
- NYC: Threats from NYC users
- LA: Threats from LA users
- LONDON: Threats from London users

AND each dashboard shows ALL threats from all instances!


# ============================================================================
# DATABASE QUERY EXAMPLES
# ============================================================================

# In your code:

from extensions import db, security_db
from models import User, Event
from models_security import SecurityLog, IPBlacklist

# Main database query
user = User.query.get(1)  # Implicitly uses db

# Security database query
threats = SecurityLog.query.filter_by(ip_address='192.168.1.1').all()  # Uses security_db

# Mixed query (examples)
main_objects = db.session.query(Event).all()
security_objects = security_db.session.query(SecurityLog).all()


# ============================================================================
# BACKUP & RESTORE
# ============================================================================

### Backup Main Database
pg_dump showwise_main > showwise_main_backup.sql

### Backup Security Database (Separate)
pg_dump showwise_security > security_backup.sql

### Selective Backup (Just high-priority events)
pg_dump showwise_security -t security_event > critical_events.sql

### Restore
psql showwise_main < showwise_main_backup.sql
psql showwise_security < security_backup.sql


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

Q: I see "No such table: ip_blacklist" error
A: Security tables not created. Run: python app.py (auto-creates tables)

Q: Security logs not appearing
A: Check SECURITY_DATABASE_URL in .env is correct
   Verify database exists and is accessible

Q: Connection error to security database
A: Check network connectivity to security DB host
   Verify credentials in SECURITY_DATABASE_URL
   Check firewall rules for database port

Q: Queries slow when multiple instances running
A: Add index on security_log.ip_address
   Consider read replicas for security DB

Q: Instance name not showing in logs
A: Set SHOWWISE_INSTANCE_NAME env var
   Format: [a-zA-Z0-9_-]


# ============================================================================
# BEST PRACTICES
# ============================================================================

✓ Use strong passwords for security DB
✓ Restrict network access to security DB
✓ Regular backups of BOTH databases
✓ Monitor security DB size (index appropriately)
✓ Set SHOWWISE_INSTANCE_NAME for each instance
✓ Document your database topology
✓ Test failover procedures
✓ Archive old security logs periodically
✓ Use read replicas for analytics queries


"""
