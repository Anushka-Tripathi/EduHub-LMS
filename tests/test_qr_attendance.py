import time

import pytest

import db
from conftest import admin_sql, flashes, login, post
from modules.attendance import code_for, code_is_valid, STEP


def open_window(instructor, sid, minutes=20, late=10):
    return post(instructor, f"/instructor/session/{sid}/qr/open", f"/instructor/session/{sid}/qr", minutes=minutes, late_after=late)


def current_code(instructor, sid):
    return instructor.get(f"/instructor/session/{sid}/qr/state").get_json()["code"]


def scan(student, sid, code):
    return post(student, "/student/attendance/mark", "/student/scan", session_id=sid, code=code)


def mark_of(student_id, sid):
    return db.query("""SELECT a.status, a.marked_via FROM attendance a JOIN enrollment e USING (enrollment_id)
                        WHERE a.session_id = %s AND e.student_id = %s""", (sid, student_id), one=True)


def test_code_changes_every_step_and_checks_out():
    assert code_for("s" * 32, 7, 100) != code_for("s" * 32, 7, 101)
    assert code_for("s" * 32, 7, 100) != code_for("s" * 32, 8, 100)       # tied to the class
    now = 1_000_000.0
    c = code_for("k" * 32, 5, int(now // STEP))
    assert code_is_valid("k" * 32, 5, c, now)
    assert code_is_valid("k" * 32, 5, c, now + STEP)                       # previous step still accepted
    assert not code_is_valid("k" * 32, 5, c, now + 3 * STEP)               # stale
    assert not code_is_valid("k" * 32, 5, "000000", now) or c == "000000"


def test_full_flow_present_then_duplicate_refused(instructor, student, section_a, today_session):
    assert open_window(instructor, today_session).status_code == 302
    code = current_code(instructor, today_session)
    r = scan(student, today_session, code)
    assert r.status_code == 302
    sid = section_a["students"][0]["student_id"]
    assert mark_of(sid, today_session) == {"status": "present", "marked_via": "qr"}
    again = scan(student, today_session, code)
    assert any("already marked" in m for m in flashes(student.get("/student/scan")))
    state = instructor.get(f"/instructor/session/{today_session}/qr/state").get_json()
    assert state["present"] == 1 and state["recent"][0]["roll_number"] == section_a["students"][0]["roll_number"]


def test_wrong_code_is_refused_and_logged(instructor, student, section_a, today_session):
    open_window(instructor, today_session)
    scan(student, today_session, "000000")
    assert mark_of(section_a["students"][0]["student_id"], today_session) is None
    log = db.query("SELECT outcome FROM attendance_scan_log WHERE session_id = %s", (today_session,))
    assert any(l["outcome"] in ("bad_code", "ok") for l in log)


def test_closed_window_refuses_scans(instructor, student, section_a, today_session):
    open_window(instructor, today_session)
    code = current_code(instructor, today_session)
    post(instructor, f"/instructor/session/{today_session}/qr/close", f"/instructor/session/{today_session}/qr")
    db.execute("UPDATE qr_window SET opened_at = NOW() - INTERVAL 30 MINUTE, late_after = NOW() - INTERVAL 10 MINUTE, closes_at = NOW() - INTERVAL 1 MINUTE WHERE session_id = %s", (today_session,))
    scan(student, today_session, code)
    assert mark_of(section_a["students"][0]["student_id"], today_session) is None


def test_scan_after_late_cutoff_is_marked_late(instructor, student, section_a, today_session):
    open_window(instructor, today_session)
    db.execute("UPDATE qr_window SET opened_at = NOW() - INTERVAL 5 MINUTE, late_after = NOW() - INTERVAL 1 MINUTE WHERE session_id = %s", (today_session,))
    scan(student, today_session, current_code(instructor, today_session))
    assert mark_of(section_a["students"][0]["student_id"], today_session)["status"] == "late"


def test_student_from_another_section_cannot_mark(instructor, today_session, section_a):
    other = db.query("""SELECT s.roll_number FROM student s WHERE s.student_id NOT IN
                         (SELECT student_id FROM enrollment WHERE offering_id = %s) AND s.status = 'active' LIMIT 1""",
                     (section_a["offering_id"],), one=True)
    open_window(instructor, today_session)
    code = current_code(instructor, today_session)
    outsider = login(other["roll_number"], "learn123")
    scan(outsider, today_session, code)
    assert db.query("SELECT COUNT(*) AS n FROM attendance WHERE session_id = %s", (today_session,), one=True)["n"] == 0


def test_only_the_teaching_instructor_can_open(today_session, section_a):
    other = db.query("""SELECT employee_code FROM instructor WHERE instructor_id NOT IN
                         (SELECT instructor_id FROM offering_instructor WHERE offering_id = %s) AND department_id = 1 LIMIT 1""",
                     (section_a["offering_id"],), one=True)
    stranger = login(other["employee_code"], "teach123")
    assert stranger.get(f"/instructor/session/{today_session}/qr").status_code == 403


def test_cannot_open_for_a_past_class(instructor, section_a):
    past = db.query("SELECT session_id FROM class_session WHERE offering_id = %s AND session_date < CURDATE() LIMIT 1", (section_a["offering_id"],), one=True)
    r = open_window(instructor, past["session_id"])
    assert db.query("SELECT COUNT(*) AS n FROM qr_window WHERE session_id = %s", (past["session_id"],), one=True)["n"] == 0


def test_throttle_after_many_wrong_codes(instructor, student, section_a, today_session):
    open_window(instructor, today_session)
    for _ in range(9):
        scan(student, today_session, "111111")
    outcomes = [r["outcome"] for r in db.query("SELECT outcome FROM attendance_scan_log WHERE session_id = %s", (today_session,))]
    assert "blocked" in outcomes
    admin_sql("DELETE FROM attendance_scan_log WHERE session_id = %s", (today_session,))


def test_finish_marks_the_rest_absent(instructor, student, section_a, today_session):
    open_window(instructor, today_session)
    scan(student, today_session, current_code(instructor, today_session))
    post(instructor, f"/instructor/session/{today_session}/qr/close", f"/instructor/session/{today_session}/qr", finish="1")
    rows = db.query("SELECT status, marked_via, COUNT(*) AS n FROM attendance WHERE session_id = %s GROUP BY 1, 2", (today_session,))
    by = {(r["status"], r["marked_via"]): r["n"] for r in rows}
    assert by[("present", "qr")] == 1 and by[("absent", "system")] >= 5


def test_qr_image_is_svg(instructor, today_session):
    open_window(instructor, today_session)
    r = instructor.get(f"/instructor/session/{today_session}/qr.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data


def test_attendance_tab_numbers_match_the_database(student, section_a):
    sid = section_a["students"][0]["student_id"]
    html = student.get("/student/attendance").get_data(True)
    rows = db.query("""SELECT SUM(a.status IN ('present','late')) AS att, SUM(a.status IN ('present','late','absent')) AS cnt
                         FROM attendance a JOIN enrollment e USING (enrollment_id) JOIN class_session cs USING (session_id)
                        WHERE e.student_id = %s AND e.status = 'enrolled' AND cs.session_date <= CURDATE()""", (sid,), one=True)
    pct = round(100 * rows["att"] / rows["cnt"], 1)
    assert f"{pct}%" in html


def test_daywise_calendar_renders_for_any_month(student):
    for month in ("2026-08", "2026-10", "2026-12", "2027-02", "bad-value"):
        assert student.get(f"/student/attendance?view=daywise&month={month}").status_code == 200
