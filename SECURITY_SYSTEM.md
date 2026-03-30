"""
SECURITY SYSTEM - COMPREHENSIVE GUIDE
======================================

This document explains the enterprise-grade security system added to ShowWise:
IP Blacklisting, Threat Detection (including BurpSuite), and Admin Dashboard.
"""

# ============================================================================
# OVERVIEW
# ============================================================================

The security system consists of:

1. **IP Blacklist** - Permanently block malicious IPs
2. **IP Quarantine** - Temporarily suspend suspicious IPs for human review
3. **Threat Detection** - Automatic detection of:
   - BurpSuite and other security scanners
   - SQL Injection (SQLi) attacks
   - Cross-Site Scripting (XSS) attacks
   - Command Injection attacks
   - High request rates (DoS/brute force)
4. **Security Logs** - Track all requests with threat flags
5. **Security Events** - High-level alerts for critical incidents
6. **Admin Dashboard** - Comprehensive management interface


# ============================================================================
# CLOUD FLARE TUNNEL INTEGRATION
# ============================================================================

The security system correctly handles Cloudflare tunnels:

🔹 IP Detection Priority:
   1. CF-Connecting-IP    ← Cloudflare client IP header (PRIMARY)
   2. X-Forwarded-For     ← Standard proxy header
   3. remote_addr         ← Direct connection

The security middleware extracts your actual client IP from Cloudflare headers,
ensuring accurate threat detection and blacklisting.


# ============================================================================
# DATABASE MODELS
# ============================================================================

Four new database tables are created:

1. IPBlacklist
   - ip_address: The blocked IP
   - reason: Why it was blocked
   - blocked_by: Admin username
   - created_at: When it was blocked
   - expires_at: Optional expiration (null = permanent)
   - is_active: Boolean to track if still active

2. IPQuarantine
   - ip_address: The suspect IP
   - threat_level: low, medium, high, critical
   - threat_details: JSON list of detected threats
   - status: pending, approved, rejected, manual_review
   - request_count: How many requests from this IP
   - reviewed_by: Admin who reviewed it
   - user_agent: Browser/scanner user agent string

3. SecurityLog
   - ip_address: Source IP
   - request_method: GET, POST, etc
   - request_path: The endpoint accessed
   - response_status: HTTP status code
   - user_agent: Browser string
   - threat_flags: Comma-separated threat flags detected
   - user_id: Authenticated user (if applicable)

4. SecurityEvent
   - event_type: burp_detected, threat_detected, blacklisted_access_attempt
   - ip_address: Source IP
   - severity: low, medium, high, critical
   - description: Event details
   - is_acknowledged: Admin has reviewed

Example:
   threat_flags: 'burpsuite,sqli,high_request_rate'
   This IP triggered BurpSuite detection, SQL injection, AND rate limiting


# ============================================================================
# THREAT DETECTION: WHAT GETS BLOCKED
# ============================================================================

### ⚠️ BURPSUITE & SECURITY SCANNERS
Detected by:
- User-Agent string patterns: 'burpsuite', 'owasp zap', 'sqlmap', 'nikto', etc
- Suspicious scanner headers
Action: IMMEDIATE BLOCK (403 Forbidden) + Security Event logged

Example scanners detected:
- BurpSuite (proxy/security testing)
- OWASP ZAP (penetration testing)
- SQLmap (SQL injection scanning)
- Nikto (web vulnerability scanner)
- Acunetix (automated scanning)
- Metasploit (exploitation framework)


### 🔓 SQL INJECTION (SQLi)
Patterns detected:
- 'UNION SELECT'
- 'DROP TABLE'
- Comments: '--', '/*'
- Logic bypass: '1=1', 'admin'--'
Action: Quarantine + Security Event

Example: 
  GET /api/users?id=1' OR '1'='1
  REQUEST BODY: email=admin'--


### <> CROSS-SITE SCRIPTING (XSS)
Patterns detected:
- <script> tags
- javascript: protocol
- Event handlers: onerror=, onclick=, onload=
- <iframe>, <svg>, other HTML injection
Action: Quarantine + Security Event

