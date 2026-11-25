#!/usr/bin/env python3
"""Small load test against a running server (no extra packages needed).

  python scripts/load_test.py --base http://127.0.0.1:8000 [--students 58] [--pages 20]

Scenario 1  "classroom rush": the instructor opens QR attendance and every student of one section
            logs in and scans within the same second.
Scenario 2  "page latency": logged-in students open the heaviest pages repeatedly.
It creates a temporary class session for today and removes it afterwards.
"""
import argparse
import http.cookiejar
import re
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


class Browser:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, path):
        t = time.perf_counter()
        with self.op.open(self.base + path, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
        return body, time.perf_counter() - t

    def post(self, path, data, form_page):
        data = dict(data, csrf_token=re.search(r'name="csrf_token" value="([^"]+)"', self.get(form_page)[0]).group(1))
        t = time.perf_counter()
        req = urllib.request.Request(self.base + path, urllib.parse.urlencode(data).encode())
        with self.op.open(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
        return body, time.perf_counter() - t

    def login(self, user, pw):
        return self.post("/login", {"username": user, "password": pw}, "/login")[1]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--students", type=int, default=58)
    ap.add_argument("--pages", type=int, default=15)
    a = ap.parse_args()

    off = db.query("""SELECT o.offering_id, i.employee_code FROM course_offering o
                       JOIN offering_instructor oi ON oi.offering_id = o.offering_id AND oi.role = 'primary'
                       JOIN instructor i USING (instructor_id) WHERE o.offering_id = 1""", one=True)
    studs = db.query("""SELECT s.roll_number, s.student_id FROM enrollment e JOIN student s USING (student_id)
                         WHERE e.offering_id = 1 AND e.status = 'enrolled' ORDER BY s.roll_number LIMIT %s""", (a.students,))
    sid = db.execute("""INSERT INTO class_session (offering_id, session_date, start_time, end_time, topic)
                        VALUES (1, CURDATE(), '00:01:00', '23:58:00', 'load test')""")
    try:
        teacher = Browser(a.base)
        teacher.login(off["employee_code"], "teach123")
        teacher.post(f"/instructor/session/{sid}/qr/open", {"minutes": 20, "late_after": 10}, f"/instructor/session/{sid}/qr")
        import json
        code = json.loads(teacher.get(f"/instructor/session/{sid}/qr/state")[0])["code"]

        browsers, login_t = [], []
        def do_login(roll):
            b = Browser(a.base); login_t.append(b.login(roll["roll_number"], "learn123")); browsers.append((b, roll))
        ts = [threading.Thread(target=do_login, args=(r,)) for r in studs]
        t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]
        print(f"{len(studs)} logins in {time.perf_counter() - t0:.1f}s  (each: median {statistics.median(login_t):.2f}s - password hashing is deliberately slow)")

        scan_t, ok, barrier = [], [], threading.Barrier(len(browsers))
        def do_scan(b, roll):
            tok = re.search(r'name="csrf_token" value="([^"]+)"', b.get("/student/scan")[0]).group(1)
            barrier.wait()
            t = time.perf_counter()
            req = urllib.request.Request(a.base + "/student/attendance/mark", urllib.parse.urlencode({"session_id": sid, "code": code, "csrf_token": tok}).encode())
            body = b.op.open(req, timeout=60).read().decode()
            scan_t.append(time.perf_counter() - t); ok.append("Attendance marked" in body)
        ts = [threading.Thread(target=do_scan, args=x) for x in browsers]
        t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]
        wall = time.perf_counter() - t0
        marked = db.query("SELECT COUNT(*) AS n FROM attendance WHERE session_id = %s AND marked_via = 'qr'", (sid,), one=True)["n"]
        print(f"QR rush: {len(scan_t)} simultaneous scans finished in {wall:.2f}s; median {statistics.median(scan_t):.2f}s, p95 {pct(scan_t, .95):.2f}s; "
              f"{sum(ok)} confirmed, {marked} rows in the database")

        lat = {}
        pages = ["/student", "/student/attendance", "/student/attendance?view=daywise", "/student/timetable", "/student/assessments", "/notifications"]
        def browse(b):
            for _ in range(a.pages):
                for p_ in pages:
                    lat.setdefault(p_, []).append(b.get(p_)[1])
        ts = [threading.Thread(target=browse, args=(b,)) for b, _ in browsers[:20]]
        t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]
        total = sum(len(v) for v in lat.values())
        print(f"Page latency: {total} requests by 20 concurrent students in {time.perf_counter() - t0:.1f}s ({total / (time.perf_counter() - t0):.0f} req/s)")
        for p_, v in lat.items():
            print(f"  {p_:<36} median {statistics.median(v) * 1000:6.0f} ms   p95 {pct(v, .95) * 1000:6.0f} ms")
    finally:
        db.execute("DELETE FROM class_session WHERE session_id = %s", (sid,))


if __name__ == "__main__":
    main()
