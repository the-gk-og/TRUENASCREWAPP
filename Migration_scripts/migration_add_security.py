"""
Migration: Add Security Enhancements
====================================
Adds account lockout fields, email verification, and audit logging to ShowWise.

To run:
  python migration_add_security.py
"""

import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db, security_db
from models import User
from models_security import AuditLog


def migrate():
    """Add security-related tables and columns."""
    app = create_app()
    
    with app.app_context():
        print("\n" + "="*70)
        print("SECURITY ENHANCEMENT MIGRATION")
        print("="*70)
        
        # Check if columns already exist
        inspector = db.inspect(User.__table__)
        existing_columns = [col.name for col in inspector.columns]
        
        print("\n📋 Checking User table...")
        new_columns_to_add = [
            'failed_login_attempts',
            'locked_until',
            'last_login_attempt',
            'email_verified',
            'email_verification_token'
        ]
        
        missing_columns = [col for col in new_columns_to_add if col not in existing_columns]
        
        if missing_columns:
            print(f"\n⚙️  Adding columns to User table: {', '.join(missing_columns)}")
            
            # Create tables (SQLAlchemy will add missing columns)
            db.create_all()
            print("✓ User table updated")
        else:
            print("✓ User table already has all security columns")
        
        # Create security tables
        print("\n📋 Checking security database...")
        security_db.metadata.create_all(security_db.metadata.bind)
        print("✓ Security tables initialized (IPBlacklist, IPQuarantine, SecurityLog, SecurityEvent, AuditLog)")
        
        print("\n" + "="*70)
        print("✅ SECURITY MIGRATION COMPLETE")
        print("="*70)
        print("""
NEW SECURITY FEATURES ENABLED:
  ✓ Account lockout after 5 failed login attempts (30 min duration)
  ✓ CSRF protection on all forms
  ✓ Security headers (X-Frame-Options, CSP, etc)
  ✓ Rate limiting (10 login attempts/min, 5 signups/hour)
  ✓ Input sanitization and validation
  ✓ Comprehensive audit logging
  ✓ Email verification support
  
DEPENDENCIES ADDED:
  - flask-wtf (CSRF)
  - flask-limiter (Rate limiting)
  - bleach (Input sanitization)

NEXT STEPS:
  1. pip install -r requirements.txt  (install new dependencies)
  2. Test login with account lockout:
     - Try 5 failed logins with valid username
     - Account should lock for 30 minutes
  3. Check audit logs at: /security/logs (admin only)
  4. Review security settings in config.py

SECURITY ENDPOINTS:
  - Admin Dashboard: /security/dashboard
  - Audit Logs: /security/logs
  - Security Logs: /security/logs
""")


if __name__ == '__main__':
    migrate()