Example:
  GET /profile?name=<script>alert('hacked')</script>
  POST /comment with: <img onerror="fetch('attacker.com')">


### 🔧 COMMAND INJECTION
Patterns detected:
- Shell commands: ; cat, | bash, && rm -rf
- Command substitution: $(command), `command`
Action: Quarantine + Security Event

Example:
  GET /api/download?file=document.pdf; rm -rf /


### ⚡ RATE LIMITING
Threshold: 100+ requests in 5 minutes from one IP
Action: Quarantine + Monitor

Indicates:
- Automated scanning/brute force
- DoS attempt
- Bot activity


# ============================================================================
# ADMIN DASHBOARD: /security
# ============================================================================

Access: Admin users only
URL: http://yourdomain.com/security/dashboard

### Dashboard Pages:

1. **Dashboard (/security/dashboard)**
   - Real-time stats: Blacklisted IPs, Quarantined IPs, Critical Events
   - Quick links to all sections
   - Recent threats and high-risk IPs
   - Auto-refreshes every 30 seconds

2. **Quarantine List (/security/quarantine)**
   - View all quarantined IPs
   - Filter by: status, threat level, sort options
   - See which threats each IP triggered
   - Quick actions: Review, Approve, Reject

3. **Quarantine Detail (/security/quarantine/<ip>)**
   - Complete IP history
   - Threat breakdown and explanations
   - Last 20 requests from this IP
   - Approve or Reject buttons
   - Whitelist/Blacklist actions

4. **Blacklist (/security/blacklist)**
   - View all permanently blocked IPs
   - Manually add IPs with custom reason
   - Set expiration: Permanent, 7/30/90 days
   - Remove IPs (whitelist)
   - See who blocked each IP and when

5. **Security Events (/security/events)**
   - Timeline of all security incidents
   - Filter by: event type, severity, acknowledgement
   - Acknowledge events to mark as reviewed
   - See critical incidents at a glance

6. **Security Logs (/security/logs)**
   - All requests (optionally filtered by IP)
   - Show threat-flagged requests only
   - See which IPs had threats detected
   - Quick links to detailed view per IP


# ============================================================================
# TYPICAL WORKFLOW
# ============================================================================

### Scenario: BurpSuite Attack Detected

1. Request arrives with BurpSuite User-Agent
2. Security middleware detects it
3. SecurityEvent created with severity=critical
4. IP immediately blocked (403 response)
5. SecurityLog entry recorded with threat_flag='burpsuite'
6. Admin Dashboard shows:
   - New Critical Event notification
   - IP in "Recent Threat-Flagged Requests"
   - 🔴 High-Risk IPs list

7. Admin clicks "Review" on the IP
8. Dashboard shows:
   - All requests from that IP
   - User-Agent "BurpSuite User Scanner"
   - All paths attempted
   - No legitimate user account associated

9. Admin decision: "Reject & Blacklist"
10. IP automatically added to blacklist
11. Future requests from that IP get 403 immediately
12. Security Event logged: "IP blacklisted by admin_user"


### Scenario: Suspicious Pattern but Not Critical

1. IP makes 150 requests in 5 minutes
2. Detected: high_request_rate threat
3. IP quarantined (not immediately blocked)
4. Placed in "Pending Review" status
5. Admin reviews logs
6. Sees legitimate pattern: Auto-refresh on dashboard
7. Admin clicks "Approve: User monitoring their own dashboard"
8. IP moved to approved list
9. Future requests allowed (not blocked)


### Scenario: False Positive (Legitimate User)

1. IP triggers SQL injection pattern
   (legitimate search query: "find users where status='active'")
2. IP quarantined
3. Admin sees the request was legitimate
4. Clicks "Approve: False positive - legitimate search syntax"
5. IP approved
6. All future requests from this IP allowed


# ============================================================================
# API ENDPOINTS (JSON)
# ============================================================================

For programmatic access/dashboards:

