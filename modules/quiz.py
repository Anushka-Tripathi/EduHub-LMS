"""Quizzes: instructors build them, students take them against a server-side clock."""
import json
import random

import mysql.connector
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

import db
from modules.common import (db_message, instructor_offering_or_403, role_required,
                            student_enrollment_or_403)

bp = Blueprint("quiz", __name__)


# ----------------------------------------------------------------- student --
def _quiz_for_student(qid):
    """(quiz row, enrollment row) when the logged-in student is enrolled in the quiz's course."""
    quiz = db.query("SELECT * FROM quiz WHERE quiz_id = %s", (qid,), one=True)
    if not quiz:
        abort(404)
    enr = db.query("""SELECT * FROM enrollment WHERE student_id = %s AND offering_id = %s
                         AND status IN ('enrolled', 'completed', 'failed')""",
                   (session["user"]["student_id"], quiz["offering_id"]), one=True)
    if not enr:
        abort(403)
    return quiz, enr


@bp.get("/student/quiz/<int:qid>")
@role_required("student")
def intro(qid):
    quiz, enr = _quiz_for_student(qid)
    info = db.query("""SELECT COUNT(*) AS questions, COALESCE(SUM(marks), 0) AS total FROM question
                        WHERE quiz_id = %s""", (qid,), one=True)
    attempts = db.query("""SELECT attempt_id, attempt_no, attempted_on, submitted_on, score,
                                  (submitted_on IS NULL AND attempted_on + INTERVAL %s MINUTE > NOW()) AS in_progress
                             FROM quiz_attempt WHERE quiz_id = %s AND enrollment_id = %s ORDER BY attempt_no""",
                        (quiz["time_limit_minutes"], qid, enr["enrollment_id"]))
    state = db.query("SELECT NOW() < %s AS before_open, NOW() > %s AS closed", (quiz["available_from"], quiz["available_until"]), one=True)
    return render_template("quiz_intro.html", quiz=quiz, enr=enr, info=info, attempts=attempts,
                           state=state, can_start=(enr["status"] == "enrolled" and not state["before_open"] and not state["closed"]
                                                   and info["questions"] > 0))


@bp.post("/student/quiz/<int:qid>/start")
@role_required("student")
def start(qid):
    quiz, enr = _quiz_for_student(qid)
    try:
        aid = db.call("sp_start_quiz_attempt", (qid, enr["enrollment_id"]))[0][0]["attempt_id"]
        return redirect(url_for("quiz.take", aid=aid))
    except mysql.connector.Error as err:
        flash(db_message(err), "error")
        return redirect(url_for("quiz.intro", qid=qid))


def _attempt_for_student(aid):
    a = db.query("""SELECT qa.*, q.title, q.time_limit_minutes, q.offering_id, q.available_until,
                           TIMESTAMPDIFF(SECOND, NOW(), qa.attempted_on + INTERVAL q.time_limit_minutes MINUTE) AS seconds_left,
                           e.student_id
                      FROM quiz_attempt qa JOIN quiz q ON q.quiz_id = qa.quiz_id
                      JOIN enrollment e ON e.enrollment_id = qa.enrollment_id WHERE qa.attempt_id = %s""", (aid,), one=True)
    if not a or a["student_id"] != session["user"]["student_id"]:
        abort(403)
    return a


@bp.get("/student/quiz/attempt/<int:aid>")
@role_required("student")
def take(aid):
    a = _attempt_for_student(aid)
    if a["submitted_on"] is not None:
        return redirect(url_for("quiz.result", aid=aid))
    questions = db.query("SELECT question_id, question_text, marks FROM question WHERE quiz_id = %s", (a["quiz_id"],))
    rnd = random.Random(aid)                  # same order on reload, different per attempt
    rnd.shuffle(questions)
    for q in questions:
        q["options"] = db.query("SELECT option_id, option_text FROM question_option WHERE question_id = %s",
                                (q["question_id"],))
        rnd.shuffle(q["options"])
    return render_template("quiz_take.html", a=a, questions=questions, seconds_left=max(a["seconds_left"], 0))


@bp.post("/student/quiz/attempt/<int:aid>/submit")
@role_required("student")
def submit(aid):
    a = _attempt_for_student(aid)
    answers = []
    for key, val in request.form.items():
        if key.startswith("q_") and val.isdigit():
            answers.append({"q": int(key[2:]), "o": int(val)})
    try:
        out = db.call("sp_submit_quiz_attempt", (aid, a["enrollment_id"], json.dumps(answers)))[0][0]
        if out["outcome"] == "timed_out":
            flash("Time was up before your answers arrived, so this attempt scored 0.", "error")
        else:
            flash("Quiz submitted.", "success")
    except mysql.connector.Error as err:
        flash(db_message(err), "error")
    return redirect(url_for("quiz.result", aid=aid))


