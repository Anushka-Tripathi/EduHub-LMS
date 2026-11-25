#!/usr/bin/env python3
"""Loads the department course catalogue from CSV files into the database.

  data/catalog/courses.csv        course_code,title,credits,department_code,semester,program[,course_type]
  data/catalog/prerequisites.csv  course_code,prerequisite_code
  data/catalog/modules.csv        course_code,module_number,title      (syllabus units / sessions)

Safe to run again: rows are matched on course_code and updated, never duplicated.
Modules from modules.csv are copied into every offering of that course that has no modules yet
(pass --no-modules to skip).

To load a new handbook: put its course list into courses.csv in the same columns and run
    python scripts/import_catalog.py
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "catalog"))
    ap.add_argument("--no-modules", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir)
    conn = db.get_conn()
    cur = conn.cursor(dictionary=True)
    n_course = n_map = n_pre = n_mod = 0

    for r in read(d / "courses.csv"):
        code = r["course_code"].strip()
        cur.execute("SELECT department_id FROM department WHERE department_code = %s", (r["department_code"].strip(),))
        dep = cur.fetchone()
        if not dep:
            cur.execute("INSERT INTO department (department_code, department_name) VALUES (%s, %s)",
                        (r["department_code"].strip(), r["department_code"].strip()))
            dep = {"department_id": cur.lastrowid}
        cur.execute("""INSERT INTO course (course_code, title, credits, department_id) VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE title = VALUES(title), credits = VALUES(credits), department_id = VALUES(department_id)""",
                    (code, r["title"].strip(), int(r["credits"]), dep["department_id"]))
        n_course += 1
        cur.execute("SELECT course_id FROM course WHERE course_code = %s", (code,))
        cid = cur.fetchone()["course_id"]
        prog = (r.get("program") or "").strip()
        if prog and r.get("semester"):
            cur.execute("SELECT program_id FROM program WHERE program_name = %s", (prog,))
            p = cur.fetchone()
            if not p:
                cur.execute("""INSERT INTO program (program_name, department_id, degree_level, duration_years)
                               VALUES (%s, %s, 'Undergraduate', 4)""", (prog, dep["department_id"]))
                p = {"program_id": cur.lastrowid}
            cur.execute("""INSERT INTO program_course (program_id, course_id, semester, course_type) VALUES (%s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE semester = VALUES(semester), course_type = VALUES(course_type)""",
                        (p["program_id"], cid, int(r["semester"]), (r.get("course_type") or "core").strip()))
            n_map += 1

    if (d / "prerequisites.csv").exists():
        for r in read(d / "prerequisites.csv"):
            cur.execute("""INSERT IGNORE INTO course_prerequisite (course_id, prerequisite_course_id)
                           SELECT c.course_id, p.course_id FROM course c, course p
                            WHERE c.course_code = %s AND p.course_code = %s""",
                        (r["course_code"].strip(), r["prerequisite_code"].strip()))
            n_pre += cur.rowcount

    if not a.no_modules and (d / "modules.csv").exists():
        for r in read(d / "modules.csv"):
            cur.execute("""INSERT INTO module (offering_id, module_number, title)
                           SELECT o.offering_id, %s, %s FROM course_offering o JOIN course c ON c.course_id = o.course_id
                            WHERE c.course_code = %s
                              AND NOT EXISTS (SELECT 1 FROM module m WHERE m.offering_id = o.offering_id AND m.module_number = %s)""",
                        (int(r["module_number"]), r["title"].strip(), r["course_code"].strip(), int(r["module_number"])))
            n_mod += cur.rowcount
    conn.commit()
    conn.close()
    print(f"courses upserted: {n_course}, curriculum rows: {n_map}, new prerequisites: {n_pre}, modules added: {n_mod}")


if __name__ == "__main__":
    main()
