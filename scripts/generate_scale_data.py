#!/usr/bin/env python3
"""Grows the seed database to a realistic college size.

What is REAL here: the course catalogue (data/catalog/*.csv), the term dates, the structure of the
university portal. What is GENERATED: people (names, phones, emails), attendance, marks, payments.
Nothing generated here pretends to be a real student; swap in the real roster with CSV import
(see README, "Loading real data").

  python scripts/generate_scale_data.py                    # 4 sections x 60 students
  python scripts/generate_scale_data.py --sections 8       # bigger
  python scripts/generate_scale_data.py --seed 7           # different (but repeatable) data

It is deterministic for a given --seed, and refuses to run twice on the same database.
"""
import argparse
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
from config import Config  # noqa: E402

FIRST_M = "Aarav Vivaan Aditya Arjun Reyansh Krish Ishaan Kabir Rohan Vihaan Ayaan Dhruv Rahul Karan Aryan Nikhil Siddharth Yash Harsh Manav Pranav Tanmay Varun Kunal Mohit Shaurya Devansh Ansh Raghav Parth Naman Lakshya Rudra Dev Samar Atharv Neel Jay Sahil".split()
FIRST_F = "Ananya Diya Saanvi Aadhya Myra Ira Anika Kiara Navya Pari Riya Kavya Ishita Tanvi Meera Aanya Sara Aditi Shreya Pooja Nisha Sneha Kritika Muskan Simran Anjali Palak Vaidehi Tara Avni Bhavya Charvi Disha Esha Garima Hiya Jiya Khushi Lavanya Mahi".split()
LAST = "Sharma Verma Gupta Singh Kumar Agarwal Mehta Joshi Chauhan Yadav Tripathi Mishra Pandey Saxena Bansal Jain Malhotra Kapoor Khanna Arora Bhatia Chopra Sethi Tiwari Dubey Rawat Negi Bisht Thakur Rana Nair Menon Iyer Reddy Patel Shah Desai Kulkarni Das Roy Ghosh Banerjee Sinha Jha Mathur Goel Garg Rastogi Soni Dahiya Hooda".split()
STAFF_FIRST = "Neha Amit Rajesh Divya Sanjay Meenakshi Vikram Anita Suresh Kavita Manoj Rekha".split()
COMMENTS = ["Clear explanations and good examples.", "Needs more practice problems before the quiz.", "Labs were very useful.",
            "Please share slides earlier.", "Pace is a little fast in the second half.", "Assignments matched what was taught.",
            "Doubt-clearing sessions help a lot.", "Would like more real-world case studies."]
REQUESTS = [("bonafide_certificate", "Bonafide certificate for education loan"), ("id_card", "Replacement ID card"),
            ("grievance", "Lab systems not working in Lab 2"), ("attendance_correction", "Attendance not reflected for a class I attended"),
            ("transcript", "Provisional transcript request"), ("fee_issue", "Fee receipt shows wrong amount"), ("other", "Hostel NOC request")]
OUTLINE = """# {code} · {title}

Credits: {credits} · Section {section} · Term: {term}

## Units
{units}

## Weekly plan
Classes follow the timetable in the portal. Attendance is taken by QR scan at the start of every class (minimum {th}% required).

## Evaluation
Assignments {aw}% and quizzes {qw}% of the continuous-assessment component; attendance below {th}% carries a deduction (see the report card).

## How to use this site
Upload your assignment links under *My Courses → {code}*. Quizzes appear in the Assessment hub.
"""


def profile(seed, student_id):
    """(attendance habit, academic ability) for one student - the same every time for the same seed."""
    r = random.Random(f"{seed}:{student_id}")
    u = r.random()
    p = r.uniform(0.55, 0.72) if u < 0.12 else r.uniform(0.72, 0.86) if u < 0.40 else r.uniform(0.86, 0.985)
    ability = min(0.97, max(0.30, 0.35 + 0.45 * (p - 0.55) / 0.43 + r.gauss(0.12, 0.13)))
    return p, ability


