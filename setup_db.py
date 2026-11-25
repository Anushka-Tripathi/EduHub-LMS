#!/usr/bin/env python3
"""One command to build the whole database.

  python setup_db.py                 schema + seed + every phase + app login (empty-ish demo college)
  python setup_db.py --with-data     ...and grow it to a 240-student college with a year of activity
  python setup_db.py --with-benchmark   also builds elearning_bench (450k rows) for the Phase 3 EXPLAIN comparison
  python setup_db.py --secure-users  random one-time passwords instead of the demo ones

It needs a MySQL account that may create databases and users (DB_ADMIN_USER / DB_ADMIN_PASSWORD in .env,
default root). The web application itself never uses that account: it connects as DB_USER (lms_app),
which only holds lms_app_role (see database/phase4_security.sql).

WARNING: schema.sql drops and recreates elearning_db. Run it on a fresh install only.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import mysql.connector

import config  # noqa: F401  (loads .env)

ROOT = Path(__file__).resolve().parent
SQL = ROOT / "database"
ORDER = ["schema.sql", "seed.sql", "phase2_routines.sql", "phase2_data.sql", "phase2_tests.sql",
         "phase3_data.sql", "phase3_reports.sql", "phase3_apply_indexes.sql", "phase3_checks.sql",
         "phase4_schema.sql", "phase4_routines.sql", "phase4_security.sql"]


def statements(text):
    """Split a script into statements, honouring DELIMITER lines (as the mysql client does)."""
    delim, buf = ";", []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            delim = stripped.split(None, 1)[1].strip()
            continue
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(delim) and not stripped.startswith("--"):
            stmt = "\n".join(buf).rstrip()
            stmt = stmt[: -len(delim)].rstrip()
            buf = []
            if stmt.strip():
                yield stmt
    tail = "\n".join(buf).strip()
    if tail and not tail.startswith("--"):
        yield tail


def run_file(cur, path):
    n = 0
    for stmt in statements(path.read_text(encoding="utf-8")):
        cur.execute(stmt)
        while True:                    # CALL statements can return several result sets; drain them all
            if cur.with_rows:
                cur.fetchall()
            if not cur.nextset():
                break
        n += 1
    return n


def run_suite(cur, proc):
    """CALL a test procedure; its last result set is the (passed, failed, total) summary."""
    cur.execute(f"CALL elearning_db.{proc}()")
    last = None
    while True:
        if cur.with_rows:
            last = cur.fetchall()
        if not cur.nextset():
            break
    return last[0] if last else (0, 0, 0)


def admin_connection():
    kw = dict(user=os.getenv("DB_ADMIN_USER", "root"), password=os.getenv("DB_ADMIN_PASSWORD", ""),
              charset="utf8mb4", autocommit=True)
    if os.getenv("DB_SOCKET"):
        kw["unix_socket"] = os.getenv("DB_SOCKET")
    else:
        kw.update(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "3306")))
    return mysql.connector.connect(**kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-data", action="store_true", help="generate the college-scale dataset and logins")
    ap.add_argument("--with-benchmark", action="store_true")
    ap.add_argument("--secure-users", action="store_true")
    ap.add_argument("--yes", action="store_true", help="do not ask before dropping elearning_db")
    a = ap.parse_args()
    if not a.yes:
        if input("This DROPS and recreates the database 'elearning_db'. Type yes to continue: ").strip().lower() != "yes":
            sys.exit("Cancelled.")
    conn = admin_connection()
    cur = conn.cursor()
    ver = conn.get_server_info()
    print(f"Connected to MySQL {ver}")
    if "MariaDB" in ver or int(ver.split(".")[0]) < 8:
        sys.exit("MySQL 8.0 or newer is required (roles, CHECK constraints, JSON_TABLE, window CTEs).")
    for name in ORDER:
        n = run_file(cur, SQL / name)
        print(f"  {name:<28} {n} statements")
    for label, proc in (("Phase 2 (triggers, procedures)", "sp_run_phase2_tests"), ("Phase 3 (reports, indexes)", "sp_run_phase3_checks")):
        passed, failed, total = run_suite(cur, proc)
        print(f"  {label}: {passed}/{total} checks passed")
        if failed:
            sys.exit(f"{failed} database check(s) FAILED. Run CALL {proc}(); in MySQL to see which.")
    if a.with_benchmark:
        print("  building benchmark database (takes a few minutes) ...")
        run_file(cur, SQL / "phase3_indexes.sql")

    # the least-privilege login the web app uses
    user, pw = os.getenv("DB_USER", "lms_app"), os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_APP_HOST", "localhost")
    if user.lower() == "root":
        print("  DB_USER is root: skipping app-login creation (use a dedicated user in production).")
    elif not pw:
        sys.exit("Set DB_PASSWORD in .env: it becomes the password of the application login.")
    else:
        cur.execute(f"CREATE USER IF NOT EXISTS '{user}'@'{host}' IDENTIFIED BY %s", (pw,))
        cur.execute(f"ALTER USER '{user}'@'{host}' IDENTIFIED BY %s", (pw,))
        cur.execute(f"GRANT 'lms_app_role' TO '{user}'@'{host}'")
        cur.execute(f"SET DEFAULT ROLE 'lms_app_role' TO '{user}'@'{host}'")
        print(f"  application login '{user}'@'{host}' created with lms_app_role")
    conn.close()

    env = dict(os.environ)
    py = sys.executable
    # these scripts need to write data, so they run with the admin login
    env.update(DB_USER=os.getenv("DB_ADMIN_USER", "root"), DB_PASSWORD=os.getenv("DB_ADMIN_PASSWORD", ""))
    steps = [[py, "scripts/import_catalog.py"]]
    if a.with_data:
        steps.append([py, "-W", "ignore", "scripts/generate_scale_data.py"])
    steps.append([py, "create_users.py"] + (["--secure"] if a.secure_users else []))
    for cmd in steps:
        print("  running", " ".join(cmd[1:] if cmd[1] != "-W" else cmd[3:]))
        subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    print("\nDone. Start the app with:  python run.py   (or gunicorn -w 4 wsgi:app)")


if __name__ == "__main__":
    main()
