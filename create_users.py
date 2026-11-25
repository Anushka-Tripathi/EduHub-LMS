"""Creates login accounts for people who do not have one yet.

  python create_users.py              demo passwords (admin123 / teach123 / learn123), for classroom demos
  python create_users.py --secure     random one-time passwords, written to credentials_<date>.csv;
                                      every account must change its password at first login
  admin           admin
  instructors     employee code (EMP1002)
  students        roll number (2501730001)
"""
import csv
import secrets
import sys
from datetime import date

from werkzeug.security import generate_password_hash

import db

SECURE = "--secure" in sys.argv
DEMO = {"admin": "admin123", "instructor": "teach123", "student": "learn123"}

conn = db.get_conn()
cur = conn.cursor()
cur.execute("SELECT username FROM user_account")
existing = {r[0] for r in cur.fetchall()}
issued = []


def add(username, role, student_id=None, instructor_id=None):
    if username in existing:
        return 0
    password = (secrets.token_urlsafe(9) + "7") if SECURE else DEMO[role]
    cur.execute(
        "INSERT INTO user_account (username, password_hash, role, student_id, instructor_id, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (username, generate_password_hash(password), role, student_id, instructor_id, SECURE))
    issued.append((username, role, password))
    return 1


created = add("admin", "admin")
cur.execute("SELECT instructor_id, employee_code FROM instructor")
for iid, code in cur.fetchall():
    created += add(code, "instructor", instructor_id=iid)
cur.execute("SELECT student_id, roll_number FROM student")
batch = cur.fetchall()
for sid, roll in batch:
    created += add(roll, "student", student_id=sid)
conn.commit()
conn.close()
print(f"Created {created} accounts.")
if SECURE and issued:
    name = f"credentials_{date.today().isoformat()}.csv"
    with open(name, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([("username", "role", "one_time_password")] + issued)
    print(f"One-time passwords written to {name}. Hand them out, then delete the file.")
