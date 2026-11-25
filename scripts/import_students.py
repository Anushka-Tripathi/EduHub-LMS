#!/usr/bin/env python3
"""Loads your real student roster from CSV (replaces the generated people).

  data/roster/students.csv  columns:
      roll_number,first_name,last_name,email,phone,date_of_birth,program,admission_year,current_semester,section
  date_of_birth is YYYY-MM-DD. `program` must match a programme name (e.g. B.Tech CSE (AI & ML)).
  If `section` is filled, the student is enrolled in that section of every current-term course that the
  curriculum (program_course) lists for their semester. Seats, prerequisites and capacity are enforced by
  the database, so rows that cannot be enrolled are reported, not silently skipped.

  python scripts/import_students.py data/roster/students.csv [--dry-run]
Afterwards run  python create_users.py  to create their logins.
"""
import argparse
import csv
import sys
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.csv_file, newline="", encoding="utf-8-sig")))
    conn = db.get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SET @app_user = 'roster-import'")
    added = enrolled = 0
    problems = []
    for n, r in enumerate(rows, start=2):
        try:
            cur.execute("SELECT program_id FROM program WHERE program_name = %s", (r["program"].strip(),))
            prog = cur.fetchone()
            if not prog:
                raise ValueError(f"unknown programme '{r['program']}'")
            cur.execute("""INSERT INTO student (roll_number, first_name, last_name, email, phone, date_of_birth, program_id, admission_year, current_semester)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE first_name = VALUES(first_name), last_name = VALUES(last_name), email = VALUES(email),
                                                   phone = VALUES(phone), current_semester = VALUES(current_semester)""",
                        (r["roll_number"].strip(), r["first_name"].strip(), r["last_name"].strip(), r["email"].strip(), r.get("phone") or None,
                         r.get("date_of_birth") or None, prog["program_id"], int(r["admission_year"]), int(r["current_semester"])))
            added += 1
            sec = (r.get("section") or "").strip()
            if sec:
                cur.execute("SELECT student_id FROM student WHERE roll_number = %s", (r["roll_number"].strip(),))
                sid = cur.fetchone()["student_id"]
                cur.execute("""SELECT o.offering_id FROM course_offering o JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
                                 JOIN program_course pc ON pc.course_id = o.course_id AND pc.program_id = %s AND pc.semester = %s
                                WHERE o.section_code = %s""", (prog["program_id"], int(r["current_semester"]), sec))
                for off in cur.fetchall():
                    try:
                        cur.callproc("sp_enroll_student", (sid, off["offering_id"]))
                        enrolled += 1
                    except mysql.connector.Error as err:
                        if "already enrolled" not in str(err):
                            problems.append(f"line {n} {r['roll_number']}: offering {off['offering_id']}: {err.msg}")
        except (ValueError, KeyError, mysql.connector.Error) as err:
            problems.append(f"line {n} {r.get('roll_number', '?')}: {getattr(err, 'msg', err)}")
    if a.dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()
    print(f"{'(dry run) ' if a.dry_run else ''}students written: {added}, enrolments made: {enrolled}, problems: {len(problems)}")
    for p in problems[:30]:
        print("  -", p)


if __name__ == "__main__":
    main()