@bp.get("/student/quiz/attempt/<int:aid>/result")
@role_required("student")
def result(aid):
    a = _attempt_for_student(aid)
    total = db.query("SELECT SUM(marks) AS t FROM question WHERE quiz_id = %s", (a["quiz_id"],), one=True)["t"]
    closed = db.query("SELECT NOW() > %s AS c", (a["available_until"],), one=True)["c"]
    review = []
    if closed:     # correct answers are shown only after the quiz window ends
        review = db.query(
            """SELECT q.question_text, q.marks, so.option_text AS chosen, so.is_correct AS right_answer,
                      (SELECT option_text FROM question_option WHERE question_id = q.question_id AND is_correct LIMIT 1) AS correct
                 FROM question q
                 LEFT JOIN quiz_answer an ON an.question_id = q.question_id AND an.attempt_id = %s
                 LEFT JOIN question_option so ON so.option_id = an.selected_option_id
                WHERE q.quiz_id = %s ORDER BY q.question_id""", (aid, a["quiz_id"]))
    return render_template("quiz_result.html", a=a, total=total, review=review, closed=closed)


# -------------------------------------------------------------- instructor --
@bp.route("/instructor/offering/<int:oid>/quizzes/new", methods=["GET", "POST"])
@role_required("instructor", "admin")
def build(oid):
    offering = instructor_offering_or_403(oid)
    course = db.query("SELECT c.course_code, c.title FROM course c WHERE c.course_id = %s", (offering["course_id"],), one=True)
    if request.method == "POST":
        f = request.form
        texts = f.getlist("q_text")
        marks = f.getlist("q_marks")
        try:
            if not f.get("title", "").strip() or not any(t.strip() for t in texts):
                raise ValueError("Give the quiz a title and at least one question.")
            with db.transaction() as cur:
                cur.execute("""INSERT INTO quiz (offering_id, title, time_limit_minutes, max_attempts, available_from, available_until)
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            (oid, f["title"].strip()[:150], int(f["time_limit"]), int(f["max_attempts"]),
                             f["available_from"].replace("T", " "), f["available_until"].replace("T", " ")))
                quiz_id = cur.lastrowid
                count = 0
                for i, text in enumerate(texts):
                    if not text.strip():
                        continue
                    opts = [o.strip() for o in f.getlist(f"opt_{i}") if o.strip()]
                    correct = f.get(f"correct_{i}", type=int)
                    if len(opts) < 2 or correct is None or correct >= len(f.getlist(f"opt_{i}")) or not f.getlist(f"opt_{i}")[correct].strip():
                        raise ValueError(f"Question {i + 1} needs at least two options and one marked correct.")
                    cur.execute("INSERT INTO question (quiz_id, question_text, marks) VALUES (%s, %s, %s)",
                                (quiz_id, text.strip(), float(marks[i] or 1)))
                    qid = cur.lastrowid
                    for j, opt in enumerate(f.getlist(f"opt_{i}")):
                        if opt.strip():
                            cur.execute("INSERT INTO question_option (question_id, option_text, is_correct) VALUES (%s, %s, %s)",
                                        (qid, opt.strip()[:300], 1 if j == correct else 0))
                    count += 1
            db.log_event("QUIZ_CREATE", "quiz", quiz_id, f"{count} questions")
            flash(f"Quiz created with {count} questions.", "success")
            return redirect(url_for("quiz.results", qid=quiz_id))
        except (ValueError, mysql.connector.Error) as err:
            flash(db_message(err) if isinstance(err, mysql.connector.Error) else str(err), "error")
    return render_template("quiz_build.html", offering=offering, course=course)


@bp.get("/instructor/quiz/<int:qid>")
@role_required("instructor", "admin")
def results(qid):
    quiz = db.query("SELECT * FROM quiz WHERE quiz_id = %s", (qid,), one=True)
    if not quiz:
        abort(404)
    offering = instructor_offering_or_403(quiz["offering_id"])
    total = db.query("SELECT COALESCE(SUM(marks), 0) AS t FROM question WHERE quiz_id = %s", (qid,), one=True)["t"]
    attempts = db.query("""SELECT s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student, qa.attempt_no,
                                  qa.attempted_on, qa.submitted_on, qa.score
                             FROM quiz_attempt qa JOIN enrollment e ON e.enrollment_id = qa.enrollment_id
                             JOIN student s ON s.student_id = e.student_id
                            WHERE qa.quiz_id = %s ORDER BY s.roll_number, qa.attempt_no""", (qid,))
    per_q = db.query("""SELECT q.question_text, COUNT(an.attempt_id) AS answered,
                               ROUND(100 * SUM(o.is_correct) / NULLIF(COUNT(an.attempt_id), 0), 0) AS pct_correct
                          FROM question q LEFT JOIN quiz_answer an ON an.question_id = q.question_id
                          LEFT JOIN question_option o ON o.option_id = an.selected_option_id
                         WHERE q.quiz_id = %s GROUP BY q.question_id, q.question_text ORDER BY q.question_id""", (qid,))
    scores = [float(a["score"]) for a in attempts if a["score"] is not None]
    return render_template("quiz_results.html", quiz=quiz, offering=offering, total=total, attempts=attempts,
                           per_q=per_q, avg=round(sum(scores) / len(scores), 2) if scores else None)
