"""
routes/email_otp.py
===================
Email-based OTP as a secondary (fallback) 2FA option.

Endpoints:
  POST /api/2fa/email-otp/enable       – enable email OTP for the logged-in user
  POST /api/2fa/email-otp/disable      – disable email OTP (requires password)
  POST /api/2fa/email-otp/send         – send OTP to pending-login user's email
  POST /api/2fa/email-otp/verify-login – verify OTP and complete login
  POST /api/2fa/email-otp/verify-setup – verify a code during initial setup
  GET  /login/2fa/email                – the email-OTP login page
"""

import secrets
import string
from datetime import datetime, timedelta

from flask import (
    Blueprint, jsonify, request, redirect,
    url_for, session, render_template,
)
from flask_login import login_user, login_required, current_user
from werkzeug.security import check_password_hash

from extensions import db
from models import User, TwoFactorAuth, EmailOTP
from utils import log_security_event, get_organization
from constants import DEFAULT_ORG

email_otp_bp = Blueprint("email_otp", __name__)

OTP_LENGTH  = 6          # digits
OTP_EXPIRY  = 10         # minutes
OTP_DIGITS  = string.digits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_otp() -> str:
    return "".join(secrets.choice(OTP_DIGITS) for _ in range(OTP_LENGTH))


def _get_or_create_email_otp(user_id: int) -> EmailOTP:
    rec = EmailOTP.query.filter_by(user_id=user_id).first()
    if not rec:
        rec = EmailOTP(user_id=user_id, otp_used=True)
        db.session.add(rec)
        db.session.commit()
    return rec


