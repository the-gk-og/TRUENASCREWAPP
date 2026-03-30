"""
SECURITY SYSTEM - QUICK START GUIDE
====================================

Get your ShowWise security dashboard running in 5 minutes.
"""

# ============================================================================
# STEP 1: DATABASE MIGRATION
# ============================================================================

The new security database tables are created automatically when you:

Option A (Recommended):
    cd /home/elijah/Documents/Projects/WEBAPPS/Active-ShowWise/ShowWise
    flask db migrate -m "Add security models"
    flask db upgrade

Option B (Manual):
    python
    >>> from app import create_app, init_db
    >>> app = create_app()
    >>> init_db(app)

The following tables will be created:
    - ip_blacklist
    - ip_quarantine
    - security_log
    - security_event


# ============================================================================
# STEP 2: RESTART APPLICATION
# ============================================================================

Restart your Flask application so the new security middleware loads:

    pkill -f "python.*app.py"
    python app.py

Or if using systemd:
    systemctl restart showwise


# ============================================================================
# STEP 3: ACCESS THE DASHBOARD
# ============================================================================

Navigate to: http://yourdomain.com/security/dashboard

Login with your admin account (required to access).

You should see:
    - Security Dashboard with stats
    - Real-time threat monitoring
    - Quarantine queue
    - Blacklist management


# ============================================================================
# CLOUD FLARE TUNNEL CONFIGURATION
# ============================================================================

No additional configuration needed!

The security system automatically:
    ✓ Detects Cloudflare tunnel connections
    ✓ Extracts client IP from CF-Connecting-IP header
    ✓ Falls back to X-Forwarded-For from proxy
    ✓ Uses direct remote_addr if needed

This works with your existing ProxyFix configuration in app.py.


# ============================================================================
# IMMEDIATE PROTECTIONS ACTIVE
# ============================================================================

As soon as you restart, your app is protected against:

🚫 BURPSUITE & SECURITY SCANNERS
    - Immediately blocks any scanning tools
    - 403 Forbidden response
    - Admin alert created

🔓 SQL INJECTION ATTACKS
    - Detects and quarantines suspicious IPs
    - Chains to admin dashboard
    - Complete request logs

<> CROSS-SITE SCRIPTING (XSS)
    - JavaScript injection attempts blocked
    - HTML markup injection detected
    - Event handler injection flagged

🔧 COMMAND INJECTION
    - Shell command patterns blocked
    - System access attempts flagged

⚡ RATE LIMITING
    - Detects 100+ requests/5 minutes
    - Indicates scanning or DoS
    - Quarantined for review


# ============================================================================
# FIRST-TIME ADMIN TASKS
# ============================================================================

1. LOGIN TO DASHBOARD
   Navigate to: /security/dashboard

2. CHECK UNACKNOWLEDGED EVENTS
   Menu: Security Events
   Acknowledge and review any incidents

3. REVIEW QUARANTINE QUEUE
   Menu: Quarantine
   Approve safe IPs or reject threats

4. WHITELIST YOUR IPS
   If your team gets quarantined:
   - Find their IP in dashboard
   - Click "Approve"
   - Reason: "Office network - internal team"

5. CUSTOMIZE BLACKLIST
   Manual add option for known threats


# ============================================================================
# DAILY MANAGEMENT
# ============================================================================

Recommended daily tasks:

MORNING:
    [ ] Check dashboard for overnight attacks
    [ ] Review critical events
    [ ] Approve/reject quarantine queue

AFTERNOON:
    [ ] Monitor for false positives
    [ ] Review security logs
    [ ] Approve legitimate IPs

WEEKLY:
    [ ] Export security report
    [ ] Review trends
    [ ] Update threat patterns if needed


# ============================================================================
# MENU STRUCTURE
# ============================================================================

/security/dashboard
    Main dashboard with real-time stats
    Quick links to all sections
    Auto-refreshes every 30 seconds

/security/quarantine
    View all quarantined IPs
    Filter and sort
    Approve/reject actions

/security/quarantine/<IP>
    Detailed view for specific IP
    All requests from that IP
    Advanced threat analysis
    Take action (approve/blacklist)

/security/blacklist
    View permanently blocked IPs
    Manually add new blocks
    Remove blocks (whitelist)
    See reason for each block

/security/events
    Timeline of security incidents
    Filter by type/severity
    Acknowledge events

/security/logs
    Raw request logs
    Filter by IP or threat type
    Deep dive investigation


# ============================================================================
# COMMON SCENARIOS
# ============================================================================

SCENARIO 1: BurpSuite Attack
    1. See alert on dashboard
    2. Check high-risk IPs
    3. Click "Review"
    4. See BurpSuite in threats
    5. Click "Reject & Blacklist"
    6. IP blocked immediately

SCENARIO 2: False Positive (Legitimate User)
    1. User reports "Access Denied"
    2. Log in to /security/dashboard
    3. Find their IP in quarantine
    4. Review their recent requests
    5. Click "Approve"
    6. User can access again

SCENARIO 3: Suspicious Pattern
    1. See IP with "high_request_rate"
    2. Click to view details
    3. Analyze request pattern
    4. If automated: Reject & Blacklist
    5. If human error: Approve with note

SCENARIO 4: SQL Injection Attempt
    1. See 'sqli' flag on threat log
    2. Review the malicious request
    3. See WHERE clause injection attempt
    4. Reject & Blacklist immediately
    5. Note: "SQL injection attempt detected"


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

Q: Dashboard not loading after restart
A: Check Python errors in logs
   Verify security_bp registered in routes/__init__.py
   Confirm admin user exists with is_admin=True

Q: No threats being detected
A: Check app is restarted (middleware must load)
   Verify security_check() function in app.py
   Check browser console for errors

Q: Legitimate requests being flagged
A: Review the request in /security/logs
   Check which threat pattern matched
   May need to fine-tune regex patterns
   Approve the IP if it's a false positive

Q: Can't access admin dashboard
A: Verify you're logged in
   Check is_admin = True on your user in database
   Try: User.query.filter_by(username='admin').first()

Q: Want to disable security temporarily
A: Comment out the security_check() function in app.py
   Restart application
   WARNING: Makes your app vulnerable!


# ============================================================================
# SECURITY EVENT TYPES
# ============================================================================

threat_detected
    General threat flag detected
    Severity varies by threat type

burp_detected
    BurpSuite scanner confirmed
    Severity: CRITICAL
    Action: Immediate block

blacklisted_access_attempt
    Blacklisted IP tried to access
    Severity: HIGH
    Action: Block + alert

ip_approved
    Admin approved an IP
    Severity: LOW
    Action: Log only

ip_blacklisted
    Admin added IP to blacklist
    Severity: MEDIUM
    Action: Block + alert


# ============================================================================
# NEXT STEPS
# ============================================================================

1. Start the app: python app.py
2. Login as admin
3. Go to /security/dashboard
4. Try scanning with BurpSuite from your IP:
   - See immediate block
   - See threat alert on dashboard
   - See request in logs
5. Approve your IP to test whitelist
6. Monitor the dashboard for real attacks

Enjoy your enterprise-grade security! 🔒
"""
