# SECURITY ENHANCEMENTS IMPLEMENTATION

## Overview
Comprehensive security hardening for ShowWise with account lockout, CSRF protection, rate limiting, input sanitization, and comprehensive audit logging.

## Changes Made

### 1. ✅ CSRF Protection
**File:** `extensions.py`, `app.py`
- Added `CSRFProtect` from `flask-wtf`
- Initialized in app factory
- Protects all form submissions from cross-site request forgery
- CSRF tokens automatically included in session

### 2. ✅ Security Headers
**File:** `app.py`
- Added `@app.after_request` decorator with 9 security headers:
  - `X-Frame-Options: DENY` - Prevent clickjacking
  - `X-Content-Type-Options: nosniff` - Prevent MIME sniffing
  - `X-XSS-Protection: 1; mode=block` - Enable XSS filters
  - `Strict-Transport-Security` - Force HTTPS (production only)
  - `Content-Security-Policy` - Restrict script/style origins
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `X-Permitted-Cross-Domain-Policies: none`

### 3. ✅ Account Lockout After Failed Logins
**Files:** `models.py`, `routes/auth.py`, `utils_security.py`
- Added 4 security fields to User model:
  - `failed_login_attempts` - Counter
  - `locked_until` - Datetime for automatic unlock
  - `last_login_attempt` - Track attempts
  - `email_verified` - Email verification flag
  - `email_verification_token` - For email confirmation
- Logic: 5 failed attempts → 30-minute lockout
- Automatic unlock after duration expires
- Failed attempts tracked and logged

### 4. ✅ Rate Limiting
**File:** `extensions.py`, `routes/auth.py`
- Added `flask-limiter` with memory storage
- Login route: **10 attempts per minute**
- Signup route: **5 attempts per hour**
- Can be configured per-endpoint with `@limiter.limit()` decorator
- Distributed systems can use Redis: `redis://localhost:6379`

### 5. ✅ Input Sanitization & Validation
**File:** `utils_security.py` (NEW)
Functions:
- `sanitize_input()` - Remove HTML/scripts from user input
- `sanitize_filename()` - Prevent directory traversal
- `validate_email()` - Email format validation
- `validate_password_strength()` - Check password requirements (12+ chars, mixed case, symbols)
- `validate_username()` - Username format (alphanumeric, 3-50 chars)
- `is_account_locked()` - Check account lockout status
- `record_failed_login()` - Track failed attempts
- `record_successful_login()` - Clear failed attempts on success

### 6. ✅ Audit Logging
**Files:** `models_security.py`, `utils_security.py`
- New `AuditLog` model in security database:
  - `username` - Who performed action
  - `action` - What action ("user_created", "login", "password_changed", etc)
  - `resource_type` - Type of resource affected ("user", "shift", "crew", etc)
  - `resource_id` - ID of affected resource
  - `change_details` - JSON of field changes
  - `ip_address` - IP of request
  - `user_agent` - Browser/client info
  - `app_instance` - Which ShowWise instance
- `log_audit_action()` function for easy logging throughout app
- Tracks: logins, failed attempts, admin actions, data changes

### 7. ✅ Dependencies Added
**File:** `requirements.txt`
```
flask-wtf>=1.2      # CSRF protection
flask-limiter>=3.5  # Rate limiting per-endpoint
bleach>=6.1         # Input sanitization
```

## Usage Examples

### 1. Login with Account Lockout
```python
# In routes/auth.py - automatically handled
# Failed login 5 times → account locked 30 minutes
# Successfully logs clear failed attempts counter
```

### 2. CSRF Protection
```html
<!-- In templates, CSRF token auto-included -->
<form method="POST" action="/login">
    {{ csrf_token() }}
    <input name="username" required>
    <input type="password" name="password" required>
    <button>Login</button>
</form>
```

### 3. Sanitize User Input
```python
from utils_security import sanitize_input, validate_email

# Clean user input
clean_username = sanitize_input(request.form.get('username'))
clean_bio = sanitize_input(request.form.get('bio'), allow_html=False)

# Validate email
if not validate_email(email):
    flash('Invalid email format')
```

### 4. Log Audit Actions
```python
from utils_security import log_audit_action

log_audit_action(
    username=current_user.username,
    action='shift_created',
    resource_type='shift',
    resource_id=str(shift.id),
    resource_name=shift.name,
    change_details={'notes': {'old': None, 'new': 'New shift notes'}},
    ip_address=request.remote_addr,
    user_agent=request.headers.get('User-Agent')
)
```

### 5. Rate Limiting on Endpoints
```python
from extensions import limiter

@app.route('/api/export', methods=['POST'])
@limiter.limit("5 per hour")  # Max 5 exports per user per hour
def export_data():
    return jsonify({'status': 'exporting'})
```

## Database Migration

Run the migration to add new columns and tables:

