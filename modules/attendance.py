"""Attendance: rotating-QR marking, the student Attendance tab (overall + day-wise),
instructor and admin overviews.

How the QR works
  * The instructor opens a window for today's class (sp_open_qr_window) and the database stores a
    random secret for that class. The secret never leaves the server.
  * Every 30 seconds the page shows a new 6-digit code = HMAC(secret, class, time-step).
    The QR holds a link containing that code; people far from the screen cannot reuse an old one.
  * The student scans (or types the code) while logged in. The app checks the code, the optional
    network allow-list and a failure throttle, then sp_mark_attendance_qr records present or late.
"""
import calendar
import hashlib
import hmac
import io
import ipaddress
import time
from datetime import date, datetime, timedelta
from math import ceil, floor

import mysql.connector
import qrcode
import qrcode.image.svg
from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

import db
from charts import column_chart, donut_chart, line_chart
from config import Config
from modules.common import db_message, instructor_offering_or_403, role_required

bp = Blueprint("attendance", __name__)
STEP = Config.QR_STEP_SECONDS


# ------------------------------------------------------------ code logic --
def code_for(secret, session_id, step):
    mac = hmac.new(secret.encode(), f"{session_id}:{step}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:4], 'big') % 1_000_000:06d}"


def current_step(now=None):
    return int((now or time.time()) // STEP)


def code_is_valid(secret, session_id, code, now=None):
    """Accepts the current and the previous time-step so a scan that straddles a refresh still works."""
    code = (code or "").replace(" ", "").strip()
    step = current_step(now)
    return any(hmac.compare_digest(code, code_for(secret, session_id, s)) for s in (step, step - 1))


def allowed_network():
    nets = Config.QR_ALLOWED_NETWORKS
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(request.remote_addr)
        return any(addr in ipaddress.ip_network(n, strict=False) for n in nets)
    except ValueError:
        return False


def log_scan(session_id, student_id, outcome):
    try:
        db.execute("""INSERT INTO attendance_scan_log (session_id, student_id, outcome, ip_address)
                      VALUES (%s, %s, %s, %s)""",
                   (session_id, student_id, outcome, (request.remote_addr or "")[:45]))
    except mysql.connector.Error:
        pass


def mark_by_code(sid, code, student_id):
    """Returns (ok, message). Everything that can go wrong is logged in attendance_scan_log."""
    if not allowed_network():
        log_scan(sid, student_id, "wrong_network")
        return False, "Attendance can only be marked from the campus network."
    fails = db.query("""SELECT COUNT(*) AS n FROM attendance_scan_log
                         WHERE student_id = %s AND outcome = 'bad_code'
                           AND scanned_at > NOW() - INTERVAL 10 MINUTE""", (student_id,), one=True)["n"]
    if fails >= 8:
        log_scan(sid, student_id, "blocked")
        return False, "Too many wrong codes. Wait a few minutes and try again."
    w = db.query("SELECT * FROM qr_window WHERE session_id = %s AND closes_at >= NOW()", (sid,), one=True)
    if not w:
        log_scan(sid, student_id, "closed")
        return False, "Attendance is not open for this class."
    if not code_is_valid(w["secret"], sid, code):
        log_scan(sid, student_id, "bad_code")
        return False, "That code is not valid or has expired. Scan the screen again."
    try:
        rows = db.call("sp_mark_attendance_qr", (sid, student_id))
        status = rows[0][0]["status"]
        log_scan(sid, student_id, "ok")
        return True, f"Attendance marked: {status}."
    except mysql.connector.Error as err:
        log_scan(sid, student_id, "rejected")
        return False, db_message(err)


# ----------------------------------------------------- instructor screens --
def session_for_instructor(sid):
    cs = db.query("""SELECT cs.*, c.course_code, c.title, o.section_code
                       FROM class_session cs JOIN course_offering o ON o.offering_id = cs.offering_id
                       JOIN course c ON c.course_id = o.course_id WHERE cs.session_id = %s""", (sid,), one=True)
    if not cs:
        abort(404)
    instructor_offering_or_403(cs["offering_id"])
    return cs


@bp.get("/instructor/session/<int:sid>/qr")
@role_required("instructor", "admin")
def qr_page(sid):
    cs = session_for_instructor(sid)
    window = db.query("SELECT *, closes_at >= NOW() AS is_open FROM qr_window WHERE session_id = %s", (sid,), one=True)
    return render_template("qr_session.html", cs=cs, window=window, step=STEP,
                           is_today=cs["session_date"] == date.today())


@bp.post("/instructor/session/<int:sid>/qr/open")
@role_required("instructor", "admin")
def qr_open(sid):
    cs = session_for_instructor(sid)
    inst = session["user"]["instructor_id"] or db.query(
        "SELECT instructor_id FROM offering_instructor WHERE offering_id = %s LIMIT 1",
        (cs["offering_id"],), one=True)["instructor_id"]
    try:
        db.call("sp_open_qr_window", (sid, inst, request.form.get("minutes", 20, type=int),
                                      request.form.get("late_after", 10, type=int)))
        flash("QR attendance is open.", "success")
    except mysql.connector.Error as err:
        flash(db_message(err), "error")
    return redirect(url_for("attendance.qr_page", sid=sid))


@bp.post("/instructor/session/<int:sid>/qr/close")
@role_required("instructor", "admin")
def qr_close(sid):
    cs = session_for_instructor(sid)
    inst = session["user"]["instructor_id"] or db.query(
        "SELECT instructor_id FROM offering_instructor WHERE offering_id = %s LIMIT 1",
        (cs["offering_id"],), one=True)["instructor_id"]
    db.call("sp_close_qr_window", (sid, inst))
    if request.form.get("finish"):
        try:
            n = db.call("sp_finish_session_attendance", (sid, inst))[0][0]["marked_absent"]
            flash(f"Window closed. {n} students without a scan were marked absent.", "success")
        except mysql.connector.Error as err:
            flash(db_message(err), "error")
    else:
        flash("QR attendance closed.", "success")
    return redirect(url_for("attendance.qr_page", sid=sid))


@bp.get("/instructor/session/<int:sid>/qr/state")
@role_required("instructor", "admin")
def qr_state(sid):
    session_for_instructor(sid)
    w = db.query("""SELECT secret, TIMESTAMPDIFF(SECOND, NOW(), closes_at) AS closes_in,
                           TIMESTAMPDIFF(SECOND, NOW(), late_after) AS late_in
                      FROM qr_window WHERE session_id = %s""", (sid,), one=True)
    counts = db.query("""SELECT SUM(status = 'present') AS present, SUM(status = 'late') AS late,
                                SUM(marked_via = 'qr') AS by_qr,
                                (SELECT COUNT(*) FROM enrollment e JOIN class_session cs ON cs.offering_id = e.offering_id
                                  WHERE cs.session_id = %s AND e.status = 'enrolled') AS enrolled
                           FROM attendance WHERE session_id = %s""", (sid, sid), one=True)
    recent = db.query("""SELECT s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS name, a.status,
                                CAST(TIME(a.marked_at) AS CHAR) AS at
                           FROM attendance a JOIN enrollment e ON e.enrollment_id = a.enrollment_id
                           JOIN student s ON s.student_id = e.student_id
                          WHERE a.session_id = %s AND a.marked_via = 'qr' ORDER BY a.marked_at DESC LIMIT 12""", (sid,))
    state = {"open": bool(w and w["closes_in"] >= 0), "step": STEP,
             "present": int(counts["present"] or 0), "late": int(counts["late"] or 0),
             "enrolled": int(counts["enrolled"] or 0), "recent": recent}
    if state["open"]:
        step = current_step()
        state.update(code=code_for(w["secret"], sid, step), step_id=step,
                     next_in=STEP - int(time.time() % STEP), closes_in=w["closes_in"], late_in=max(w["late_in"], 0))
    return jsonify(state)


@bp.get("/instructor/session/<int:sid>/qr.svg")
@role_required("instructor", "admin")
def qr_svg(sid):
    session_for_instructor(sid)
    w = db.query("SELECT secret FROM qr_window WHERE session_id = %s AND closes_at >= NOW()", (sid,), one=True)
    if not w:
        abort(404)
    base = Config.PUBLIC_BASE_URL or request.host_url.rstrip("/")
    url = f"{base}/attend/{sid}/{code_for(w['secret'], sid, current_step())}"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    resp = Response(buf.getvalue(), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/instructor/attendance")
@role_required("instructor")
def instructor_overview():
    iid = session["user"]["instructor_id"]
    offerings = db.query(
        """SELECT o.offering_id, c.course_code, c.title, o.section_code,
                  (SELECT COUNT(*) FROM enrollment e WHERE e.offering_id = o.offering_id AND e.status = 'enrolled') AS students,
                  (SELECT COUNT(*) FROM class_session cs WHERE cs.offering_id = o.offering_id AND cs.session_date <= CURDATE()) AS held,
                  (SELECT ROUND(100 * SUM(a.status IN ('present','late')) / NULLIF(SUM(a.status <> 'excused'), 0), 1)
                     FROM attendance a JOIN enrollment e ON e.enrollment_id = a.enrollment_id
                    WHERE e.offering_id = o.offering_id) AS pct
             FROM course_offering o JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id
             JOIN offering_instructor oi ON oi.offering_id = o.offering_id AND oi.instructor_id = %s
            WHERE t.is_current ORDER BY c.course_code, o.section_code""", (iid,))
    today = db.query(
        """SELECT cs.session_id, cs.start_time, cs.end_time, cs.topic, c.course_code, o.section_code,
                  w.closes_at >= NOW() AS qr_open,
                  (SELECT COUNT(*) FROM attendance a WHERE a.session_id = cs.session_id) AS marked
             FROM class_session cs JOIN course_offering o ON o.offering_id = cs.offering_id
             JOIN course c ON c.course_id = o.course_id
             JOIN offering_instructor oi ON oi.offering_id = o.offering_id AND oi.instructor_id = %s
             LEFT JOIN qr_window w ON w.session_id = cs.session_id
            WHERE cs.session_date = CURDATE() ORDER BY cs.start_time""", (iid,))
    return render_template("instructor_attendance_overview.html", offerings=offerings, today=today)


# --------------------------------------------------------- student screens --
@bp.get("/attend/<int:sid>/<code>")
@role_required("student")
def attend_confirm(sid, code):
    cs = db.query("""SELECT cs.session_id, cs.session_date, cs.start_time, cs.end_time, c.course_code, c.title
                       FROM class_session cs JOIN course_offering o ON o.offering_id = cs.offering_id
                       JOIN course c ON c.course_id = o.course_id WHERE cs.session_id = %s""", (sid,), one=True)
    if not cs:
        abort(404)
    return render_template("attend_confirm.html", cs=cs, code=code)


@bp.post("/student/attendance/mark")
@role_required("student")
def mark():
    sid = request.form.get("session_id", type=int)
    ok, msg = mark_by_code(sid, request.form.get("code", ""), session["user"]["student_id"])
    flash(msg, "success" if ok else "error")
    return redirect(url_for("attendance.student_tab") if ok else url_for("attendance.scan"))


@bp.get("/student/scan")
@role_required("student")
def scan():
    open_now = db.query(
        """SELECT cs.session_id, cs.start_time, cs.end_time, c.course_code, c.title,
                  TIMESTAMPDIFF(MINUTE, NOW(), w.closes_at) AS minutes_left, a.status AS my_status
             FROM enrollment e JOIN class_session cs ON cs.offering_id = e.offering_id
             JOIN qr_window w ON w.session_id = cs.session_id AND w.closes_at >= NOW()
             JOIN course_offering o ON o.offering_id = e.offering_id
             JOIN course c ON c.course_id = o.course_id
             LEFT JOIN attendance a ON a.session_id = cs.session_id AND a.enrollment_id = e.enrollment_id
            WHERE e.student_id = %s AND e.status = 'enrolled' ORDER BY cs.start_time""",
        (session["user"]["student_id"],))
    return render_template("student_scan.html", open_now=open_now)


def needed_or_spare(attended, counted, threshold):
    """Classes to attend in a row to reach the threshold, or classes that can still be missed."""
    th = threshold / 100
    if counted == 0:
        return None
    if attended / counted < th:
        return {"need": max(0, ceil((th * counted - attended) / (1 - th)))}
    return {"spare": max(0, floor(attended / th - counted))}


@bp.get("/student/attendance")
@role_required("student")
def student_tab():
    sid = session["user"]["student_id"]
    view = request.args.get("view", "overall")
    th = Config.ATTENDANCE_THRESHOLD
    rows = db.query(
        """SELECT d.enrollment_id, d.course_code, d.course_title,
                  SUM(d.status = 'present') AS present, SUM(d.status = 'late') AS late,
                  SUM(d.status = 'absent') AS absent, SUM(d.status = 'excused') AS excused,
                  SUM(d.status IS NULL) AS unmarked, COUNT(*) AS held
             FROM v_attendance_detail d
             JOIN enrollment e ON e.enrollment_id = d.enrollment_id AND e.status = 'enrolled'
            WHERE d.student_id = %s AND d.session_date <= CURDATE()
            GROUP BY d.enrollment_id, d.course_code, d.course_title ORDER BY d.course_code""", (sid,))
    tot = {k: 0 for k in ("present", "late", "absent", "excused", "unmarked")}
    for r in rows:
        for k in tot:
            r[k] = int(r[k] or 0)
            tot[k] += r[k]
        attended, counted = r["present"] + r["late"], r["present"] + r["late"] + r["absent"]
        r["pct"] = round(100 * attended / counted, 1) if counted else None
        r["advice"] = needed_or_spare(attended, counted, th)
    counted_all = tot["present"] + tot["late"] + tot["absent"]
    overall = round(100 * (tot["present"] + tot["late"]) / counted_all, 1) if counted_all else None
    charts, cal, days, month = {}, None, [], None
    if view == "overall":
        if rows:
            charts["donut"] = donut_chart(["Present", "Late", "Absent", "Excused"],
                                          [tot["present"], tot["late"], tot["absent"], tot["excused"]],
                                          colors=["var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"],
                                          center_big=f"{overall}%" if overall is not None else "-", center_small="overall")
            charts["by_course"] = column_chart([r["course_code"] for r in rows], [float(r["pct"] or 0) for r in rows],
                                               colors=["var(--c5)" if (r["pct"] or 0) < th else "var(--c3)" for r in rows], unit="%")
            monthly = db.query(
                """SELECT DATE_FORMAT(session_date, '%%b %%Y') AS m, DATE_FORMAT(session_date, '%%Y-%%m') AS k,
                          ROUND(100 * SUM(status IN ('present','late')) / NULLIF(SUM(status IN ('present','late','absent')), 0), 1) AS pct
                     FROM v_attendance_detail WHERE student_id = %s AND session_date <= CURDATE()
                    GROUP BY k, m ORDER BY k""", (sid,))
            monthly = [m for m in monthly if m["pct"] is not None]
            if len(monthly) > 1:
                charts["trend"] = line_chart([m["m"] for m in monthly], [float(m["pct"]) for m in monthly])
    else:
        try:
            y, m = map(int, request.args.get("month", date.today().strftime("%Y-%m")).split("-"))
            first = date(y, m, 1)
        except ValueError:
            first = date.today().replace(day=1)
        last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
        month = {"label": first.strftime("%B %Y"), "key": first.strftime("%Y-%m"),
                 "prev": (first - timedelta(days=1)).strftime("%Y-%m"),
                 "next": (last + timedelta(days=1)).strftime("%Y-%m")}
        days_rows = db.query(
            """SELECT session_date, start_time, end_time, course_code, course_title, topic, status, marked_via,
                      DATE_FORMAT(marked_at, '%%H:%%i') AS marked_time
                 FROM v_attendance_detail WHERE student_id = %s AND session_date BETWEEN %s AND %s
                ORDER BY session_date, start_time""", (sid, first, last))
        hol = {h["holiday_date"]: h["name"] for h in db.query(
            "SELECT holiday_date, name FROM holiday WHERE holiday_date BETWEEN %s AND %s", (first, last))}
        by_day = {}
        for r in days_rows:
            by_day.setdefault(r["session_date"], []).append(r)
        cal = []
        for week in calendar.Calendar(0).monthdatescalendar(first.year, first.month):
            cells = []
            for d in week:
                items = by_day.get(d, [])
                cls = "out" if d.month != first.month else ""
                if d in hol:
                    cls += " hol"
                elif items:
                    st = [i["status"] for i in items]
                    if d > date.today():
                        cls += " future"
                    elif all(s in ("present", "late") for s in st):
                        cls += " good"
                    elif all(s == "absent" for s in st):
                        cls += " bad"
                    elif any(s is None for s in st):
                        cls += " pending"
                    else:
                        cls += " mixed"
                cells.append({"date": d, "cls": cls.strip(), "n": len(items), "holiday": hol.get(d),
                              "tip": "; ".join(f"{i['course_code']} {i['status'] or 'not marked'}" for i in items)})
            cal.append(cells)
        days = sorted(by_day.items(), reverse=True)
    return render_template("student_attendance.html", view=view, rows=rows, tot=tot, overall=overall,
                           charts=charts, cal=cal, days=days, month=month, threshold=th, today=date.today())


# ------------------------------------------------------------ admin screen --
@bp.get("/admin/attendance")
@role_required("admin")
def admin_overview():
    th = Config.ATTENDANCE_THRESHOLD
    offerings = db.query(
        """SELECT o.offering_id, c.course_code, c.title, o.section_code,
                  COUNT(DISTINCT e.enrollment_id) AS students,
                  COUNT(a.session_id) AS marks,
                  ROUND(100 * SUM(a.status IN ('present','late')) / NULLIF(SUM(a.status <> 'excused'), 0), 1) AS pct,
                  ROUND(100 * SUM(a.marked_via = 'qr') / NULLIF(COUNT(a.session_id), 0), 1) AS qr_share
             FROM course_offering o JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
             LEFT JOIN enrollment e ON e.offering_id = o.offering_id AND e.status = 'enrolled'
             LEFT JOIN attendance a ON a.enrollment_id = e.enrollment_id
            GROUP BY o.offering_id, c.course_code, c.title, o.section_code ORDER BY pct IS NULL, pct, c.course_code""")
    shortage = db.query(
        """SELECT COUNT(*) AS n FROM (SELECT e.enrollment_id
                 FROM enrollment e JOIN attendance a ON a.enrollment_id = e.enrollment_id
                WHERE e.status = 'enrolled' GROUP BY e.enrollment_id
               HAVING 100 * SUM(a.status IN ('present','late')) / NULLIF(SUM(a.status <> 'excused'), 0) < %s) x""",
        (th,), one=True)["n"]
    methods = db.query("SELECT marked_via, COUNT(*) AS n FROM attendance GROUP BY marked_via")
    scans = db.query("""SELECT outcome, COUNT(*) AS n FROM attendance_scan_log
                         WHERE scanned_at >= CURDATE() GROUP BY outcome ORDER BY n DESC""")
    charts = {}
    if methods:
        charts["methods"] = donut_chart([m["marked_via"] for m in methods], [m["n"] for m in methods],
                                        colors=["var(--c1)", "var(--c3)", "var(--c6)"], center_big=str(sum(m["n"] for m in methods)),
                                        center_small="marks")
    return render_template("admin_attendance.html", offerings=offerings, shortage=shortage, scans=scans,
                           charts=charts, threshold=th)
