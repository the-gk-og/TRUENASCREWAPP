"""
routes/security.py
==================
Admin security dashboard: manage blacklists, quarantine IPs, view threat logs.
Uses the separate security_db for all security data.
"""

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func
from services.security_service import SecurityService
from models_security import SecurityEvent, IPQuarantine, IPBlacklist, SecurityLog
from extensions import security_db

security_bp = Blueprint('security', __name__, url_prefix='/security')


def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# DASHBOARD
# ============================================================================

@security_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Main security dashboard."""
    
    # Get summary stats
    blacklist_count = IPBlacklist.query.filter_by(is_active=True).count()
    quarantine_count = IPQuarantine.query.filter_by(status='pending').count()
    
    critical_events = SecurityEvent.query.filter(
        SecurityEvent.severity == 'critical',
        SecurityEvent.is_acknowledged == False
    ).count()

    # Recent activity
    recent_events = SecurityEvent.query.order_by(
        SecurityEvent.created_at.desc()
    ).limit(10).all()

    recent_logs = SecurityLog.query.filter(
        SecurityLog.threat_flags != None
    ).order_by(SecurityLog.created_at.desc()).limit(20).all()

    high_risk_ips = IPQuarantine.query.filter_by(
        status='pending'
    ).filter(
        IPQuarantine.threat_level.in_(['high', 'critical'])
    ).all()

    return render_template('security/dashboard.html',
        blacklist_count=blacklist_count,
        quarantine_count=quarantine_count,
        critical_events=critical_events,
        recent_events=recent_events,
        recent_logs=recent_logs,
        high_risk_ips=high_risk_ips[:5]  # Top 5
    )


# ============================================================================
# QUARANTINE MANAGEMENT
# ============================================================================

@security_bp.route('/quarantine')
@login_required
@admin_required
def quarantine_list():
    """List all quarantined IPs."""
    
    # Filters
    status = request.args.get('status', 'pending')
    threat_level = request.args.get('threat_level', 'all')
    sort_by = request.args.get('sort', 'last_activity')

    query = IPQuarantine.query

    if status != 'all':
        query = query.filter_by(status=status)

    if threat_level != 'all':
        query = query.filter_by(threat_level=threat_level)

    if sort_by == 'last_activity':
        query = query.order_by(IPQuarantine.last_activity.desc())
    elif sort_by == 'threat_level':
        query = query.order_by(IPQuarantine.threat_level.desc())
    elif sort_by == 'request_count':
        query = query.order_by(IPQuarantine.request_count.desc())

    quarantined_ips = query.all()

    return render_template('security/quarantine_list.html',
        quarantined_ips=quarantined_ips,
        current_status=status,
        current_threat_level=threat_level,
        sort_by=sort_by
    )


@security_bp.route('/quarantine/<ip_address>')
@login_required
@admin_required
def quarantine_detail(ip_address):
    """View details of a quarantined IP."""
    
    quarantine = IPQuarantine.query.filter_by(ip_address=ip_address).first()
    if not quarantine:
        flash('Quarantine record not found', 'danger')
        return redirect(url_for('security.quarantine_list'))

    # Get security logs for this IP
    logs = SecurityLog.query.filter_by(
        ip_address=ip_address
    ).order_by(SecurityLog.created_at.desc()).limit(100).all()

    # Get threat details
    import json
    threat_details = json.loads(quarantine.threat_details) if quarantine.threat_details else []

    # Get related security events
    events = SecurityEvent.query.filter_by(
        ip_address=ip_address
    ).order_by(SecurityEvent.created_at.desc()).all()

    return render_template('security/quarantine_detail.html',
        quarantine=quarantine,
        logs=logs,
        threat_details=threat_details,
        events=events
    )


@security_bp.route('/quarantine/<ip_address>/approve', methods=['POST'])
@login_required
@admin_required
def approve_quarantine(ip_address):
    """Approve a quarantined IP."""
    
    action = request.form.get('action', 'Approved after review')
    
    SecurityService.approve_quarantine(
        ip_address=ip_address,
        reviewed_by=current_user.username,
        action=action
    )

    flash(f'IP {ip_address} approved', 'success')
    return redirect(url_for('security.quarantine_list'))


@security_bp.route('/quarantine/<ip_address>/reject', methods=['POST'])
@login_required
@admin_required
def reject_quarantine(ip_address):
    """Reject and blacklist a quarantined IP."""
    
    reason = request.form.get('reason', 'Rejected from quarantine')
    
    SecurityService.reject_quarantine(
        ip_address=ip_address,
        reviewed_by=current_user.username,
        reason=reason
    )

    flash(f'IP {ip_address} rejected and blacklisted', 'success')
    return redirect(url_for('security.quarantine_list'))


# ============================================================================
# BLACKLIST MANAGEMENT
# ============================================================================

@security_bp.route('/blacklist')
@login_required
@admin_required
def blacklist():
    """View and manage IP blacklist."""
    
    # Get active blacklist
    active = IPBlacklist.query.filter_by(is_active=True).order_by(
        IPBlacklist.created_at.desc()
    ).all()

    return render_template('security/blacklist.html', active=active)


@security_bp.route('/blacklist/add', methods=['POST'])
@login_required
@admin_required
def add_blacklist():
    """Manually add IP to blacklist."""
    
    ip_address = request.form.get('ip_address', '').strip()
    reason = request.form.get('reason', 'Manual blacklist')
    duration = request.form.get('duration', 'permanent')

    if not ip_address:
        flash('IP address required', 'danger')
        return redirect(url_for('security.blacklist'))

    # Calculate expiry
    expires_at = None
    if duration == '7days':
        expires_at = datetime.utcnow() + timedelta(days=7)
    elif duration == '30days':
        expires_at = datetime.utcnow() + timedelta(days=30)
    elif duration == '90days':
        expires_at = datetime.utcnow() + timedelta(days=90)

    SecurityService.blacklist_ip(
        ip_address=ip_address,
        reason=reason,
        blocked_by=current_user.username,
        expires_at=expires_at
    )

    flash(f'IP {ip_address} added to blacklist', 'success')
    return redirect(url_for('security.blacklist'))


@security_bp.route('/blacklist/<ip_address>/remove', methods=['POST'])
@login_required
@admin_required
def remove_blacklist(ip_address):
    """Remove IP from blacklist (whitelist)."""
    
    SecurityService.whitelist_ip(ip_address)
    
    flash(f'IP {ip_address} removed from blacklist', 'success')
    return redirect(url_for('security.blacklist'))


# ============================================================================
# SECURITY EVENTS & LOGS
# ============================================================================

@security_bp.route('/events')
@login_required
@admin_required
def events():
    """View security events."""
    
    # Filters
    event_type = request.args.get('type', 'all')
    severity = request.args.get('severity', 'all')
    acknowledged = request.args.get('acknowledged', 'unacknowledged')

    query = SecurityEvent.query

    if event_type != 'all':
        query = query.filter_by(event_type=event_type)

    if severity != 'all':
        query = query.filter_by(severity=severity)

    if acknowledged == 'unacknowledged':
        query = query.filter_by(is_acknowledged=False)
    elif acknowledged == 'acknowledged':
        query = query.filter_by(is_acknowledged=True)

    security_events = query.order_by(
        SecurityEvent.created_at.desc()
    ).all()

    return render_template('security/events.html',
        events=security_events,
        current_type=event_type,
        current_severity=severity,
        current_acknowledged=acknowledged
    )


@security_bp.route('/events/<int:event_id>/acknowledge', methods=['POST'])
@login_required
@admin_required
def acknowledge_event(event_id):
    """Mark security event as acknowledged."""
    
    SecurityService.acknowledge_security_event(event_id, current_user.username)
    
    flash('Event acknowledged', 'success')
    return redirect(request.referrer or url_for('security.events'))


# ============================================================================
# SECURITY LOGS
# ============================================================================

@security_bp.route('/logs')
@login_required
@admin_required
def logs():
    """View security logs with threat flags."""
    
    ip_filter = request.args.get('ip', '')
    threat_only = request.args.get('threats_only', 'false') == 'true'
    limit = request.args.get('limit', 100, type=int)

    query = SecurityLog.query

    if ip_filter:
        query = query.filter_by(ip_address=ip_filter)

    if threat_only:
        query = query.filter(SecurityLog.threat_flags != None)

    logs = query.order_by(SecurityLog.created_at.desc()).limit(limit).all()

    # Get unique threatened IPs
    threatened_ips = security_db.session.query(SecurityLog.ip_address).filter(
        SecurityLog.threat_flags != None
    ).distinct().limit(50).all()

    return render_template('security/logs.html',
        logs=logs,
        ip_filter=ip_filter,
        threats_only=threat_only,
        threatened_ips=[ip[0] for ip in threatened_ips]
    )


@security_bp.route('/logs/ip/<ip_address>')
@login_required
@admin_required
def logs_by_ip(ip_address):
    """View all logs from a specific IP."""
    
    logs = SecurityLog.query.filter_by(
        ip_address=ip_address
    ).order_by(SecurityLog.created_at.desc()).limit(500).all()

    # Get IP status
    quarantine = IPQuarantine.query.filter_by(ip_address=ip_address).first()
    blacklist = IPBlacklist.query.filter_by(
        ip_address=ip_address,
        is_active=True
    ).first()

    return render_template('security/logs_by_ip.html',
        ip_address=ip_address,
        logs=logs,
        quarantine=quarantine,
        blacklist=blacklist
    )


# ============================================================================
# API ENDPOINTS (for dashboard updates)
# ============================================================================

@security_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """Get security stats as JSON."""
    
    from sqlalchemy import func
    from datetime import datetime, timedelta

    time_24h = datetime.utcnow() - timedelta(hours=24)
    time_7d = datetime.utcnow() - timedelta(days=7)

    stats = {
        'blacklist_count': IPBlacklist.query.filter_by(is_active=True).count(),
        'quarantine_count': IPQuarantine.query.filter_by(status='pending').count(),
        'critical_events': SecurityEvent.query.filter(
            SecurityEvent.severity == 'critical',
            SecurityEvent.is_acknowledged == False
        ).count(),
        'logs_24h': SecurityLog.query.filter(
            SecurityLog.created_at >= time_24h
        ).count(),
        'threats_24h': SecurityLog.query.filter(
            SecurityLog.created_at >= time_24h,
            SecurityLog.threat_flags != None
        ).count(),
        'events_7d': SecurityEvent.query.filter(
            SecurityEvent.created_at >= time_7d
        ).count(),
        'top_ips': [
            {
                'ip': ip,
                'count': count
            }
            for ip, count in security_db.session.query(
                SecurityLog.ip_address,
                func.count(SecurityLog.id)
            ).filter(
                SecurityLog.created_at >= time_24h
            ).group_by(SecurityLog.ip_address).order_by(
                func.count(SecurityLog.id).desc()
            ).limit(10)
        ]
    }

    return jsonify(stats)


@security_bp.route('/api/recent-events')
@login_required
@admin_required
def api_recent_events():
    """Get recent security events as JSON."""
    
    events = SecurityEvent.query.order_by(
        SecurityEvent.created_at.desc()
    ).limit(20).all()

    return jsonify({
        'events': [
            {
                'id': e.id,
                'type': e.event_type,
                'severity': e.severity,
                'ip': e.ip_address,
                'description': e.description,
                'created_at': e.created_at.isoformat(),
                'acknowledged': e.is_acknowledged
            }
            for e in events
        ]
    })
