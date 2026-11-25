"""Student-portal style modules: notifications, timetable, holidays, feedback, service requests,
fees, mentorship, assessments, course registration, account security, admin user tools, audit log."""
import re
import secrets
from datetime import date, datetime, time, timedelta

import mysql.connector
from flask import (Blueprint, abort, flash, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
from charts import column_chart, donut_chart
from modules.common import (current_term, db_message, instructor_offering_or_403, role_required,
                            student_enrollment_or_403)

bp = Blueprint("portal", __name__)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------- notifications --
def _visible(user):
    """SQL condition + params selecting the notifications this user may see."""
    role = user["role"]
    if role == "student":
        return ("(n.audience IN ('all', 'students') OR (n.audience = 'student' AND n.student_id = %s) "
                "OR (n.audience = 'offering' AND n.offering_id IN "
                "(SELECT offering_id FROM enrollment WHERE student_id = %s AND status = 'enrolled')))",
                (user["student_id"], user["student_id"]))
    if role == "instructor":
        return ("(n.audience IN ('all', 'instructors') OR (n.audience = 'offering' AND n.offering_id IN "
                "(SELECT offering_id FROM offering_instructor WHERE instructor_id = %s)))", (user["instructor_id"],))
    return ("(n.audience IN ('all', 'instructors', 'students'))", ())


@bp.app_context_processor
def _unread():
    user = session.get("user")
    if not user:
        return {"unread_count": 0}
    cond, params = _visible(user)
    try:
        n = db.query(f"""SELECT COUNT(*) AS n FROM notification n
                          WHERE n.created_at > NOW() - INTERVAL 90 DAY AND {cond}
                            AND NOT EXISTS (SELECT 1 FROM notification_read r
                                             WHERE r.user_id = %s AND r.notification_id = n.notification_id)""",
                     params + (user["user_id"],), one=True)["n"]
    except mysql.connector.Error:
        n = 0
    return {"unread_count": n}


@bp.get("/notifications")
@role_required("student", "instructor", "admin")
def notifications():
    user = session["user"]
    cond, params = _visible(user)
    items = db.query(
        f"""SELECT n.notification_id, n.title, n.body, n.category, n.created_at, n.audience, c.course_code,
                   r.read_at IS NOT NULL AS is_read
              FROM notification n
              LEFT JOIN course_offering o ON o.offering_id = n.offering_id
              LEFT JOIN course c ON c.course_id = o.course_id
              LEFT JOIN notification_read r ON r.notification_id = n.notification_id AND r.user_id = %s
             WHERE n.created_at > NOW() - INTERVAL 90 DAY AND {cond}
             ORDER BY n.created_at DESC, n.notification_id DESC LIMIT 100""", (user["user_id"],) + params)
    return render_template("notifications.html", items=items)


@bp.post("/notifications/read")
@role_required("student", "instructor", "admin")
def notifications_read():
    user = session["user"]
    cond, params = _visible(user)
    one = request.form.get("id", type=int)
    extra, eparams = ("AND n.notification_id = %s", (one,)) if one else ("", ())
    db.execute(f"""INSERT IGNORE INTO notification_read (user_id, notification_id)
                   SELECT %s, n.notification_id FROM notification n
                    WHERE n.created_at > NOW() - INTERVAL 90 DAY AND {cond} {extra}""",
               (user["user_id"],) + params + eparams)
    return redirect(url_for("portal.notifications"))


@bp.route("/notifications/new", methods=["GET", "POST"])
@role_required("instructor", "admin")
def notify_new():
    user = session["user"]
    if user["role"] == "admin":
        offerings = db.query("""SELECT o.offering_id, c.course_code, o.section_code FROM course_offering o
                                JOIN course c ON c.course_id = o.course_id JOIN academic_term t ON t.term_id = o.term_id
                               WHERE t.is_current ORDER BY c.course_code, o.section_code""")
    else:
        offerings = db.query("""SELECT o.offering_id, c.course_code, o.section_code FROM course_offering o
                                JOIN course c ON c.course_id = o.course_id JOIN academic_term t ON t.term_id = o.term_id
                                JOIN offering_instructor oi ON oi.offering_id = o.offering_id AND oi.instructor_id = %s
                               WHERE t.is_current ORDER BY c.course_code, o.section_code""", (user["instructor_id"],))
    if request.method == "POST":
        f = request.form
        audience = f.get("audience", "offering")
        oid = f.get("offering_id", type=int) if audience == "offering" else None
        if user["role"] == "instructor" and (audience != "offering" or oid not in {o["offering_id"] for o in offerings}):
            abort(403)
        if not f.get("title", "").strip():
            flash("A notice needs a title.", "error")
        else:
            db.execute("""INSERT INTO notification (audience, offering_id, category, title, body, created_by_user)
                          VALUES (%s, %s, %s, %s, %s, %s)""",
                       (audience, oid, f.get("category", "general"), f["title"].strip()[:150],
                        f.get("body", "").strip()[:2000] or None, user["user_id"]))
            flash("Notice sent.", "success")
            return redirect(url_for("portal.notifications"))
    return render_template("notify_new.html", offerings=offerings)


# -------------------------------------------------------------- timetable --
def _grid(rows):
    by_day = {d: [] for d in range(1, 8)}
    for r in rows:
        by_day[r["day_of_week"]].append(r)
    show = [d for d in range(1, 6)] + [d for d in (6, 7) if by_day[d]]
    return [(d, DAYS[d - 1], by_day[d]) for d in show]


@bp.get("/student/timetable")
@role_required("student")
def student_timetable():
    rows = db.query(
        """SELECT ts.*, c.course_code, c.title, o.section_code,
                  (SELECT CONCAT(i.first_name, ' ', i.last_name) FROM offering_instructor oi
                     JOIN instructor i ON i.instructor_id = oi.instructor_id
                    WHERE oi.offering_id = o.offering_id AND oi.role = 'primary' LIMIT 1) AS teacher
             FROM enrollment e JOIN timetable_slot ts ON ts.offering_id = e.offering_id
             JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
            WHERE e.student_id = %s AND e.status = 'enrolled' ORDER BY ts.day_of_week, ts.start_time""",
        (session["user"]["student_id"],))
    return render_template("timetable.html", grid=_grid(rows), today=date.today().isoweekday(), who="student")


@bp.get("/instructor/timetable")
@role_required("instructor")
def instructor_timetable():
    rows = db.query(
        """SELECT ts.*, c.course_code, c.title, o.section_code, NULL AS teacher
             FROM offering_instructor oi JOIN timetable_slot ts ON ts.offering_id = oi.offering_id
             JOIN course_offering o ON o.offering_id = oi.offering_id JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
            WHERE oi.instructor_id = %s ORDER BY ts.day_of_week, ts.start_time""", (session["user"]["instructor_id"],))
    return render_template("timetable.html", grid=_grid(rows), today=date.today().isoweekday(), who="instructor")


@bp.route("/admin/offerings/<int:oid>/timetable", methods=["GET", "POST"])
@role_required("admin")
def admin_timetable(oid):
    off = db.query("""SELECT o.*, c.course_code, c.title, t.start_date, t.end_date FROM course_offering o
                      JOIN course c ON c.course_id = o.course_id JOIN academic_term t ON t.term_id = o.term_id
                     WHERE o.offering_id = %s""", (oid,), one=True)
    if not off:
        abort(404)
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        try:
            if action == "add":
                clash = db.query(
                    """SELECT c.course_code FROM timetable_slot ts JOIN course_offering o ON o.offering_id = ts.offering_id
                       JOIN course c ON c.course_id = o.course_id
                      WHERE ts.room = %s AND ts.day_of_week = %s AND ts.start_time < %s AND ts.end_time > %s
                        AND o.term_id = %s""", (f["room"], f["day"], f["end_time"], f["start_time"], off["term_id"]), one=True)
                if clash:
                    raise ValueError(f"Room {f['room']} is already taken by {clash['course_code']} at that time.")
                db.execute("""INSERT INTO timetable_slot (offering_id, day_of_week, start_time, end_time, room, slot_type)
                              VALUES (%s, %s, %s, %s, %s, %s)""",
                           (oid, int(f["day"]), f["start_time"], f["end_time"], f["room"].strip()[:30], f["slot_type"]))
                flash("Slot added.", "success")
            elif action == "delete":
                db.execute("DELETE FROM timetable_slot WHERE slot_id = %s AND offering_id = %s", (f.get("slot_id", type=int), oid))
            elif action == "generate":
                made = db.call("sp_generate_sessions", (oid, f["from"], f["to"]))[0][0]["sessions_created"]
                flash(f"{made} class sessions created (holidays skipped).", "success")
        except (ValueError, mysql.connector.Error) as err:
            flash(db_message(err) if isinstance(err, mysql.connector.Error) else str(err), "error")
        return redirect(url_for("portal.admin_timetable", oid=oid))
    slots = db.query("SELECT * FROM timetable_slot WHERE offering_id = %s ORDER BY day_of_week, start_time", (oid,))
    return render_template("admin_timetable.html", off=off, slots=slots, days=DAYS)


# --------------------------------------------------------------- holidays --
@bp.get("/holidays")
@role_required("student", "instructor", "admin")
def holidays():
    rows = db.query("SELECT * FROM holiday WHERE holiday_date >= CURDATE() - INTERVAL 30 DAY ORDER BY holiday_date")
    return render_template("holidays.html", rows=rows, today=date.today())


@bp.post("/admin/holidays")
@role_required("admin")
def holidays_edit():
    f = request.form
    try:
        if f.get("action") == "delete":
            db.execute("DELETE FROM holiday WHERE holiday_id = %s", (f.get("holiday_id", type=int),))
        else:
            db.execute("INSERT INTO holiday (holiday_date, name, kind) VALUES (%s, %s, %s)",
                       (f["holiday_date"], f["name"].strip()[:100], f.get("kind", "public")))
            flash("Holiday added.", "success")
    except mysql.connector.Error as err:
        flash(db_message(err), "error")
    return redirect(url_for("portal.holidays"))


# --------------------------------------------------------------- feedback --
@bp.route("/student/feedback", methods=["GET", "POST"])
@role_required("student")
def student_feedback():
    sid = session["user"]["student_id"]
    if request.method == "POST":
        eid = request.form.get("enrollment_id", type=int)
        student_enrollment_or_403(eid)
        try:
            db.execute("""INSERT INTO course_feedback (enrollment_id, rating_content, rating_teaching, rating_assessment, comment)
                          VALUES (%s, %s, %s, %s, %s)""",
                       (eid, request.form["rating_content"], request.form["rating_teaching"],
                        request.form["rating_assessment"], request.form.get("comment", "").strip()[:1000] or None))
            flash("Thank you, your feedback was recorded anonymously for the instructor.", "success")
        except mysql.connector.IntegrityError:
            flash("You already gave feedback for this course.", "error")
        except mysql.connector.Error as err:
            flash(db_message(err), "error")
        return redirect(url_for("portal.student_feedback"))
    rows = db.query(
        """SELECT e.enrollment_id, c.course_code, c.title, f.submitted_on, f.rating_content, f.rating_teaching, f.rating_assessment
             FROM enrollment e JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
             LEFT JOIN course_feedback f ON f.enrollment_id = e.enrollment_id
            WHERE e.student_id = %s AND e.status = 'enrolled' ORDER BY c.course_code""", (sid,))
    return render_template("student_feedback.html", rows=rows)


@bp.get("/instructor/offering/<int:oid>/feedback")
@role_required("instructor", "admin")
def offering_feedback(oid):
    off = instructor_offering_or_403(oid)
    course = db.query("SELECT course_code, title FROM course WHERE course_id = %s", (off["course_id"],), one=True)
    avg = db.query("""SELECT COUNT(*) AS n, ROUND(AVG(rating_content), 2) AS content, ROUND(AVG(rating_teaching), 2) AS teaching,
                             ROUND(AVG(rating_assessment), 2) AS assessment
                        FROM course_feedback f JOIN enrollment e ON e.enrollment_id = f.enrollment_id
                       WHERE e.offering_id = %s""", (oid,), one=True)
    comments = db.query("""SELECT f.comment, f.submitted_on FROM course_feedback f JOIN enrollment e ON e.enrollment_id = f.enrollment_id
                            WHERE e.offering_id = %s AND f.comment IS NOT NULL ORDER BY f.submitted_on DESC LIMIT 50""", (oid,))
    chart = None
    if avg["n"]:
        chart = column_chart(["Content", "Teaching", "Assessment"], [float(avg["content"]), float(avg["teaching"]), float(avg["assessment"])],
                             colors=["var(--c1)", "var(--c3)", "var(--c6)"])
    return render_template("offering_feedback.html", off=off, course=course, avg=avg, comments=comments, chart=chart)


# --------------------------------------------------------------- requests --
CATEGORIES = [("grievance", "Grievance"), ("bonafide_certificate", "Bonafide certificate"), ("transcript", "Transcript"),
              ("id_card", "ID card"), ("fee_issue", "Fee issue"), ("attendance_correction", "Attendance correction"), ("other", "Other")]


@bp.route("/student/requests", methods=["GET", "POST"])
@role_required("student")
def student_requests():
    sid = session["user"]["student_id"]
    if request.method == "POST":
        f = request.form
        if f.get("category") not in dict(CATEGORIES) or not f.get("subject", "").strip():
            flash("Choose a category and write a subject.", "error")
        else:
            db.execute("INSERT INTO service_request (student_id, category, subject, description) VALUES (%s, %s, %s, %s)",
                       (sid, f["category"], f["subject"].strip()[:150], f.get("description", "").strip()[:3000] or None))
            flash("Request submitted. You will be notified when it is handled.", "success")
        return redirect(url_for("portal.student_requests"))
    rows = db.query("SELECT * FROM service_request WHERE student_id = %s ORDER BY created_on DESC", (sid,))
    return render_template("student_requests.html", rows=rows, categories=CATEGORIES)


@bp.route("/admin/requests", methods=["GET", "POST"])
@role_required("admin")
def admin_requests():
    if request.method == "POST":
        f = request.form
        rid = f.get("request_id", type=int)
        status = f.get("status")
        req = db.query("SELECT * FROM service_request WHERE request_id = %s", (rid,), one=True)
        if not req or status not in ("open", "in_progress", "resolved", "rejected"):
            abort(400)
        db.execute("""UPDATE service_request SET status = %s, response = %s, handled_by_user = %s,
                             resolved_on = IF(%s IN ('resolved', 'rejected'), NOW(), NULL) WHERE request_id = %s""",
                   (status, f.get("response", "").strip()[:2000] or None, session["user"]["user_id"], status, rid))
        db.execute("""INSERT INTO notification (audience, student_id, category, title, body, created_by_user)
                      VALUES ('student', %s, 'general', %s, %s, %s)""",
                   (req["student_id"], f"Request update: {req['subject'][:100]}",
                    f"Status: {status.replace('_', ' ')}. {f.get('response', '').strip()[:500]}", session["user"]["user_id"]))
        flash("Request updated and the student was notified.", "success")
        return redirect(url_for("portal.admin_requests", status=request.args.get("status", "")))
    status = request.args.get("status", "open")
    rows = db.query(
        """SELECT r.*, s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student FROM service_request r
             JOIN student s ON s.student_id = r.student_id WHERE (%s = 'all' OR r.status = %s)
            ORDER BY r.created_on DESC LIMIT 200""", (status, status))
    return render_template("admin_requests.html", rows=rows, status=status)


# ------------------------------------------------------------------- fees --
@bp.get("/student/fees")
@role_required("student")
def student_fees():
    sid = session["user"]["student_id"]
    invoices = db.query("""SELECT v.*, t.term_name FROM v_fee_invoice_status v JOIN academic_term t ON t.term_id = v.term_id
                            WHERE v.student_id = %s ORDER BY v.due_date DESC""", (sid,))
    payments = db.query("""SELECT p.*, i.description FROM fee_payment p JOIN fee_invoice i ON i.invoice_id = p.invoice_id
                            WHERE i.student_id = %s ORDER BY p.paid_on DESC""", (sid,))
    due = sum(float(i["balance"]) for i in invoices)
    return render_template("student_fees.html", invoices=invoices, payments=payments, due=due)


@bp.route("/admin/fees", methods=["GET", "POST"])
@role_required("admin")
def admin_fees():
    user = session["user"]
    if request.method == "POST":
        f = request.form
        try:
            if f.get("action") == "invoice":
                term = current_term()
                if f.get("scope") == "all":
                    n = db.execute_count("""INSERT INTO fee_invoice (student_id, term_id, description, amount, due_date)
                                            SELECT student_id, %s, %s, %s, %s FROM student WHERE status = 'active'""",
                                         (term["term_id"], f["description"].strip()[:150], f["amount"], f["due_date"]))
                else:
                    stu = db.query("SELECT student_id FROM student WHERE roll_number = %s", (f["roll"].strip(),), one=True)
                    if not stu:
                        raise ValueError("No student with that roll number.")
                    n = db.execute_count("""INSERT INTO fee_invoice (student_id, term_id, description, amount, due_date)
                                            VALUES (%s, %s, %s, %s, %s)""",
                                         (stu["student_id"], term["term_id"], f["description"].strip()[:150], f["amount"], f["due_date"]))
                flash(f"{n} invoice(s) created.", "success")
            elif f.get("action") == "payment":
                db.execute("""INSERT INTO fee_payment (invoice_id, amount, mode, reference_no, recorded_by_user)
                              VALUES (%s, %s, %s, %s, %s)""",
                           (f.get("invoice_id", type=int), f["amount"], f["mode"], f["reference_no"].strip()[:40], user["user_id"]))
                flash("Payment recorded.", "success")
        except (ValueError, mysql.connector.Error) as err:
            flash(db_message(err) if isinstance(err, mysql.connector.Error) else str(err), "error")
        return redirect(url_for("portal.admin_fees"))
    status = request.args.get("status", "outstanding")
    roll = request.args.get("roll", "").strip()
    rows = db.query(
        """SELECT v.*, s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student FROM v_fee_invoice_status v
             JOIN student s ON s.student_id = v.student_id
            WHERE (%s = 'all' OR (%s = 'outstanding' AND v.status <> 'paid') OR v.status = %s)
              AND (%s = '' OR s.roll_number = %s) ORDER BY v.due_date, s.roll_number LIMIT 200""",
        (status, status, status, roll, roll))
    totals = db.query("""SELECT COALESCE(SUM(amount), 0) AS billed, COALESCE(SUM(paid), 0) AS collected,
                                COALESCE(SUM(balance), 0) AS outstanding FROM v_fee_invoice_status""", one=True)
    return render_template("admin_fees.html", rows=rows, totals=totals, status=status, roll=roll)


# ------------------------------------------------------------- mentorship --
@bp.get("/student/mentor")
@role_required("student")
def student_mentor():
    m = db.query("""SELECT i.first_name, i.last_name, i.email, i.designation, mt.assigned_on FROM mentorship mt
                      JOIN instructor i ON i.instructor_id = mt.instructor_id WHERE mt.student_id = %s""",
                 (session["user"]["student_id"],), one=True)
    return render_template("student_mentor.html", m=m)


@bp.get("/instructor/mentees")
@role_required("instructor")
def instructor_mentees():
    rows = db.query(
        """SELECT s.student_id, s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student, s.email,
                  (SELECT ROUND(100 * SUM(a.status IN ('present','late')) / NULLIF(SUM(a.status <> 'excused'), 0), 1)
                     FROM attendance a JOIN enrollment e ON e.enrollment_id = a.enrollment_id WHERE e.student_id = s.student_id) AS attendance,
                  (SELECT COUNT(*) FROM service_request r WHERE r.student_id = s.student_id AND r.status IN ('open','in_progress')) AS open_requests
             FROM mentorship m JOIN student s ON s.student_id = m.student_id WHERE m.instructor_id = %s ORDER BY s.roll_number""",
        (session["user"]["instructor_id"],))
    return render_template("instructor_mentees.html", rows=rows)


@bp.route("/admin/mentorship", methods=["GET", "POST"])
@role_required("admin")
def admin_mentorship():
    if request.method == "POST":
        if request.form.get("action") == "auto":
            insts = [r["instructor_id"] for r in db.query(
                "SELECT instructor_id FROM instructor WHERE is_active AND designation <> 'Teaching Assistant' ORDER BY instructor_id")]
            studs = db.query("""SELECT student_id FROM student WHERE status = 'active'
                                   AND student_id NOT IN (SELECT student_id FROM mentorship) ORDER BY roll_number""")
            if insts and studs:
                with db.transaction() as cur:
                    for i, s in enumerate(studs):
                        cur.execute("INSERT INTO mentorship (student_id, instructor_id) VALUES (%s, %s)", (s["student_id"], insts[i % len(insts)]))
                flash(f"{len(studs)} students assigned evenly across {len(insts)} mentors.", "success")
            else:
                flash("Nothing to assign.", "error")
        else:
            stu = db.query("SELECT student_id FROM student WHERE roll_number = %s", (request.form.get("roll", "").strip(),), one=True)
            if not stu:
                flash("No student with that roll number.", "error")
            else:
                db.execute("""INSERT INTO mentorship (student_id, instructor_id) VALUES (%s, %s)
                              ON DUPLICATE KEY UPDATE instructor_id = VALUES(instructor_id), assigned_on = CURRENT_DATE""",
                           (stu["student_id"], request.form.get("instructor_id", type=int)))
                flash("Mentor assigned.", "success")
        return redirect(url_for("portal.admin_mentorship"))
    load = db.query("""SELECT i.instructor_id, CONCAT(i.first_name, ' ', i.last_name) AS name, COUNT(m.student_id) AS mentees
                         FROM instructor i LEFT JOIN mentorship m ON m.instructor_id = i.instructor_id
                        WHERE i.is_active GROUP BY i.instructor_id, name ORDER BY mentees DESC, name""")
    unassigned = db.query("SELECT COUNT(*) AS n FROM student WHERE status = 'active' AND student_id NOT IN (SELECT student_id FROM mentorship)", one=True)["n"]
    return render_template("admin_mentorship.html", load=load, unassigned=unassigned)


# ------------------------------------------------------------ assessments --
@bp.get("/student/assessments")
@role_required("student")
def student_assessments():
    sid = session["user"]["student_id"]
    quizzes = db.query(
        """SELECT q.quiz_id, q.title, q.available_from, q.available_until, q.time_limit_minutes, q.max_attempts,
                  c.course_code, e.enrollment_id,
                  (SELECT COUNT(*) FROM quiz_attempt qa WHERE qa.quiz_id = q.quiz_id AND qa.enrollment_id = e.enrollment_id) AS attempts,
                  (SELECT MAX(qa.score) FROM quiz_attempt qa WHERE qa.quiz_id = q.quiz_id AND qa.enrollment_id = e.enrollment_id) AS best,
                  (SELECT SUM(marks) FROM question WHERE quiz_id = q.quiz_id) AS total
             FROM enrollment e JOIN quiz q ON q.offering_id = e.offering_id
             JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
            WHERE e.student_id = %s AND e.status = 'enrolled' ORDER BY q.available_until""", (sid,))
    assignments = db.query(
        """SELECT a.assignment_id, a.title, a.due_date, a.max_marks, c.course_code, e.enrollment_id,
                  s.submission_id, s.marks_obtained
             FROM enrollment e JOIN assignment a ON a.offering_id = e.offering_id
             JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
             JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
             LEFT JOIN submission s ON s.assignment_id = a.assignment_id AND s.enrollment_id = e.enrollment_id
            WHERE e.student_id = %s AND e.status = 'enrolled' ORDER BY a.due_date""", (sid,))
    return render_template("student_assessments.html", quizzes=quizzes, assignments=assignments, now=datetime.now())


# ----------------------------------------------------------- registration --
@bp.route("/student/register", methods=["GET", "POST"])
@role_required("student")
def student_register():
    sid = session["user"]["student_id"]
    if request.method == "POST":
        try:
            db.call("sp_enroll_student", (sid, request.form.get("offering_id", type=int)))
            flash("You are enrolled.", "success")
        except mysql.connector.Error as err:
            flash(db_message(err), "error")
        return redirect(url_for("portal.student_register"))
    rows = db.query(
        """SELECT o.offering_id, c.course_code, c.title, c.credits, o.section_code, o.max_capacity,
                  (SELECT COUNT(*) FROM enrollment x WHERE x.offering_id = o.offering_id AND x.status <> 'dropped') AS taken,
                  (SELECT CONCAT(i.first_name, ' ', i.last_name) FROM offering_instructor oi JOIN instructor i ON i.instructor_id = oi.instructor_id
                    WHERE oi.offering_id = o.offering_id AND oi.role = 'primary' LIMIT 1) AS teacher
             FROM course_offering o JOIN course c ON c.course_id = o.course_id JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
            WHERE NOT EXISTS (SELECT 1 FROM enrollment e JOIN course_offering o2 ON o2.offering_id = e.offering_id
                               WHERE e.student_id = %s AND e.status <> 'dropped' AND o2.course_id = o.course_id AND o2.term_id = o.term_id)
            ORDER BY c.course_code, o.section_code""", (sid,))
    return render_template("student_register.html", rows=rows)


# ---------------------------------------------------------------- account --
def password_problem(pw):
    if len(pw) < 10:
        return "Use at least 10 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Use both letters and digits."
    return None


@bp.route("/account", methods=["GET", "POST"])
@role_required("student", "instructor", "admin")
def account():
    user = session["user"]
    if request.method == "POST":
        f = request.form
        row = db.query("SELECT password_hash FROM user_account WHERE user_id = %s", (user["user_id"],), one=True)
        problem = password_problem(f.get("new", ""))
        if not check_password_hash(row["password_hash"], f.get("current", "")):
            flash("Your current password is not correct.", "error")
        elif f.get("new") != f.get("confirm"):
            flash("The two new passwords differ.", "error")
        elif problem:
            flash(problem, "error")
        elif f["new"] == f["current"]:
            flash("Pick a password different from the old one.", "error")
        else:
            db.execute("""UPDATE user_account SET password_hash = %s, must_change_password = 0, password_changed_on = NOW()
                           WHERE user_id = %s""", (generate_password_hash(f["new"]), user["user_id"]))
            user["must_change"] = False
            session["user"] = user
            flash("Password updated.", "success")
            return redirect(url_for("index"))
    return render_template("account.html")


@bp.route("/admin/users", methods=["GET", "POST"])
@role_required("admin")
def admin_users():
    if request.method == "POST":
        uid = request.form.get("user_id", type=int)
        row = db.query("SELECT username, role FROM user_account WHERE user_id = %s", (uid,), one=True)
        if not row:
            abort(404)
        if request.form.get("action") == "reset":
            temp = secrets.token_urlsafe(9) + "7"
            db.execute("""UPDATE user_account SET password_hash = %s, must_change_password = 1 WHERE user_id = %s""",
                       (generate_password_hash(temp), uid))
            flash(f"Temporary password for {row['username']}: {temp}  (shown once; they must change it at next login)", "success")
        elif uid == session["user"]["user_id"]:
            flash("You cannot deactivate your own account.", "error")
        else:
            db.execute("UPDATE user_account SET is_active = NOT is_active WHERE user_id = %s", (uid,))
        return redirect(url_for("portal.admin_users", q=request.args.get("q", "")))
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    rows = db.query(
        """SELECT u.user_id, u.username, u.role, u.is_active, u.last_login, u.must_change_password,
                  COALESCE(CONCAT(s.first_name, ' ', s.last_name), CONCAT(i.first_name, ' ', i.last_name), 'Administrator') AS name
             FROM user_account u LEFT JOIN student s ON s.student_id = u.student_id LEFT JOIN instructor i ON i.instructor_id = u.instructor_id
            WHERE (%s = '' OR u.username LIKE %s OR s.first_name LIKE %s OR s.last_name LIKE %s OR i.first_name LIKE %s OR i.last_name LIKE %s)
              AND (%s = '' OR u.role = %s) ORDER BY u.role, u.username LIMIT 100""",
        (q, f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", role, role))
    return render_template("admin_users.html", rows=rows, q=q, role=role)


@bp.get("/admin/audit")
@role_required("admin")
def admin_audit():
    action, entity, actor = request.args.get("action", ""), request.args.get("entity", ""), request.args.get("actor", "").strip()
    rows = db.query("""SELECT * FROM audit_log WHERE (%s = '' OR action = %s) AND (%s = '' OR entity = %s)
                          AND (%s = '' OR actor LIKE %s) ORDER BY log_id DESC LIMIT 200""",
                    (action, action, entity, entity, actor, f"%{actor}%"))
    actions = [r["action"] for r in db.query("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return render_template("admin_audit.html", rows=rows, actions=actions, action=action, entity=entity, actor=actor)