def _send_otp_email(user: User, otp: str) -> bool:
    """Send the OTP via the existing email service."""
    if not user.email:
        return False
    try:
        from services.email_service import send_html_email
        from utils import get_organization
        org = get_organization() or {}
        primary_color = org.get("primary_color", "#6366f1")
        org_name      = org.get("name", "ShowWise")

        subject   = f"Your {org_name} login code: {otp}"
        html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:40px 0;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:14px;overflow:hidden;
                  box-shadow:0 4px 20px rgba(0,0,0,0.08);">
      <tr><td style="background:linear-gradient(135deg,{primary_color},#a855f7);
                     padding:36px 44px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;">🔐 Login Verification</h1>
        <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:15px;">{org_name}</p>
      </td></tr>
      <tr><td style="padding:36px 44px;">
        <p style="font-size:16px;color:#374151;margin:0 0 8px;">Hi <strong>{user.username}</strong>,</p>
        <p style="font-size:15px;color:#4b5563;line-height:1.7;margin:0 0 28px;">
          Use the code below to complete your login. It expires in <strong>{OTP_EXPIRY} minutes</strong>.
        </p>
        <div style="background:#f5f3ff;border:2px solid {primary_color};border-radius:12px;
                    padding:24px;text-align:center;margin:0 0 24px;">
          <p style="margin:0 0 6px;font-size:12px;color:#7c3aed;font-weight:600;
                    letter-spacing:2px;text-transform:uppercase;">Your login code</p>
          <p style="margin:0;font-size:42px;font-weight:800;color:#1f2937;
                    letter-spacing:12px;font-family:monospace;">{otp}</p>
        </div>
        <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:12px 16px;">
          <p style="margin:0;font-size:13px;color:#b91c1c;">
            🚨 If you didn't try to log in, ignore this email — your account is safe.
          </p>
        </div>
      </td></tr>
      <tr><td style="background:#f9fafb;padding:18px 44px;text-align:center;">
        <p style="margin:0;font-size:12px;color:#d1d5db;">
          &copy; {org_name} &middot; Powered by ShowWise
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

        text_body = (
            f"Hi {user.username},\n\n"
            f"Your ShowWise login code is: {otp}\n\n"
            f"It expires in {OTP_EXPIRY} minutes.\n\n"
            f"If you didn't request this, ignore this email.\n\nShowWise"
        )
        return send_html_email(subject, user.email, html_body, text_body)
    except Exception as exc:
        print(f"Email OTP send error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Login-time page  (served to pending-2fa users who chose email OTP)
# ---------------------------------------------------------------------------

@email_otp_bp.route("/login/2fa/email")
def email_otp_verify_page():
    if "pending_2fa_user_id" not in session:
        return redirect(url_for("auth.login"))
    user = User.query.get(session["pending_2fa_user_id"])
    if not user:
        session.pop("pending_2fa_user_id", None)
        return redirect(url_for("auth.login"))
    org = get_organization() or DEFAULT_ORG

    # Mask email for display: j***@example.com
    masked = ""
    if user.email:
        parts = user.email.split("@")
        masked = parts[0][0] + "***@" + parts[1] if len(parts) == 2 else "***"

    return render_template(
        "email_otp_verify.html",
        organization=org,
        username=user.username,
        masked_email=masked,
    )


# ---------------------------------------------------------------------------
# Send OTP (during login — called by the email-OTP verify page)
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/send", methods=["POST"])
def send_login_otp():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return jsonify({"error": "No pending login session"}), 400

    user = User.query.get(user_id)
    if not user or not user.email:
        return jsonify({"error": "No email address on file for this account"}), 400

    rec  = _get_or_create_email_otp(user_id)
    otp  = _generate_otp()
    rec.otp_code   = otp
    rec.otp_expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    rec.otp_used   = False
    db.session.commit()

    sent = _send_otp_email(user, otp)
    if sent:
        return jsonify({"success": True, "message": f"Code sent to your email"})
    return jsonify({"error": "Failed to send email — check mail configuration"}), 500


# ---------------------------------------------------------------------------
# Verify OTP at login time
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/verify-login", methods=["POST"])
def verify_login_otp():
    data    = request.json or {}
    code    = (data.get("code") or "").strip()
    user_id = session.get("pending_2fa_user_id")

    if not user_id:
        return jsonify({"error": "No pending login session"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    rec = EmailOTP.query.filter_by(user_id=user_id).first()
    if not rec or rec.otp_used or not rec.otp_code:
        return jsonify({"error": "No active code — please request a new one"}), 400

    if datetime.utcnow() > rec.otp_expiry:
        rec.otp_used = True
        db.session.commit()
        return jsonify({"error": "Code has expired — please request a new one"}), 400

    if rec.otp_code != code:
        return jsonify({"error": "Invalid code — please try again"}), 400

    # Success — invalidate the code and log in
    rec.otp_used = True
    db.session.commit()

    session.pop("pending_2fa_user_id", None)
    login_user(user, remember=session.pop("pending_2fa_remember", False))
    log_security_event("EMAIL_OTP_LOGIN_SUCCESS", username=user.username)

    return jsonify({
        "success":  True,
        "redirect": url_for("cast.cast_events") if user.is_cast else url_for("crew.dashboard"),
    })


# ---------------------------------------------------------------------------
# Setup — send a verification code to the logged-in user's email
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/send-setup", methods=["POST"])
@login_required
def send_setup_otp():
    """Send a verification OTP to the currently-logged-in user's email to confirm setup."""
    if not current_user.email:
        return jsonify({"error": "You need an email address to use email OTP. Add one in Settings → Security."}), 400

    # Cannot enable email OTP if TOTP is already active
    totp = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if totp and totp.enabled:
        return jsonify({"error": "Disable TOTP 2FA before switching to email OTP"}), 400

    rec = _get_or_create_email_otp(current_user.id)
    otp = _generate_otp()
    rec.otp_code   = otp
    rec.otp_expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    rec.otp_used   = False
    db.session.commit()

    sent = _send_otp_email(current_user, otp)
    if sent:
        return jsonify({"success": True})
    return jsonify({"error": "Failed to send email"}), 500


# ---------------------------------------------------------------------------
# Setup — verify the code and enable email OTP
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/verify-setup", methods=["POST"])
@login_required
def verify_setup_otp():
    data = request.json or {}
    code = (data.get("code") or "").strip()

    rec = EmailOTP.query.filter_by(user_id=current_user.id).first()
    if not rec or rec.otp_used or not rec.otp_code:
        return jsonify({"error": "No active code — please request a new one"}), 400

    if datetime.utcnow() > rec.otp_expiry:
        rec.otp_used = True
        db.session.commit()
        return jsonify({"error": "Code expired — please request a new one"}), 400

    if rec.otp_code != code:
        return jsonify({"error": "Invalid code — please try again"}), 400

    rec.enabled  = True
    rec.otp_used = True
    db.session.commit()

    log_security_event("EMAIL_OTP_ENABLED", username=current_user.username)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Disable email OTP
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/disable", methods=["POST"])
@login_required
def disable_email_otp():
    data     = request.json or {}
    password = data.get("password", "")

    if not current_user.password_hash or not check_password_hash(current_user.password_hash, password):
        return jsonify({"error": "Invalid password"}), 401

    rec = EmailOTP.query.filter_by(user_id=current_user.id).first()
    if rec:
        db.session.delete(rec)
        db.session.commit()

    log_security_event("EMAIL_OTP_DISABLED", username=current_user.username)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Forced-setup fallback: send + verify (for users without TOTP app)
# ---------------------------------------------------------------------------

@email_otp_bp.route("/api/2fa/email-otp/send-forced", methods=["POST"])
@login_required
def send_forced_otp():
    """Called from the forced-setup page when user clicks 'I can't use TOTP'."""
    if not current_user.email:
        return jsonify({
            "error": "No email on file. Ask your admin to add an email address to your account."
        }), 400

    rec = _get_or_create_email_otp(current_user.id)
    otp = _generate_otp()
    rec.otp_code   = otp
    rec.otp_expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    rec.otp_used   = False
    db.session.commit()

    sent = _send_otp_email(current_user, otp)
    if sent:
        return jsonify({"success": True})
    return jsonify({"error": "Failed to send email — contact your administrator"}), 500


@email_otp_bp.route("/api/2fa/email-otp/verify-forced", methods=["POST"])
@login_required
def verify_forced_otp():
    """Verify code entered during forced setup and mark email OTP as the user's 2FA."""
    data = request.json or {}
    code = (data.get("code") or "").strip()

    rec = EmailOTP.query.filter_by(user_id=current_user.id).first()
    if not rec or rec.otp_used or not rec.otp_code:
        return jsonify({"error": "No active code — please request a new one"}), 400

    if datetime.utcnow() > rec.otp_expiry:
        rec.otp_used = True
        db.session.commit()
        return jsonify({"error": "Code expired — please request a new one"}), 400

    if rec.otp_code != code:
        return jsonify({"error": "Invalid code"}), 400

    rec.enabled  = True
    rec.otp_used = True
    # Clear the force-2FA flag
    current_user.force_2fa_setup = False
    session.pop("force_2fa_setup", None)
    db.session.commit()

    log_security_event("EMAIL_OTP_FORCED_SETUP_COMPLETE", username=current_user.username)
    return jsonify({"success": True, "redirect": url_for("crew.dashboard")})