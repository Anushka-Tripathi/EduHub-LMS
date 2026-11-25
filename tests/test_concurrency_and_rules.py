"""Transactions and database rules: what happens when two people act at the same instant."""
import threading

import mysql.connector
import pytest

import db


def new_conn():
    c = db.get_conn()
    return c, c.cursor(dictionary=True)


@pytest.fixture()
def one_seat_offering():
    """A fresh offering with exactly one free seat, in the current term."""
    term = db.query("SELECT term_id FROM academic_term WHERE is_current", one=True)["term_id"]
    db.execute("DELETE FROM course_offering WHERE course_id IN (SELECT course_id FROM course WHERE course_code = 'PYTEST101')")
    db.execute("DELETE FROM course WHERE course_code = 'PYTEST101'")
    course = db.execute("INSERT INTO course (course_code, title, credits, department_id) VALUES ('PYTEST101', 'Seat race', 1, 1)")
    oid = db.execute("INSERT INTO course_offering (course_id, term_id, section_code, max_capacity) VALUES (%s, %s, 'Z', 1)", (course, term))
    db.execute("INSERT INTO offering_instructor (offering_id, instructor_id, role) VALUES (%s, 1, 'primary')", (oid,))
    yield oid
    db.execute("DELETE FROM course_offering WHERE offering_id = %s", (oid,))     # enrolments go with it (cascade)
    db.execute("DELETE FROM course WHERE course_id = %s", (course,))


def test_last_seat_goes_to_exactly_one_student(one_seat_offering):
    students = [r["student_id"] for r in db.query("SELECT student_id FROM student WHERE status = 'active' ORDER BY student_id LIMIT 8")]
    assert len(students) >= 8
    results, barrier = [], threading.Barrier(len(students))

    def enrol(sid):
        conn, cur = new_conn()
        try:
            barrier.wait()
            cur.callproc("sp_enroll_student", (sid, one_seat_offering))
            conn.commit()
            results.append("ok")
        except mysql.connector.Error as err:
            results.append("full" if "full" in str(err) else str(err))
        finally:
            conn.close()

    threads = [threading.Thread(target=enrol, args=(s,)) for s in students]
    [t.start() for t in threads]; [t.join() for t in threads]
    taken = db.query("SELECT COUNT(*) AS n FROM enrollment WHERE offering_id = %s AND status <> 'dropped'", (one_seat_offering,), one=True)["n"]
    assert results.count("ok") == 1 and taken == 1, results


@pytest.fixture()
def invoice():
    stu = db.query("SELECT student_id FROM student LIMIT 1", one=True)["student_id"]
    term = db.query("SELECT term_id FROM academic_term WHERE is_current", one=True)["term_id"]
    iid = db.execute("INSERT INTO fee_invoice (student_id, term_id, description, amount, due_date) VALUES (%s, %s, 'pytest fee', 1000, CURDATE() + INTERVAL 30 DAY)", (stu, term))
    yield iid
    db.execute("DELETE FROM fee_payment WHERE invoice_id = %s", (iid,))
    db.execute("DELETE FROM fee_invoice WHERE invoice_id = %s", (iid,))


