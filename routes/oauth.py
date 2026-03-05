"""
routes/oauth.py
===============
Google OAuth login and account linking (Authlib + PKCE).
"""

import os
from datetime import datetime, timezone
from flask import Blueprint, redirect, url_for, flash, request, session
from flask_login import login_user, login_required, current_user

from extensions import db, oauth
from models import User, OAuthConnection, TwoFactorAuth
from utils import log_security_event

oauth_bp = Blueprint("oauth", __name__)

GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:5001/auth/google/callback"
)


def _convert_expires_at(token):
    """Convert Authlib's UNIX timestamp to Python datetime."""
    expires_at = token.get("expires_at")
    if expires_at:
        return datetime.fromtimestamp(expires_at, tz=timezone.utc)
    return None


@oauth_bp.route("/auth/google")
def google_login():
    if not oauth.google.client_id or not oauth.google.client_secret:
        flash("Google OAuth is not configured")
        return redirect(url_for("auth.login"))

    return oauth.google.authorize_redirect(GOOGLE_REDIRECT_URI)


@oauth_bp.route("/auth/google/link")
@login_required
def google_link_initiate():
    existing = OAuthConnection.query.filter_by(
        user_id=current_user.id, provider="google"
    ).first()

    if existing:
        flash("Google account already linked. Unlink it first to link a different account.")
        return redirect(url_for("tfa.security_settings"))

    return redirect(url_for("oauth.google_login"))


@oauth_bp.route("/auth/google/callback")
def google_callback():
    if not oauth.google.client_id or not oauth.google.client_secret:
        flash("Google OAuth is not configured")
        return redirect(url_for("auth.login"))

    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo")

        if not userinfo:
            flash("Google login failed: No user info received")
            return redirect(url_for("auth.login"))

        google_user_id = userinfo["sub"]
        email = userinfo.get("email")
        is_linking = current_user.is_authenticated

        # Convert UNIX timestamp → datetime
        expires_at = _convert_expires_at(token)

        # -----------------------
        # Linking flow
        # -----------------------
        if is_linking:
            existing = OAuthConnection.query.filter_by(
                provider="google", provider_user_id=google_user_id
            ).first()

            if existing:
                msg = (
                    "This Google account is already linked to your account"
                    if existing.user_id == current_user.id
                    else "This Google account is already linked to another account"
                )
                flash(msg)
                return redirect(url_for("profile.settings_page"))

            conn = OAuthConnection(
                user_id=current_user.id,
                provider="google",
                provider_user_id=google_user_id,
                email=email,
                access_token=token["access_token"],
                refresh_token=token.get("refresh_token"),
                token_expiry=expires_at,
                last_login=datetime.utcnow(),
            )
            db.session.add(conn)
            db.session.commit()

            log_security_event("GOOGLE_LINK", username=current_user.username)
            flash("Google account linked successfully!")
            return redirect(url_for("profile.settings_page"))

        # -----------------------
        # Login flow
        # -----------------------
        conn = OAuthConnection.query.filter_by(
            provider="google", provider_user_id=google_user_id
        ).first()

        if conn:
            user = conn.user
            conn.access_token = token["access_token"]
            conn.refresh_token = token.get("refresh_token")
            conn.token_expiry = expires_at
            conn.last_login = datetime.utcnow()
            db.session.commit()

            tfa = TwoFactorAuth.query.filter_by(user_id=user.id).first()
            skip_2fa = getattr(user, "skip_2fa_for_oauth", False)

            if tfa and tfa.enabled and not skip_2fa:
                session["pending_2fa_user_id"] = user.id
                session["pending_2fa_remember"] = False
                return redirect(url_for("tfa.totp_verify_page"))

            login_user(user, remember=False)
            log_security_event("GOOGLE_LOGIN", username=user.username)
            flash(f"Welcome back, {user.username}!")
            return redirect(url_for("cast.cast_events") if user.is_cast else url_for("crew.dashboard"))

        # -----------------------
        # Email match fallback
        # -----------------------
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            conn = OAuthConnection(
                user_id=existing_user.id,
                provider="google",
                provider_user_id=google_user_id,
                email=email,
                access_token=token["access_token"],
                refresh_token=token.get("refresh_token"),
                token_expiry=expires_at,
                last_login=datetime.utcnow(),
            )
            db.session.add(conn)
            db.session.commit()

            login_user(existing_user, remember=False)
            log_security_event("GOOGLE_LOGIN", username=existing_user.username)
            flash(f"Google account linked and signed in, {existing_user.username}!")
            return redirect(url_for("cast.cast_events") if existing_user.is_cast else url_for("crew.dashboard"))

        flash("No ShowWise account found for that Google account. Sign up first, then link Google from settings.")
        return redirect(url_for("auth.login"))

    except Exception as exc:
        flash(f"Google login failed: {str(exc)[:100]}")
        return redirect(url_for("auth.login"))
