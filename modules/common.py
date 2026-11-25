"""Helpers shared by every blueprint."""
from functools import wraps

from flask import abort, redirect, request, session, url_for

import db


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = session.get("user")
            if not user:
                return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
            if user["role"] not in roles:
                abort(403)
            if user.get("must_change") and request.endpoint not in ("portal.account", "logout"):
                return redirect(url_for("portal.account"))
            return view(*args, **kwargs)
        return wrapper
    return decorator


def db_message(err):
    """Friendly text for a MySQL error (trigger/procedure messages are already readable)."""
    return getattr(err, "msg", None) or str(err)


def instructor_offering_or_403(oid):
    """The offering row, if the logged-in instructor teaches it (admins pass too)."""
    user = session["user"]
    if user["role"] == "admin":
        row = db.query("SELECT o.* FROM course_offering o WHERE o.offering_id = %s", (oid,), one=True)
    else:
        row = db.query(
            """SELECT o.* FROM course_offering o
                 JOIN offering_instructor oi ON oi.offering_id = o.offering_id
                WHERE o.offering_id = %s AND oi.instructor_id = %s""",
            (oid, user["instructor_id"]), one=True)
    if not row:
        abort(403)
    return row


def student_enrollment_or_403(eid):
    row = db.query("SELECT * FROM enrollment WHERE enrollment_id = %s AND student_id = %s",
                   (eid, session["user"]["student_id"]), one=True)
    if not row:
        abort(403)
    return row


def current_term():
    return db.query("SELECT * FROM academic_term WHERE is_current ORDER BY start_date DESC LIMIT 1", one=True)