def sql_time(t):
    return time(t // 60, t % 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", type=int, default=4)
    ap.add_argument("--section-size", type=int, default=60)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--today", default=None, help="pretend it is this date (YYYY-MM-DD)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    today = date.fromisoformat(args.today) if args.today else date.today()
    qr_start = date(2026, 10, 26)           # QR attendance rolled out for the Phase-1 evaluation

    conn = db.get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SET @suppress_notifications = 1, @app_user = 'seed-loader'")
    cur.execute("SELECT COUNT(*) AS n FROM student")
    if cur.fetchone()["n"] > 50 and not args.force:
        sys.exit("The database already holds more than 50 students. Use --force to add anyway.")

    def q(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchall()

    term = q("SELECT * FROM academic_term WHERE is_current")[0]
    prev_term = q("SELECT * FROM academic_term WHERE term_id <> %s ORDER BY start_date DESC LIMIT 1", (term["term_id"],))[0]
    cse_courses = q("""SELECT c.* FROM course c JOIN program_course pc ON pc.course_id = c.course_id
                         WHERE pc.semester = 3 ORDER BY c.course_id""")
    ds = q("SELECT * FROM course WHERE course_code = 'ETCCDS201'")[0]
    total = args.sections * args.section_size
    print(f"Generating {total} students in {args.sections} sections ...")

    # ---------------------------------------------------------------- instructors
    n_inst = q("SELECT COUNT(*) AS n FROM instructor")[0]["n"]
    desig = ["Associate Professor", "Assistant Professor", "Assistant Professor", "Lecturer", "Professor", "Assistant Professor"]
    for i in range(12):
        code = f"EMP{1006 + i}"
        if q("SELECT 1 FROM instructor WHERE employee_code = %s", (code,)):
            continue
        first, last = STAFF_FIRST[i % len(STAFF_FIRST)], rnd.choice(LAST)
        dept = 3 if i in (3, 9) else 1
        cur.execute("""INSERT INTO instructor (employee_code, first_name, last_name, email, department_id, designation, hire_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (code, first, last, f"{first}.{last}.{code[-4:]}@college.edu".lower(), dept, desig[i % len(desig)],
                     date(2012 + i % 10, 7, 1)))
    cse_staff = [r["instructor_id"] for r in q("""SELECT instructor_id FROM instructor WHERE department_id = 1
                                                   AND designation <> 'Teaching Assistant' ORDER BY instructor_id""")]
    hum_staff = [r["instructor_id"] for r in q("SELECT instructor_id FROM instructor WHERE department_id = 3 ORDER BY instructor_id")]

    # ---------------------------------------------------------------- students
    existing_rolls = {r["roll_number"] for r in q("SELECT roll_number FROM student")}
    base = 2501730000
    n_other = q("SELECT COUNT(*) AS n FROM student WHERE roll_number NOT BETWEEN %s AND %s", (str(base + 1), str(base + total)))[0]["n"]
    new_rows = []
    for i in range(1, total - n_other + 1):
        roll = str(base + i)
        if roll in existing_rolls:
            continue
        female = rnd.random() < 0.38
        first = rnd.choice(FIRST_F if female else FIRST_M)
        last = rnd.choice(LAST)
        new_rows.append((roll, first, last, f"{first}.{last}.{roll[-4:]}@student.college.edu".lower(),
                         f"9{rnd.randint(100000000, 999999999)}", date(2006, 1, 1) + timedelta(days=rnd.randint(0, 700)), 1, 2025, 3))
    cur.executemany("""INSERT INTO student (roll_number, first_name, last_name, email, phone, date_of_birth, program_id,
                                            admission_year, current_semester) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""", new_rows)
    students = q("SELECT student_id, roll_number FROM student WHERE roll_number BETWEEN %s AND %s ORDER BY roll_number",
                 (str(base + 1), str(base + total)))
    sec_of = {}
    # seed students outside this roll range (other batches) already sit in section A and use up seats there
    others = q("SELECT COUNT(*) AS n FROM student WHERE roll_number NOT BETWEEN %s AND %s", (str(base + 1), str(base + total)))[0]["n"]
    for idx, s in enumerate(students):
        sec_of[s["student_id"]] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(idx + others) // args.section_size]
    sections = sorted(set(sec_of.values()))
    # each student has a steady attendance habit and an academic ability; the two are loosely related
    habit, ability = {}, {}
    for r_ in q("SELECT student_id FROM student"):
        habit[r_["student_id"]], ability[r_["student_id"]] = profile(args.seed, r_["student_id"])

    # ---------------------------------------------------------------- offerings per section
    cur.execute("UPDATE course_offering SET max_capacity = 60 WHERE max_capacity < 60 AND section_code = 'A'")
    offering = {}      # (course_id, term_id, section) -> offering_id
    for r in q("SELECT offering_id, course_id, term_id, section_code FROM course_offering"):
        offering[(r["course_id"], r["term_id"], r["section_code"])] = r["offering_id"]
    for c in cse_courses + [ds]:
        tid = prev_term["term_id"] if c["course_id"] == ds["course_id"] else term["term_id"]
        a_row = q("SELECT * FROM course_offering WHERE course_id = %s AND term_id = %s AND section_code = 'A'", (c["course_id"], tid))[0]
        for s_idx, sec in enumerate(sections):
            if (c["course_id"], tid, sec) in offering:
                continue
            cur.execute("""INSERT INTO course_offering (course_id, term_id, section_code, max_capacity, assignment_weight, quiz_weight)
                           VALUES (%s, %s, %s, 60, %s, %s)""", (c["course_id"], tid, sec, a_row["assignment_weight"], a_row["quiz_weight"]))
            oid = cur.lastrowid
            offering[(c["course_id"], tid, sec)] = oid
            pool = hum_staff if c["department_id"] == 3 else cse_staff
            cur.execute("INSERT INTO offering_instructor (offering_id, instructor_id, role) VALUES (%s, %s, 'primary')",
                        (oid, pool[(c["course_id"] + s_idx) % len(pool)]))
            # modules copied from section A
            cur.execute("""INSERT INTO module (offering_id, module_number, title)
                           SELECT %s, module_number, title FROM module WHERE offering_id = %s""", (oid, a_row["offering_id"]))
    primary = {r["offering_id"]: r["instructor_id"] for r in q(
        "SELECT offering_id, instructor_id FROM offering_instructor WHERE role = 'primary'")}

    # ---------------------------------------------------------------- enrolments
    rows = []
    for s in students:
        sec = sec_of[s["student_id"]]
        rows.append((s["student_id"], offering[(ds["course_id"], prev_term["term_id"], sec)], date(2026, 1, 14), "completed"))
    done = {(r["student_id"], r["offering_id"]) for r in q("SELECT student_id, offering_id FROM enrollment")}
    cur.executemany("INSERT INTO enrollment (student_id, offering_id, enrolled_on, status) VALUES (%s, %s, %s, %s)",
                    [r for r in rows if (r[0], r[1]) not in done])
    rows = []
    for s in students:
        for c in cse_courses:
            oid = offering[(c["course_id"], term["term_id"], sec_of[s["student_id"]])]
            if (s["student_id"], oid) not in done:
                rows.append((s["student_id"], oid, date(2026, 7, 28), "enrolled"))
    for r in rows:      # one by one: the capacity trigger counts every row, and a clear error beats a batch failure
        try:
            cur.execute("INSERT INTO enrollment (student_id, offering_id, enrolled_on, status) VALUES (%s, %s, %s, %s)", r)
        except Exception as err:  # noqa: BLE001
            sys.exit(f"Could not enrol student {r[0]} (section {sec_of.get(r[0])}) in offering {r[1]}: {err}; now {q('SELECT COUNT(*) n FROM enrollment WHERE offering_id=%s AND status<>%s', (r[1], 'dropped'))[0]['n']} taken, cap {q('SELECT max_capacity c FROM course_offering WHERE offering_id=%s', (r[1],))[0]['c']}; by status {q('SELECT status, COUNT(*) n, MIN(student_id) lo, MAX(student_id) hi FROM enrollment WHERE offering_id=%s GROUP BY status', (r[1],))}; secA={sum(1 for v in sec_of.values() if v=='A')}")
    print(f"  enrolments: {len(rows)} (+ {total} completed prerequisite records)")

    term_offerings = {sec: [offering[(c["course_id"], term["term_id"], sec)] for c in cse_courses] for sec in sections}
    all_off = [o for lst in term_offerings.values() for o in lst]

    # ---------------------------------------------------------------- holidays
    for d, name, kind in [("2026-08-15", "Independence Day", "public"), ("2026-10-02", "Gandhi Jayanti", "public"),
                          ("2026-10-20", "Dussehra", "public"), ("2026-11-08", "Diwali", "public"),
                          ("2026-11-09", "Diwali break", "institute"), ("2026-12-25", "Christmas", "public"),
                          ("2026-09-21", "Mid-semester break (day 1)", "exam_break"), ("2026-09-22", "Mid-semester break (day 2)", "exam_break")]:
        cur.execute("INSERT IGNORE INTO holiday (holiday_date, name, kind) VALUES (%s, %s, %s)", (d, name, kind))

    # ---------------------------------------------------------------- timetable (greedy, no clashes)
    periods = [(9 * 60, 10 * 60), (10 * 60, 11 * 60), (11 * 60, 12 * 60), (12 * 60, 13 * 60),
               (14 * 60, 15 * 60), (15 * 60, 16 * 60), (16 * 60, 17 * 60)]
    pattern = {"ETCCMS304": ["lecture"] * 3 + ["lab2"], "ETCCDA302": ["lecture"] * 3 + ["tutorial"], "ETCCML301": ["lecture"] * 3,
               "ETCCCC303": ["lab2"], "ETCCHW305": ["lecture"] * 2 + ["lab2"], "AEC006": ["lecture"] * 2}
    busy_sec, busy_inst, busy_room = set(), set(), set()
    cur.execute("DELETE FROM timetable_slot WHERE offering_id IN (%s)" % ",".join(["%s"] * len(all_off)), all_off)
    slots = []
    # section A keeps the weekly slot it already had in the seed (sessions already exist for it)
    for c in cse_courses:
        oid = offering[(c["course_id"], term["term_id"], "A")]
        for r in q("""SELECT DISTINCT (DAYOFWEEK(session_date) + 5) % 7 + 1 AS dow, start_time, end_time FROM class_session
                       WHERE offering_id = %s AND session_date < %s""", (oid, qr_start)):
            st = int(r["start_time"].total_seconds() // 60)
            p = next((i for i, (a, b) in enumerate(periods) if a == st), None)
            if p is None:
                continue
            slots.append((oid, r["dow"], periods[p][0], periods[p][1], f"LH-{101}", "lecture"))
            busy_sec.add(("A", r["dow"], p)); busy_inst.add((primary[oid], r["dow"], p)); busy_room.add((f"LH-101", r["dow"], p))
    first_done = {(s[0], s[1]) for s in slots}
    for s_idx, sec in enumerate(sections):
        for c_idx, c in enumerate(cse_courses):
            oid = offering[(c["course_id"], term["term_id"], sec)]
            inst = primary[oid]
            days_used = {s[1] for s in slots if s[0] == oid}
            kinds = list(pattern.get(c["course_code"], ["lecture"] * 2))
            if sec == "A":                       # one lecture hour already placed from the seed
                kinds = kinds[1:] if "lecture" in kinds and any(s[0] == oid for s in slots) else kinds
            for kind in kinds:
                need = 2 if kind == "lab2" else 1
                placed = False
                order = [(d, p) for d in range(1, 6) for p in range(len(periods))]
                rnd.shuffle(order)
                for d, p in order:
                    if need == 2 and (p in (3, 6) or p + 1 >= len(periods) or (p < 4) != (p + 1 < 4)):
                        continue
                    cells = [p + k for k in range(need)]
                    room = (f"LAB-{1 + (s_idx + c_idx) % 4}" if kind == "lab2" else f"LH-{101 + s_idx}")
                    if d in days_used and kind != "lab2":
                        continue
                    if any((sec, d, x) in busy_sec or (inst, d, x) in busy_inst or (room, d, x) in busy_room for x in cells):
                        continue
                    for x in cells:
                        busy_sec.add((sec, d, x)); busy_inst.add((inst, d, x)); busy_room.add((room, d, x))
                    days_used.add(d)
                    slots.append((oid, d, periods[p][0], periods[p + need - 1][1], room, "lab" if kind == "lab2" else kind))
                    placed = True
                    break
                if not placed:
                    print(f"  warning: could not place a {kind} for {c['course_code']} section {sec}")
    cur.executemany("""INSERT IGNORE INTO timetable_slot (offering_id, day_of_week, start_time, end_time, room, slot_type)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    [(o, d, sql_time(a), sql_time(b), r, k) for (o, d, a, b, r, k) in slots])
    print(f"  timetable slots: {len(slots)}")
    for oid in all_off:
        cur.callproc("sp_generate_sessions", (oid, term["start_date"], term["end_date"]))
        [r.fetchall() for r in cur.stored_results()]

    # topics, spread across the modules in order
    for oid in all_off:
        mods = [m["title"] for m in q("SELECT title FROM module WHERE offering_id = %s ORDER BY module_number", (oid,))]
        sess = q("SELECT session_id, session_date FROM class_session WHERE offering_id = %s ORDER BY session_date, start_time", (oid,))
        if not mods:
            continue
        cur.executemany("UPDATE class_session SET topic = %s WHERE session_id = %s AND topic IS NULL",
                        [(f"{mods[min(len(mods) - 1, i * len(mods) // len(sess))]} (class {i + 1})", s["session_id"]) for i, s in enumerate(sess)])

    # ---------------------------------------------------------------- attendance (past classes only; today stays open for the QR demo)
    enrolled = q("""SELECT e.enrollment_id, e.student_id, e.offering_id FROM enrollment e
                      WHERE e.status = 'enrolled' AND e.offering_id IN (%s)""" % ",".join(["%s"] * len(all_off)), all_off)
    by_off = {}
    for e in enrolled:
        by_off.setdefault(e["offering_id"], []).append(e)
    batch, count = [], 0
    for oid in all_off:
        for s in q("""SELECT session_id, session_date, start_time FROM class_session
                       WHERE offering_id = %s AND session_date < %s""", (oid, today)):
            have = {r["enrollment_id"] for r in q("SELECT enrollment_id FROM attendance WHERE session_id = %s", (s["session_id"],))}
            start = datetime.combine(s["session_date"], (datetime.min + s["start_time"]).time())
            for e in by_off.get(oid, []):
                if e["enrollment_id"] in have:
                    continue
                present = rnd.random() < habit[e["student_id"]]
                if present:
                    status = "late" if rnd.random() < 0.07 else "present"
                else:
                    status = "excused" if rnd.random() < 0.03 else "absent"
                via = "qr" if (s["session_date"] >= qr_start and present and rnd.random() < 0.88) else "manual"
                marked = start + timedelta(minutes=rnd.randint(1, 14)) if via == "qr" else start + timedelta(minutes=rnd.randint(50, 65))
                batch.append((s["session_id"], e["enrollment_id"], status, via, marked))
            if len(batch) >= 4000:
                cur.executemany("INSERT INTO attendance (session_id, enrollment_id, status, marked_via, marked_at) VALUES (%s, %s, %s, %s, %s)", batch)
                count += len(batch); batch = []
    if batch:
        cur.executemany("INSERT INTO attendance (session_id, enrollment_id, status, marked_via, marked_at) VALUES (%s, %s, %s, %s, %s)", batch)
        count += len(batch)
    print(f"  attendance rows: {count}")

    # ---------------------------------------------------------------- assignments and submissions
    specs = [("Assignment 1", date(2026, 9, 14), 20), ("Assignment 2", date(2026, 10, 19), 20), ("Assignment 3", date(2026, 12, 7), 30)]
    sub_rows = 0
    for oid in all_off:
        have_titles = {r["title"] for r in q("SELECT title FROM assignment WHERE offering_id = %s", (oid,))}
        for title, due, mx in specs:
            if title not in have_titles:
                cur.execute("""INSERT INTO assignment (offering_id, title, description, max_marks, assigned_on, due_date, allow_late)
                               VALUES (%s, %s, %s, %s, %s, %s, 0)""",
                            (oid, title, "Graded assignment covering the recent modules. Submit a link to your work.", mx,
                             datetime.combine(due - timedelta(days=21), time(9, 0)), datetime.combine(due, time(23, 59))))
        asg = q("SELECT assignment_id, due_date, max_marks FROM assignment WHERE offering_id = %s", (oid,))
        done_sub = {(r["assignment_id"], r["enrollment_id"]) for r in q(
            "SELECT s.assignment_id, s.enrollment_id FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id WHERE a.offering_id = %s", (oid,))}
        batch = []
        for a in asg:
            past = a["due_date"].date() < today
            for e in by_off.get(oid, []):
                if (a["assignment_id"], e["enrollment_id"]) in done_sub:
                    continue
                ab = ability[e["student_id"]]
                if past and rnd.random() < 0.06 + (0.9 - habit[e["student_id"]]) * 0.25:
                    continue                                   # missed it
                if not past and rnd.random() > 0.22:
                    continue                                   # only early birds have submitted a future deadline
                sub_on = a["due_date"] - timedelta(hours=rnd.randint(1, 120)) if past else datetime.combine(today, time(rnd.randint(8, 20), 15)) - timedelta(days=rnd.randint(0, 6))
                if past:
                    marks = round(float(a["max_marks"]) * min(1, max(0.25, rnd.gauss(ab, 0.10))) * 2) / 2
                    batch.append((a["assignment_id"], e["enrollment_id"], sub_on, f"https://github.com/student-{e['student_id']}/{a['assignment_id']}",
                                  marks, primary[oid], a["due_date"] + timedelta(days=rnd.randint(2, 6)), None))
                else:
                    batch.append((a["assignment_id"], e["enrollment_id"], sub_on, f"https://github.com/student-{e['student_id']}/{a['assignment_id']}",
                                  None, None, None, None))
        cur.executemany("""INSERT INTO submission (assignment_id, enrollment_id, submitted_on, content_url, marks_obtained, graded_by, graded_on, feedback)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", batch)
        sub_rows += len(batch)
    print(f"  assignments/submissions: {sub_rows}")

    # ---------------------------------------------------------------- quizzes (cloned from section A, attempts scored in SQL)
    for c in cse_courses:
        a_off = offering[(c["course_id"], term["term_id"], "A")]
        for qz in q("SELECT * FROM quiz WHERE offering_id = %s", (a_off,)):
            for sec in sections:
                oid = offering[(c["course_id"], term["term_id"], sec)]
                if sec == "A" or q("SELECT 1 FROM quiz WHERE offering_id = %s AND title = %s", (oid, qz["title"])):
                    continue
                cur.execute("""INSERT INTO quiz (offering_id, title, time_limit_minutes, max_attempts, available_from, available_until)
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            (oid, qz["title"], qz["time_limit_minutes"], qz["max_attempts"], qz["available_from"], qz["available_until"]))
                new_q = cur.lastrowid
                for qq in q("SELECT * FROM question WHERE quiz_id = %s", (qz["quiz_id"],)):
                    cur.execute("INSERT INTO question (quiz_id, question_text, marks) VALUES (%s, %s, %s)", (new_q, qq["question_text"], qq["marks"]))
                    nq = cur.lastrowid
                    cur.execute("""INSERT INTO question_option (question_id, option_text, is_correct)
                                   SELECT %s, option_text, is_correct FROM question_option WHERE question_id = %s ORDER BY option_id""", (nq, qq["question_id"]))
    attempts = 0
    for qz in q("SELECT * FROM quiz WHERE available_until < %s ORDER BY quiz_id", (datetime.combine(today, time(0, 0)),)):
        oid = qz["offering_id"]
        enr = [e for e in by_off.get(oid, [])]
        existing = {r["enrollment_id"] for r in q("SELECT enrollment_id FROM quiz_attempt WHERE quiz_id = %s", (qz["quiz_id"],))}
        todo = [e for e in enr if e["enrollment_id"] not in existing and rnd.random() < 0.9]
        if not todo:
            continue
        questions = q("SELECT question_id FROM question WHERE quiz_id = %s", (qz["quiz_id"],))
        opts = {x["question_id"]: q("SELECT option_id, is_correct FROM question_option WHERE question_id = %s", (x["question_id"],)) for x in questions}
        cur.execute("UPDATE quiz SET available_from = NOW() - INTERVAL 1 DAY, available_until = NOW() + INTERVAL 1 DAY WHERE quiz_id = %s", (qz["quiz_id"],))
        for e in todo:
            cur.execute("INSERT INTO quiz_attempt (quiz_id, enrollment_id) VALUES (%s, %s)", (qz["quiz_id"], e["enrollment_id"]))
            aid = cur.lastrowid
            ab = ability[e["student_id"]]
            ans = []
            for x in questions:
                right = [o for o in opts[x["question_id"]] if o["is_correct"]]
                wrong = [o for o in opts[x["question_id"]] if not o["is_correct"]]
                pick = (right[0] if right and rnd.random() < ab else rnd.choice(wrong or right))
                ans.append((aid, x["question_id"], pick["option_id"]))
            cur.executemany("INSERT INTO quiz_answer (attempt_id, question_id, selected_option_id) VALUES (%s, %s, %s)", ans)
            when = qz["available_from"] + timedelta(minutes=rnd.randint(5, 600))
            cur.execute("""UPDATE quiz_attempt SET attempted_on = %s, submitted_on = %s,
                                  score = (SELECT COALESCE(SUM(qs.marks), 0) FROM quiz_answer an JOIN question qs ON qs.question_id = an.question_id
                                             JOIN question_option o ON o.option_id = an.selected_option_id AND o.is_correct = 1
                                            WHERE an.attempt_id = %s) WHERE attempt_id = %s""",
                        (when, when + timedelta(minutes=rnd.randint(6, max(7, qz["time_limit_minutes"] - 1))), aid, aid))
            attempts += 1
        cur.execute("UPDATE quiz SET available_from = %s, available_until = %s WHERE quiz_id = %s",
                    (qz["available_from"], qz["available_until"], qz["quiz_id"]))
    print(f"  quiz attempts: {attempts}")

    # ---------------------------------------------------------------- study material (course outline per section + per-module reading list)
    made = 0
    for sec in sections:
        for c, oid in zip(cse_courses, term_offerings[sec]):
            mods = q("SELECT module_id, module_number, title FROM module WHERE offering_id = %s ORDER BY module_number", (oid,))
            if not mods or q("SELECT 1 FROM material ma JOIN module m ON m.module_id = ma.module_id WHERE m.offering_id = %s AND ma.stored_name IS NOT NULL", (oid,)):
                continue
            wts = q("SELECT assignment_weight, quiz_weight FROM course_offering WHERE offering_id = %s", (oid,))[0]
            text = OUTLINE.format(code=c["course_code"], title=c["title"], credits=c["credits"], section=sec, term=term["term_name"],
                                  units="\n".join(f"{m['module_number']}. {m['title']}" for m in mods), th=Config.ATTENDANCE_THRESHOLD,
                                  aw=int(wts["assignment_weight"]), qw=int(wts["quiz_weight"]))
            folder = Config.UPLOAD_DIR / "materials" / str(oid)
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.md"
            (folder / name).write_text(text, encoding="utf-8")
            cur.execute("""INSERT INTO material (module_id, title, description, material_type, stored_name, original_name, file_size, mime_type, uploaded_by, uploaded_on)
                           VALUES (%s, %s, %s, 'other', %s, %s, %s, 'text/markdown', %s, %s)""",
                        (mods[0]["module_id"], "Course outline and evaluation scheme", "Units, weekly plan and how marks are calculated",
                         name, f"{c['course_code']}-outline.md", len(text.encode()), primary[oid], term["start_date"]))
            made += 1
    print(f"  uploaded files: {made}")

    # ---------------------------------------------------------------- notifications (backdated)
    notes = [("all", "general", "Welcome to the odd semester", "Classes begin on 3 August. Check your timetable and register for courses.", date(2026, 8, 1)),
             ("students", "fees", "Tuition fee due date", "Pay the semester fee by 31 August at the accounts office.", date(2026, 8, 10)),
             ("all", "exam", "Mid-semester break", "No classes on 21 and 22 September.", date(2026, 9, 10)),
             ("students", "academic", "Attendance rule", f"Students below {Config.ATTENDANCE_THRESHOLD}% attendance may be barred from the end-semester exam.", date(2026, 10, 5)),
             ("students", "event", "QR attendance starts", "From 26 October, attendance is marked by scanning the QR code shown in class.", date(2026, 10, 24)),
             ("all", "event", "Diwali break", "The campus is closed on 8 and 9 November.", date(2026, 11, 5)),
             ("students", "exam", "End-semester examination form", "Fill the exam form in the Assessment hub before 5 December.", date(2026, 11, 18))]
    cur.executemany("INSERT INTO notification (audience, category, title, body, created_at) VALUES (%s, %s, %s, %s, %s)",
                    [(a, c_, t, b, datetime.combine(d, time(9, 30))) for a, c_, t, b, d in notes])
    for oid in all_off:
        cur.execute("""INSERT INTO notification (audience, offering_id, category, title, body, created_at)
                       VALUES ('offering', %s, 'academic', 'Welcome to the course', 'Read the course outline under Study material before the first class.', %s)""",
                    (oid, datetime.combine(term["start_date"], time(8, 0))))
    cur.execute("""INSERT INTO notification (audience, offering_id, category, title, body, created_at)
                   SELECT 'offering', a.offering_id, 'academic', CONCAT('New assignment: ', a.title),
                          CONCAT('Due ', DATE_FORMAT(a.due_date, '%d %b %Y, %H:%i'), '. Max marks ', a.max_marks, '.'), a.assigned_on
                     FROM assignment a WHERE a.assigned_on <= NOW()""")

    # ---------------------------------------------------------------- fees
    inv = [("Tuition fee", 85000, date(2026, 8, 31)), ("Examination and library fee", 6500, date(2026, 9, 15))]
    pay_rows = 0
    for s in students:
        for desc, amt, due in inv:
            cur.execute("INSERT INTO fee_invoice (student_id, term_id, description, amount, due_date) VALUES (%s, %s, %s, %s, %s)",
                        (s["student_id"], term["term_id"], f"{desc} - {term['term_name']}", amt, due))
            iid = cur.lastrowid
            u = rnd.random()
            if u < 0.86:
                parts = [amt]
            elif u < 0.93:
                parts = [round(amt * 0.5, 2)]
            else:
                continue
            for part in parts:
                mode = rnd.choice(["upi", "netbanking", "card", "neft", "upi"])
                cur.execute("INSERT INTO fee_payment (invoice_id, amount, paid_on, mode, reference_no) VALUES (%s, %s, %s, %s, %s)",
                            (iid, part, datetime.combine(due - timedelta(days=rnd.randint(0, 12)), time(rnd.randint(9, 18), rnd.randint(0, 59))),
                             mode, f"{mode.upper()[:3]}{rnd.randint(10**9, 10**10 - 1)}"))
                pay_rows += 1
    print(f"  fee payments: {pay_rows}")

    # ---------------------------------------------------------------- feedback, requests, mentors
    fb = 0
    for e in enrolled:
        if rnd.random() < 0.35:
            r = lambda: min(5, max(1, int(round(rnd.gauss(4.0, 0.9)))))
            cur.execute("""INSERT INTO course_feedback (enrollment_id, rating_content, rating_teaching, rating_assessment, comment, submitted_on)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (e["enrollment_id"], r(), r(), r(), rnd.choice(COMMENTS) if rnd.random() < 0.6 else None,
                         datetime.combine(today - timedelta(days=rnd.randint(0, 20)), time(rnd.randint(9, 22), 5))))
            fb += 1
    for s in rnd.sample(students, min(len(students), max(12, total // 10))):
        cat, subj = rnd.choice(REQUESTS)
        status = rnd.choices(["open", "in_progress", "resolved", "rejected"], [3, 2, 5, 1])[0]
        created = datetime.combine(today - timedelta(days=rnd.randint(1, 40)), time(rnd.randint(9, 17), 0))
        cur.execute("""INSERT INTO service_request (student_id, category, subject, description, status, response, resolved_on, created_on)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (s["student_id"], cat, subj, "Please look into this at the earliest.", status,
                     "Done. Collect it from the department office." if status == "resolved" else ("Not applicable." if status == "rejected" else None),
                     created + timedelta(days=2) if status in ("resolved", "rejected") else None, created))
    if cse_staff:
        cur.executemany("INSERT IGNORE INTO mentorship (student_id, instructor_id) VALUES (%s, %s)",
                        [(s["student_id"], cse_staff[i % len(cse_staff)]) for i, s in enumerate(students)])
    print(f"  feedback: {fb}")

    # ---------------------------------------------------------------- results (provisional, as the admin button would)
    for oid in all_off:
        cur.callproc("sp_calculate_offering_results", (oid,))
        [r.fetchall() for r in cur.stored_results()]
    conn.commit()
    conn.close()
    print("Done. Run  python create_users.py  to give the new people logins.")


if __name__ == "__main__":
    main()