GET /security/api/stats
- Returns JSON with blacklist count, quarantine count, event stats

GET /security/api/recent-events
- Returns last 20 security events in JSON format


# ============================================================================
# CONFIGURATION & CUSTOMIZATION
# ============================================================================

To modify threat detection, edit services/security_service.py:

BURPSUITE_INDICATORS = { ... }
  Add or remove User-Agent patterns

SQL_INJECTION_PATTERNS = [ ... ]
  Add or remove SQLi regex patterns

XSS_PATTERNS = [ ... ]
  Add or remove XSS patterns

COMMAND_INJECTION_PATTERNS = [ ... ]
  Add or remove command injection patterns

Rate limit threshold (line ~180):
  if recent_count > 100:  # Change 100 to your desired threshold


# ============================================================================
# SECURITY BEST PRACTICES
# ============================================================================

1. **Regular Reviews**
   - Check dashboard daily
   - Acknowledge security events
   - Review pending quarantine queue

2. **Whitelist Safe IPs**
   - Office networks
   - Team members' home IPs
   - Approved partner networks
   - After review, approve them in quarantine queue

3. **Set Expiration Dates**
   - Temporary blacklists (30 days) for minor issues
   - Permanent blacklist for serious attacks
   - Review pending IPs within 24 hours

4. **Monitor False Positives**
   - If legitimate users report blocked access
   - Review their IPs in dashboard
   - Approve them if safe

5. **Alert Integration** (Future)
   - Set up email alerts on critical events
   - Integrate with your SIEM
   - Log to centralized monitoring

6. **Backup Threat Rules**
   - Keep copies of threat patterns
   - Document any custom patterns you add
   - Track changes for audit


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

Q: Legitimate user's IP is blocked
A: Check /security/dashboard → Quarantine List
   Review the threats detected
   Click to view their requests
   If safe, click "Approve"

Q: BurpSuite is being allowed through
A: Check User-Agent is in BURPSUITE_INDICATORS
   Ensure pattern matches exactly
   Check SecurityLog to see what User-Agent was sent

Q: Too many false positives on SQL patterns
A: Review the detected patterns in /security/logs
   Update SQL_INJECTION_PATTERNS to be more specific
   Add whitelist for certain safe patterns (e.g., 'AND' in search)

Q: Rate limiting is too aggressive
A: Edit services/security_service.py
   Line ~180: if recent_count > 100:
   Change 100 to higher threshold (e.g., 500)

Q: Dashboard not loading
A: Check admin user has is_admin=True in database
   Verify security blueprint registered in routes/__init__.py
   Check Flask logs for errors


# ============================================================================
# LOGGING & MONITORING
# ============================================================================

All security activity is logged to the database:

SecurityLog table:
- Every request from potential threat IPs
- Every request with threat flags detected
- Queryable by IP, time range, threat type

SecurityEvent table:  
- High-level security incidents
- Sortable by severity and type
- Track acknowledged vs unacknowledged

Admin can:
- Export logs for compliance reports
- Generate threat statistics
- Identify patterns over time
- Demonstrate due diligence to auditors


# ============================================================================
# DATABASE MIGRATION
# ============================================================================

The new models are automatically created when you run:

flask db upgrade  (if using migrations)
or
python -c "from app import create_app, init_db; app = create_app(); init_db(app)" (manual)

Tables created:
- ip_blacklist
- ip_quarantine
- security_log
- security_event


# ============================================================================
# SUMMARY
# ============================================================================

Your ShowWise application now has military-grade security:

✓ Cloudflare tunnel support with correct IP extraction
✓ Detects and blocks BurpSuite and security scanners immediately
✓ Identifies SQL injection, XSS, command injection attempts
✓ Rate-limit detection for DoS/brute force
✓ Admin dashboard for managing threats
✓ Quarantine system for human review
✓ Permanent blacklisting option
✓ Complete audit trail of all threats
✓ Security events with severity levels
✓ Zero-touch threat detection


Access the dashboard at: /security/dashboard (admin only)
"""