def test_two_simultaneous_payments_cannot_overpay(invoice):
    results, barrier = [], threading.Barrier(2)

    def pay(ref):
        conn, cur = new_conn()
        try:
            barrier.wait()
            cur.execute("INSERT INTO fee_payment (invoice_id, amount, mode, reference_no) VALUES (%s, 700, 'upi', %s)", (invoice, ref))
            conn.commit(); results.append("ok")
        except mysql.connector.Error as err:
            conn.rollback(); results.append("rejected")
        finally:
            conn.close()

    ts = [threading.Thread(target=pay, args=(f"PYTEST-{i}-{invoice}",)) for i in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    paid = db.query("SELECT SUM(amount) AS s FROM fee_payment WHERE invoice_id = %s", (invoice,), one=True)["s"]
    assert sorted(results) == ["ok", "rejected"] and paid == 700


def test_payment_status_view(invoice):
    assert db.query("SELECT status, balance FROM v_fee_invoice_status WHERE invoice_id = %s", (invoice,), one=True)["status"] == "due"
    db.execute("INSERT INTO fee_payment (invoice_id, amount, mode, reference_no) VALUES (%s, 400, 'cash', %s)", (invoice, f"PYTEST-A-{invoice}"))
    assert db.query("SELECT status FROM v_fee_invoice_status WHERE invoice_id = %s", (invoice,), one=True)["status"] == "partial"
    db.execute("INSERT INTO fee_payment (invoice_id, amount, mode, reference_no) VALUES (%s, 600, 'cash', %s)", (invoice, f"PYTEST-B-{invoice}"))
    assert db.query("SELECT status FROM v_fee_invoice_status WHERE invoice_id = %s", (invoice,), one=True)["status"] == "paid"


def test_grade_change_is_audited_with_the_actor():
    sub = db.query("SELECT submission_id, marks_obtained FROM submission WHERE marks_obtained IS NOT NULL LIMIT 1", one=True)
    count = lambda: db.query("SELECT COUNT(*) AS n FROM audit_log WHERE entity = 'submission' AND entity_id = %s AND actor = 'pytest-grader'", (str(sub["submission_id"]),), one=True)["n"]
    before = count()
    conn, cur = new_conn()
    try:
        cur.execute("SET @app_user = 'pytest-grader'")
        cur.execute("UPDATE submission SET marks_obtained = marks_obtained - 0.5 WHERE submission_id = %s", (sub["submission_id"],))
        conn.commit()
        cur.execute("UPDATE submission SET marks_obtained = %s WHERE submission_id = %s", (sub["marks_obtained"], sub["submission_id"]))
        conn.commit()
    finally:
        conn.close()
    assert count() == before + 2
    last = db.query("SELECT detail FROM audit_log WHERE actor = 'pytest-grader' ORDER BY log_id DESC LIMIT 1", one=True)
    assert "->" in last["detail"]


def test_attendance_cannot_be_marked_for_the_future():
    fut = db.query("SELECT cs.session_id, e.enrollment_id FROM class_session cs JOIN enrollment e ON e.offering_id = cs.offering_id AND e.status = 'enrolled' WHERE cs.session_date > CURDATE() LIMIT 1", one=True)
    with pytest.raises(mysql.connector.Error) as err:
        db.execute("INSERT INTO attendance (session_id, enrollment_id, status) VALUES (%s, %s, 'present')", (fut["session_id"], fut["enrollment_id"]))
    assert "future" in str(err.value)


def test_generated_sessions_skip_holidays():
    term = db.query("SELECT * FROM academic_term WHERE is_current", one=True)
    hol = db.query("SELECT holiday_date FROM holiday WHERE holiday_date BETWEEN %s AND %s", (term["start_date"], term["end_date"]))
    on_holiday = db.query("SELECT COUNT(*) AS n FROM class_session cs JOIN holiday h ON h.holiday_date = cs.session_date JOIN course_offering o USING (offering_id) WHERE o.offering_id > 7", one=True)["n"]
    assert hol and on_holiday == 0


def test_new_assignment_notifies_the_course():
    before = db.query("SELECT COUNT(*) AS n FROM notification WHERE offering_id = 1", one=True)["n"]
    aid = db.execute("INSERT INTO assignment (offering_id, title, max_marks, due_date) VALUES (1, 'pytest assignment', 10, NOW() + INTERVAL 5 DAY)")
    after = db.query("SELECT COUNT(*) AS n FROM notification WHERE offering_id = 1", one=True)["n"]
    db.execute("DELETE FROM assignment WHERE assignment_id = %s", (aid,))
    db.execute("DELETE FROM notification WHERE title = 'New assignment: pytest assignment'")
    assert after == before + 1
