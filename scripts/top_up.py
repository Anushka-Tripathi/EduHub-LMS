#!/usr/bin/env python3
"""Brings the generated activity up to today.

Run it before a demo or evaluation: it fills attendance for every class held since the data was
generated (so the Attendance tab, shortage report and results are current) and leaves today's classes
open so you can run the QR flow live. Uses each student's stored habit, so numbers stay consistent.

  python scripts/top_up.py [--seed 2026] [--today YYYY-MM-DD]
"""
import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import db  # noqa: E402
from generate_scale_data import profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--today", default=None)
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else date.today()
    rnd = random.Random(f"topup:{a.seed}:{today}")
    conn = db.get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SET @app_user = 'top-up'")
    cur.execute("""SELECT cs.session_id, cs.session_date, cs.start_time, e.enrollment_id, e.student_id
                     FROM class_session cs
                     JOIN academic_term t ON cs.session_date BETWEEN t.start_date AND t.end_date AND t.is_current
                     JOIN enrollment e ON e.offering_id = cs.offering_id AND e.status = 'enrolled'
                     LEFT JOIN attendance a ON a.session_id = cs.session_id AND a.enrollment_id = e.enrollment_id
                    WHERE cs.session_date < %s AND a.session_id IS NULL
                    ORDER BY cs.session_id""", (today,))
    rows, cache = [], {}
    for r in cur.fetchall():
        habit = cache.setdefault(r["student_id"], profile(a.seed, r["student_id"])[0])
        present = rnd.random() < habit
        status = ("late" if rnd.random() < 0.07 else "present") if present else ("excused" if rnd.random() < 0.03 else "absent")
        via = "qr" if present and rnd.random() < 0.88 else "manual"
        start = datetime.combine(r["session_date"], (datetime.min + r["start_time"]).time())
        marked = start + (timedelta(minutes=rnd.randint(1, 14)) if via == "qr" else timedelta(minutes=rnd.randint(50, 65)))
        rows.append((r["session_id"], r["enrollment_id"], status, via, marked))
    cur2 = conn.cursor()
    for i in range(0, len(rows), 4000):
        cur2.executemany("INSERT INTO attendance (session_id, enrollment_id, status, marked_via, marked_at) VALUES (%s, %s, %s, %s, %s)", rows[i:i + 4000])
    conn.commit()
    conn.close()
    print(f"Added {len(rows)} attendance marks for classes before {today}. Today's classes are left open for QR.")


if __name__ == "__main__":
    main()
