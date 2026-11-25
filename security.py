"""Web-layer security: CSRF tokens, security headers, login throttling, safe redirects."""
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlparse

from flask import abort, g, request, session
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

import db
from config import Config

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip():
    return request.remote_addr or "0.0.0.0"


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def is_safe_next(target):
    """Only follow redirects that stay on this site."""
    if not target:
        return False
    parts = urlparse(target)
    return not parts.scheme and not parts.netloc and target.startswith("/") and not target.startswith("//")


def login_blocked(username, ip):
    """True when this username or this address failed too often recently."""
    row = db.query(
        """SELECT SUM(username = %s) AS by_user, SUM(ip_address = %s) AS by_ip
             FROM login_attempt
            WHERE success = 0 AND attempted_at > NOW() - INTERVAL %s MINUTE
              AND (username = %s OR ip_address = %s)""",
        (username, ip, Config.LOGIN_WINDOW_MIN, username, ip), one=True)
    return (row["by_user"] or 0) >= Config.LOGIN_MAX_FAILS or (row["by_ip"] or 0) >= Config.LOGIN_MAX_FAILS * 4


def record_login(username, ip, success):
    db.execute("INSERT INTO login_attempt (username, ip_address, success) VALUES (%s, %s, %s)",
               (username[:50], ip, bool(success)))
    if success:   # a good login clears the failure count for that name
        db.execute("DELETE FROM login_attempt WHERE username = %s AND success = 0", (username[:50],))


def init_security(app):
    if Config.BEHIND_PROXY:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=Config.SESSION_HOURS),
        MAX_CONTENT_LENGTH=Config.MAX_UPLOAD_MB * 1024 * 1024,
    )

    @app.before_request
    def _guard():
        g.csp_nonce = secrets.token_urlsafe(16)
        if request.method not in SAFE_METHODS:
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
            expected = session.get("_csrf")
            if not expected or not sent or not hmac.compare_digest(sent, expected):
                abort(400, description="Your form expired or was tampered with. Reload the page and try again.")

    @app.after_request
    def _headers(resp):
        nonce = getattr(g, "csp_nonce", "")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'nonce-{nonce}'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.path.startswith(("/student", "/instructor", "/admin", "/account")):
            resp.headers["Cache-Control"] = "no-store"
        if Config.COOKIE_SECURE:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    @app.context_processor
    def _inject():
        return {
            "csrf_token": csrf_token,
            "csrf_field": lambda: Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'),
            "csp_nonce": lambda: getattr(g, "csp_nonce", ""),
        }