```bash
python Migration_scripts/migration_add_security.py
```

This will:
1. Add new columns to User table
2. Create AuditLog table in security database
3. Display confirmation and next steps

## Configuration

### Update config.py (Already Done)
Session cookie security settings:
```python
SESSION_COOKIE_SECURE = True       # HTTPS only (production)
SESSION_COOKIE_HTTPONLY = True     # JS cannot access
SESSION_COOKIE_SAMESITE = 'Strict' # Prevent CSRF via cookies
PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
```

### Rate Limiter Storage
Default: In-memory (development)
Production: Use Redis
```python
# In extensions.py
storage_uri = "redis://localhost:6379"  # Use Redis for distributed systems
```

## Security Features by Threat Type

| Threat | Protection | Where |
|--------|-----------|-------|
| **CSRF** | CSRF tokens + SameSite cookies | flask-wtf + config.py |
| **Clickjacking** | X-Frame-Options: DENY | app.py after_request |
| **MIME Sniffing** | X-Content-Type-Options: nosniff | app.py after_request |
| **XSS** | CSP + X-XSS-Protection | app.py after_request |
| **Brute Force** | Account lockout + rate limiting | auth.py + utils_security.py |
| **Malicious Input** | Input sanitization | utils_security.py |
| **Data Tampering** | Secure cookies (HTTPS only) | config.py |
| **Unauthorized Changes** | Audit logging | models_security.py |

## Testing

### Test Account Lockout
```bash
# 1. Try login 5 times with wrong password
# Expected: After 5 attempts, "Account locked" message

# 2. Wait 30 minutes or check database
sqlite3 beta_security.db "SELECT locked_until FROM user WHERE username='admin';"

# 3. Account auto-unlocks after 30 minutes
```

### Test CSRF Protection
```bash
# 1. Try to POST to login without CSRF token
# Expected: 400 Bad Request (CSRF validation failed)

# 2. With valid CSRF token in session
# Expected: Form processed normally
```

### Test Rate Limiting
```bash
# 1. Make 11+ requests to /login in 1 minute
# Expected: 429 Too Many Requests after 10th request

# 2. Limit resets after 1 minute window
```

### Check Audit Logs
```bash
# View recent admin actions
sqlite3 beta_security.db "SELECT username, action, created_at FROM audit_log ORDER BY created_at DESC LIMIT 10;"
```

## Admin Dashboard Features

All security features accessible in admin dashboard:

### `/security/dashboard`
- Real-time threat stats
- Recent audit actions
- Top security events

### `/security/logs` 
- Full request audit trail
- Filter by IP, threat type, date range
- Export for analysis

### `/security/logs/audit`
- User action history
- Changes tracking
- Admin activity log

## Next Steps

1. **✅ Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **✅ Run migration:**
   ```bash
   python Migration_scripts/migration_add_security.py
   ```

3. **✅ Test account lockout:**
   - Try 5 failed logins
   - Verify lockout works

4. **✅ Review security settings:**
   - Check config.py for cookie security
   - Verify HTTPS in production
   - Test CSP headers

5. **✅ Add audit logging to existing routes:**
   - Use `log_audit_action()` in create/update/delete routes
   - Track important admin actions

6. **⏳ Optional: Implement email verification**
   - Use `email_verification_token` field
   - Send verification email on signup
   - Require email confirmation before login

7. **⏳ Optional: Implement 2FA email alerts**
   - Alert on unusual login locations
   - Notify on password changes
   - Failed login notifications

## Security Best Practices

Now Implemented:
- ✅ CSRF tokens on all forms
- ✅ Secure HTTP headers
- ✅ Account lockout mechanism
- ✅ Rate limiting
- ✅ Input sanitization
- ✅ Comprehensive audit logging
- ✅ Secure session cookies
- ✅ Brute force protection

Recommended (Future):
- 🔄 Email verification for signup
- 🔄 Two-factor authentication (already in code)
- 🔄 Session timeout warnings
- 🔄 IP-based suspicious activity alerts
- 🔄 Database encryption at rest
- 🔄 Regular security audits
- 🔄 Intrusion detection system

## Files Modified/Created

- ✅ `extensions.py` - Added CSRF and rate limiter
- ✅ `app.py` - Added security headers, CSRF/limiter init
- ✅ `models.py` - Added account lockout fields to User
- ✅ `models_security.py` - Added AuditLog model
- ✅ `utils_security.py` - New file with validation/sanitization
- ✅ `routes/auth.py` - Added account lockout logic
- ✅ `requirements.txt` - Added flask-wtf, flask-limiter, bleach
- ✅ `Migration_scripts/migration_add_security.py` - Migration script

## Support

For questions about security settings:
- See `README/SECURITY_SYSTEM.md` for overview
- Check `config.py` for configuration options
- Review `utils_security.py` for available functions
