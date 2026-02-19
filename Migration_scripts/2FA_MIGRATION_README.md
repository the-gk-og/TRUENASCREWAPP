# 2FA Migration - Quick Start Guide

## ✅ Status

Your 2FA database table is **already set up and ready to use**.

## 📁 Files Created

| File | Purpose |
|------|---------|
| `migrate_2fa.py` | Standalone 2FA migration script |
| `run_migrations.py` | Master migration runner (runs all migrations) |
| `MIGRATION_GUIDE.md` | Complete migration documentation |

## 🚀 How to Use

### Option 1: Run 2FA Migration Only
```bash
cd Migration_scripts
python migrate_2fa.py
```

**Output**:
```
✓ two_factor_auth table already exists
✓ All required columns present
✓ Migration completed successfully!
```

### Option 2: Run All Migrations
```bash
cd Migration_scripts
python run_migrations.py
```

**Output**:
```
Found 1 migration(s)
Running migration: 2fa
✓ two_factor_auth table already exists
✓ All required columns present

Migration Summary
✓ 2fa
Total: 1 successful, 0 failed
```

### Option 3: List Available Migrations
```bash
cd Migration_scripts
python run_migrations.py --list
```

**Output**:
```
Available migrations:
  ✓ 2fa (migrate_2fa)
```

## 🎯 What the 2FA Table Does

Stores Two-Factor Authentication settings for users:

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer | Unique identifier |
| `user_id` | Integer | Link to user (unique) |
| `secret` | String | TOTP secret (32 chars) |
| `enabled` | Boolean | Is 2FA active? |
| `backup_codes` | Text | JSON array of backup codes (hashed) |
| `created_at` | DateTime | When 2FA was set up |

## 🔐 How 2FA Works in Your App

### 1. User Enables 2FA
```
User clicks "Enable 2FA"
  ↓
App generates TOTP secret
  ↓
QR code displayed (Authy, Google Authenticator)
  ↓
User scans QR code
  ↓
User enters 6-digit code to verify
  ↓
2FA enabled + backup codes generated
```

### 2. Login with 2FA Active
```
User enters username/password
  ↓
Password validated
  ↓
App checks if 2FA enabled
  ↓
Shows "Enter 6-digit code" prompt
  ↓
User enters code from authenticator app
  ↓
Code verified
  ↓
User logged in
```

### 3. Backup Codes
```
10 backup codes generated
  ↓
User saves them securely
  ↓
Each code can be used once
  ↓
Used when authenticator app unavailable
```

## 💾 Migrating Other Tables

The same migration system can be used for future changes:

```bash
# Add a new migration file
Migration_scripts/migrate_newfeature.py

# Auto-discovered and can be run via:
python run_migrations.py
```

## 🆘 Rollback (If Needed)

```bash
# WARNING: This deletes the 2FA table and all data
python migrate_2fa.py --rollback
```

## 📊 Verify Database Setup

```bash
# Check if 2FA table exists
sqlite3 production_crew.db ".schema two_factor_auth"

# Count 2FA records
sqlite3 production_crew.db "SELECT COUNT(*) FROM two_factor_auth;"

# See table structure
sqlite3 production_crew.db ".schema"
```

## 🎓 Learning Resources

- Full documentation: `Migration_scripts/MIGRATION_GUIDE.md`
- Flask-SQLAlchemy: [https://flask-sqlalchemy.palletsprojects.com/](https://flask-sqlalchemy.palletsprojects.com/)
- TOTP/2FA: [https://en.wikipedia.org/wiki/Time-based_one-time_password](https://en.wikipedia.org/wiki/Time-based_one-time_password)

## ✨ Next Steps

1. **Restart your app** to ensure 2FA is working
2. **Test 2FA** by enabling it in security settings
3. **Document** any custom migrations in `MIGRATION_GUIDE.md`
4. **Backup** regularly before running migrations

---

**Your app is now fully prepared for 2FA!** 🎉
