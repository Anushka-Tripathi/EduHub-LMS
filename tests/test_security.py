import mysql.connector
import pytest

import db
from conftest import DEMO, login, post, token, flask_app


def test_security_headers_present():
    r = flask_app.test_client().get("/login")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_post_without_csrf_token_is_rejected(admin):
    assert admin.post("/admin/holidays", data={"holiday_date": "2027-01-01", "name": "x"}).status_code == 400


def test_post_with_forged_csrf_token_is_rejected(admin):
    r = admin.post("/admin/holidays", data={"holiday_date": "2027-01-01", "name": "x", "csrf_token": "forged"})
    assert r.status_code == 400


def test_logout_needs_post(student):
    assert student.get("/logout").status_code == 405


def test_anonymous_is_sent_to_login_with_next():
    r = flask_app.test_client().get("/student/attendance")
    assert r.status_code == 302 and "/login?next=" in r.headers["Location"]


@pytest.mark.parametrize("path", ["/admin", "/admin/audit", "/admin/users", "/admin/fees", "/instructor", "/instructor/attendance"])
def test_student_cannot_reach_staff_pages(student, path):
    assert student.get(path).status_code == 403


@pytest.mark.parametrize("path", ["/admin", "/admin/audit", "/admin/users", "/student", "/student/attendance"])
def test_instructor_cannot_reach_admin_or_student_pages(instructor, path):
    assert instructor.get(path).status_code == 403


def test_open_redirect_is_ignored():
    c = flask_app.test_client()
    r = c.post("/login", data={"username": "admin", "password": DEMO["admin"], "csrf_token": token(c), "next": "//evil.example"})
    assert r.headers["Location"] in ("/", "http://localhost/")


def test_login_lockout_after_repeated_failures():
    name = "no.such.user.pytest"
    db.execute("DELETE FROM login_attempt WHERE username = %s", (name,))
    c = flask_app.test_client()
    codes = []
    for _ in range(7):
        codes.append(c.post("/login", data={"username": name, "password": "x", "csrf_token": token(c)}).status_code)
    db.execute("DELETE FROM login_attempt WHERE username = %s", (name,))
    assert codes[:5] == [200] * 5 and codes[-1] == 429


def test_passwords_are_hashed():
    row = db.query("SELECT password_hash FROM user_account WHERE username = 'admin'", one=True)
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:")) and "admin123" not in row["password_hash"]


def test_student_cannot_open_another_students_course(student, section_a):
    other = section_a["students"][1]["enrollment_id"]
    assert student.get(f"/student/course/{other}").status_code == 403


def test_session_cookie_flags():
    c = flask_app.test_client()
    c.post("/login", data={"username": "admin", "password": DEMO["admin"], "csrf_token": token(c)})
    cookie = [h for h in c.get("/").headers.getlist("Set-Cookie")] or [h for h in c._cookies.values()]
    assert flask_app.config["SESSION_COOKIE_HTTPONLY"] and flask_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


# ---- what the database login is allowed to do (the app never connects as root) ----
@pytest.fixture()
def raw():
    conn = db.get_conn()
    yield conn.cursor()
    conn.close()


@pytest.mark.parametrize("sql", [
    "DROP TABLE student", "ALTER TABLE student ADD COLUMN x INT", "DELETE FROM audit_log",
    "UPDATE audit_log SET actor = 'nobody'", "INSERT INTO audit_log (actor, action, entity) VALUES ('x','x','x')",
    "UPDATE grade_scale SET min_percentage = 0", "CREATE TABLE evil (id INT)", "GRANT ALL ON *.* TO 'lms_app'@'localhost'",
    "CREATE USER 'x'@'%' IDENTIFIED BY 'y'",
])
def test_app_login_cannot_do_dangerous_things(raw, sql):
    with pytest.raises(mysql.connector.Error) as err:
        raw.execute(sql)
    assert err.value.errno in (1142, 1044, 1045, 1227, 1410)       # privilege errors


def test_app_login_can_append_audit_only_through_the_procedure(raw):
    raw.execute("CALL sp_log_event('pytest', 'TEST', 'unit', '1', 'ok', NULL)")
    raw.execute("SELECT COUNT(*) FROM audit_log WHERE actor = 'pytest'")
    assert raw.fetchone()[0] >= 1
