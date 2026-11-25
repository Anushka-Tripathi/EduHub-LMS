import io
import json
import re

import db
from conftest import flashes, login, post, token

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def module_of(oid):
    return db.query("SELECT module_id FROM module WHERE offering_id = %s ORDER BY module_number LIMIT 1", (oid,), one=True)["module_id"]


def upload(instructor, oid, filename, data, title="pytest material"):
    t = token(instructor, f"/instructor/offering/{oid}")
    return instructor.post(f"/instructor/offering/{oid}/materials", data={
        "csrf_token": t, "module_id": module_of(oid), "title": title, "file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data", follow_redirects=True)


def latest_material(title="pytest material"):
    return db.query("SELECT * FROM material WHERE title = %s ORDER BY material_id DESC LIMIT 1", (title,), one=True)


def test_upload_download_roundtrip_and_delete(instructor, student, section_a):
    oid = section_a["offering_id"]
    upload(instructor, oid, "notes.pdf", PDF)
    m = latest_material()
    assert m and m["original_name"] == "notes.pdf" and m["stored_name"].endswith(".pdf") and m["file_size"] == len(PDF)
    r = student.get(f"/materials/{m['material_id']}/download")
    assert r.status_code == 200 and r.data == PDF
    assert db.query("SELECT COUNT(*) AS n FROM notification WHERE title = %s", ("New study material: pytest material",), one=True)["n"] >= 1
    post(instructor, f"/instructor/materials/{m['material_id']}/delete", f"/instructor/offering/{oid}")
    assert latest_material() is None
    assert student.get(f"/materials/{m['material_id']}/download").status_code == 404


def test_unenrolled_student_cannot_download(instructor, section_a):
    oid = section_a["offering_id"]
    upload(instructor, oid, "private.pdf", PDF, title="pytest private")
    m = latest_material("pytest private")
    other = db.query("""SELECT roll_number FROM student WHERE student_id NOT IN (SELECT student_id FROM enrollment WHERE offering_id = %s)
                         AND status = 'active' LIMIT 1""", (oid,), one=True)
    assert login(other["roll_number"], "learn123").get(f"/materials/{m['material_id']}/download").status_code == 403
    post(instructor, f"/instructor/materials/{m['material_id']}/delete", f"/instructor/offering/{oid}")


def test_hidden_material_is_not_served_to_students(instructor, student, section_a):
    oid = section_a["offering_id"]
    upload(instructor, oid, "draft.pdf", PDF, title="pytest hidden")
    m = latest_material("pytest hidden")
    post(instructor, f"/instructor/materials/{m['material_id']}/toggle", f"/instructor/offering/{oid}")
    assert student.get(f"/materials/{m['material_id']}/download").status_code == 403
    post(instructor, f"/instructor/materials/{m['material_id']}/delete", f"/instructor/offering/{oid}")


def test_dangerous_files_are_refused(instructor, section_a):
    oid = section_a["offering_id"]
    for name, body in [("run.exe", b"MZ"), ("page.html", b"<script>alert(1)</script>"), ("fake.pdf", b"not a pdf at all"), ("a.php", b"<?php ?>")]:
        r = upload(instructor, oid, name, body, title="pytest bad")
        assert latest_material("pytest bad") is None, name


def test_path_traversal_in_filename_is_neutralised(instructor, section_a):
    oid = section_a["offering_id"]
    upload(instructor, oid, "../../etc/passwd.pdf", PDF, title="pytest trav")
    m = latest_material("pytest trav")
    assert m and "/" not in m["stored_name"] and ".." not in m["stored_name"] and "/" not in m["original_name"]
    post(instructor, f"/instructor/materials/{m['material_id']}/delete", f"/instructor/offering/{oid}")


def test_student_cannot_upload(student, section_a):
    oid = section_a["offering_id"]
    r = student.post(f"/instructor/offering/{oid}/materials", data={"csrf_token": token(student, "/student/scan")})
    assert r.status_code == 403


# ---------------------------------------------------------------- quizzes
def build_quiz(instructor, oid, title="pytest quiz", minutes=15):
    t = token(instructor, f"/instructor/offering/{oid}/quizzes/new")
    form = {"csrf_token": t, "title": title, "time_limit": minutes, "max_attempts": 2,
            "available_from": "2026-01-01T00:00", "available_until": "2035-01-01T00:00",
            "q_text": ["2 + 2 ?", "Capital of France?"], "q_marks": ["2", "3"],
            "opt_0": ["3", "4", "5", ""], "correct_0": "1", "opt_1": ["Paris", "Rome", "", ""], "correct_1": "0"}
    return instructor.post(f"/instructor/offering/{oid}/quizzes/new", data=form)


def cleanup_quiz(title="pytest quiz"):
    db.execute("DELETE FROM quiz WHERE title = %s", (title,))
    db.execute("DELETE FROM notification WHERE title = %s", (f"New quiz: {title}",))


def correct_answers(qid):
    return {q["question_id"]: db.query("SELECT option_id FROM question_option WHERE question_id = %s AND is_correct", (q["question_id"],), one=True)["option_id"]
            for q in db.query("SELECT question_id FROM question WHERE quiz_id = %s", (qid,))}


def test_quiz_build_take_submit_score(instructor, student, section_a):
    oid = section_a["offering_id"]
    cleanup_quiz()
    r = build_quiz(instructor, oid)
    assert r.status_code == 302
    qid = db.query("SELECT quiz_id FROM quiz WHERE title = 'pytest quiz'", one=True)["quiz_id"]
    assert db.query("SELECT COUNT(*) AS n FROM question WHERE quiz_id = %s", (qid,), one=True)["n"] == 2
    post(student, f"/student/quiz/{qid}/start", f"/student/quiz/{qid}")
    aid = db.query("SELECT attempt_id FROM quiz_attempt WHERE quiz_id = %s", (qid,), one=True)["attempt_id"]
    page = student.get(f"/student/quiz/attempt/{aid}").get_data(True)
    assert "2 + 2" in page and 'id="timer"' in page
    answers = {f"q_{q}": o for q, o in correct_answers(qid).items()}
    r = post(student, f"/student/quiz/attempt/{aid}/submit", f"/student/quiz/attempt/{aid}", **answers)
    assert float(db.query("SELECT score FROM quiz_attempt WHERE attempt_id = %s", (aid,), one=True)["score"]) == 5.0
    r2 = post(student, f"/student/quiz/attempt/{aid}/submit", "/student/scan", **answers)
    assert float(db.query("SELECT score FROM quiz_attempt WHERE attempt_id = %s", (aid,), one=True)["score"]) == 5.0   # not rescored
    cleanup_quiz()


def test_wrong_answers_score_zero_and_late_submit_times_out(instructor, student, section_a):
    oid = section_a["offering_id"]
    cleanup_quiz()
    build_quiz(instructor, oid, minutes=1)
    qid = db.query("SELECT quiz_id FROM quiz WHERE title = 'pytest quiz'", one=True)["quiz_id"]
    post(student, f"/student/quiz/{qid}/start", f"/student/quiz/{qid}")
    aid = db.query("SELECT attempt_id FROM quiz_attempt WHERE quiz_id = %s", (qid,), one=True)["attempt_id"]
    db.execute("UPDATE quiz_attempt SET attempted_on = NOW() - INTERVAL 10 MINUTE WHERE attempt_id = %s", (aid,))
    answers = {f"q_{q}": o for q, o in correct_answers(qid).items()}
    r = post(student, f"/student/quiz/attempt/{aid}/submit", f"/student/quiz/attempt/{aid}", **answers)
    row = db.query("SELECT score, submitted_on FROM quiz_attempt WHERE attempt_id = %s", (aid,), one=True)
    assert float(row["score"]) == 0 and row["submitted_on"] is not None
    assert db.query("SELECT COUNT(*) AS n FROM quiz_answer WHERE attempt_id = %s", (aid,), one=True)["n"] == 0
    cleanup_quiz()


def test_student_cannot_open_someone_elses_attempt(instructor, student, section_a):
    oid = section_a["offering_id"]
    cleanup_quiz()
    build_quiz(instructor, oid)
    qid = db.query("SELECT quiz_id FROM quiz WHERE title = 'pytest quiz'", one=True)["quiz_id"]
    other = login(section_a["students"][1]["roll_number"], "learn123")
    post(other, f"/student/quiz/{qid}/start", f"/student/quiz/{qid}")
    aid = db.query("SELECT attempt_id FROM quiz_attempt WHERE quiz_id = %s", (qid,), one=True)["attempt_id"]
    assert student.get(f"/student/quiz/attempt/{aid}").status_code == 403
    cleanup_quiz()
