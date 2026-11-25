"""Shared fixtures. The suite runs against a database built by `python setup_db.py --yes --with-data`
and connects as the same low-privilege login the web app uses (DB_USER / DB_PASSWORD from .env)."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
from app import app as flask_app  # noqa: E402

def admin_sql(sql, params=()):
    """Clean-up that the app login is (deliberately) not allowed to do, e.g. wipe the append-only scan log."""
    import setup_db
    conn = setup_db.admin_connection()
    cur = conn.cursor()
    cur.execute("USE elearning_db")
    cur.execute(sql, params)
    conn.close()


DEMO = {"student": "learn123", "instructor": "teach123", "admin": "admin123"}


def token(client, path="/login"):
    html = client.get(path).get_data(True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(username, password):
    c = flask_app.test_client()
    r = c.post("/login", data={"username": username, "password": password, "csrf_token": token(c)})
    assert r.status_code == 302, f"login failed for {username}: {r.status_code}"
    return c


def post(client, path, form_page, **data):
    """POST with a fresh CSRF token taken from a page the user can see."""
    data["csrf_token"] = token(client, form_page)
    return client.post(path, data=data, follow_redirects=False)


def flashes(resp):
    return re.findall(r'class="flash [a-z]+" role="status">([^<]+)<', resp.get_data(True))


@pytest.fixture(scope="session")
def app():
    flask_app.config["TESTING"] = False
    return flask_app


@pytest.fixture()
def admin():
    return login("admin", DEMO["admin"])


@pytest.fixture(scope="session")
def section_a():
    """Offering 1 (DBMS, section A): its primary instructor and three enrolled students."""
    off = db.query("""SELECT o.offering_id, i.employee_code, i.instructor_id FROM course_offering o
                       JOIN offering_instructor oi ON oi.offering_id = o.offering_id AND oi.role = 'primary'
                       JOIN instructor i ON i.instructor_id = oi.instructor_id WHERE o.offering_id = 1""", one=True)
    studs = db.query("""SELECT s.student_id, s.roll_number, e.enrollment_id FROM enrollment e JOIN student s USING (student_id)
                         WHERE e.offering_id = 1 AND e.status = 'enrolled' ORDER BY s.roll_number LIMIT 6""")
    off["students"] = studs
    return off


@pytest.fixture()
def instructor(section_a):
    return login(section_a["employee_code"], DEMO["instructor"])


@pytest.fixture()
def student(section_a):
    return login(section_a["students"][0]["roll_number"], DEMO["student"])


@pytest.fixture()
def today_session(section_a):
    """A class session held today (created for the test, removed afterwards)."""
    ids = ",".join(str(s["student_id"]) for s in section_a["students"])
    admin_sql(f"DELETE FROM attendance_scan_log WHERE student_id IN ({ids})")      # the throttle is per student
    sid = db.execute("""INSERT INTO class_session (offering_id, session_date, start_time, end_time, topic)
                        VALUES (%s, CURDATE(), '00:01:00', '23:58:00', 'pytest session')""", (section_a["offering_id"],))
    yield sid
    db.execute("DELETE FROM class_session WHERE session_id = %s", (sid,))
    admin_sql(f"DELETE FROM attendance_scan_log WHERE session_id = %s OR student_id IN ({ids})", (sid,))
