# EduHub LMS

A college learning-management system on **Flask + MySQL 8**: courses, study material uploads, QR-code attendance,
timetable, assignments, quizzes, results, fees, notifications, requests and audit trail. It is the final submission of the
DBMS capstone (all five phases) for the B.Tech CSE (AI & ML) department.

* 38 tables, 2 views, 24 procedures, 5 functions, 23 triggers, 52 foreign keys, 32 CHECK constraints
* three roles: **student**, **instructor**, **admin**, enforced in the app *and* in the database
* tested: 60 automated tests + the 35 Phase 2 and 9 Phase 3 database checks (all passing)

---

## 1. Quick start

You need **Python 3.10+** and **MySQL 8.0+** (8.0.16 or newer; MariaDB will not work).

```bash
python -m venv venv
venv\Scripts\activate            # Windows        (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Mac/Linux: cp .env.example .env     then edit .env
```

In `.env` set at least `DB_ADMIN_PASSWORD` (your MySQL root password) and `DB_PASSWORD` (a new password for the
application's own login), and `SECRET_KEY`.

```bash
python setup_db.py --with-data   # builds everything, ~1 minute. Type "yes" when asked.
python run.py                    # http://127.0.0.1:5000
```

`setup_db.py` creates the database, runs all five phases of SQL, runs the Phase 2 and Phase 3 test suites (it stops if any
check fails), creates the low-privilege login `lms_app`, loads the course catalogue, generates a college-sized dataset
(`--with-data`) and creates a login for every person.

**Docker instead:** `docker compose up --build`, then open http://localhost:8000.

### Demo logins (created without `--secure-users`)

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Instructor | employee code, e.g. `EMP1002` (Sunita Verma, DBMS) | `teach123` |
| Student | roll number, e.g. `2501730001` (Aarav Sharma) | `learn123` |

For a real deployment run `python setup_db.py --secure-users` (random one-time passwords written to a CSV, forced change at
first login) and set `APP_ENV=production`.

---

## 2. What is in it

| Area | Student | Instructor | Admin |
|---|---|---|---|
| **Study material** | open / download files and links of enrolled courses | upload files (PDF, slides, notebooks, zip, images, video) or links per module; hide, delete | all |
| **Attendance** | **Attendance tab: Overall** (per course %, chart, "attend the next N classes to reach 75%") and **Day-wise** (month calendar + day list); scan QR or type the code | open a **rotating QR** for today's class, watch scans arrive live, close and mark the rest absent; manual marking still works | college-wide view, shortage count, QR vs manual split, scan outcomes |
| **Timetable** | weekly grid | own weekly grid | create slots (room clashes refused), generate class sessions that skip holidays |
| **Assignments / grading** | submit links, see marks | grade, late report | calculate results |
| **Quizzes** | timed attempts, server-side clock, auto-score, review after close | build quizzes with a form, see per-question analysis | |
| **Results** | report card, term GPA | roster and weighted totals | |
| **Fees** | invoices, balance, payments | | create invoices, record payments (over-payment impossible) |
| **Notifications** | bell with unread count; new assignments, material, quizzes and grades notify automatically | notices to own courses | notices to anyone |
| **Request centre** | grievance, bonafide, transcript, ID card, fee issue ... | | respond, student is notified |
| **Also** | course registration, feedback, mentor, holidays, account/password | mentees list, feedback results | users, password reset, audit log, mentorship, holidays |

### How QR attendance works (and what it does not do)

1. The instructor opens today's class and clicks *Show QR code* (open for N minutes, "late" after M minutes).
2. The database stores a secret for that class. Every **30 seconds** the screen shows a new 6-digit code
   (HMAC of the secret and the time slot) and a QR containing a link with that code.
3. The student, logged in, scans with the in-app camera (Chrome/Edge/Android) or the phone's camera app, or types the code
   under *Scan QR*. The server checks the code, enrolment, window, and records **present** or **late**; a second scan is refused.
4. Every attempt, good or bad, is stored in `attendance_scan_log`. After 8 wrong codes in 10 minutes a student is blocked.

For phones: the QR must contain an address the phone can reach. On a laptop that is `localhost`, which a phone cannot open, so set
`PUBLIC_BASE_URL=http://<laptop-ip>:5000` (same Wi-Fi) or deploy behind HTTPS. The in-page camera scanner needs HTTPS or `localhost`;
the phone's own camera app does not.

Limits: a student could still send the code to a friend within the 30-second window. Two mitigations are built in: the
rotating code, and `QR_ALLOWED_NETWORKS` (only campus Wi-Fi addresses may mark attendance). GPS geofencing is not included.

---

## 3. Data: what is real and what is generated

* **Real:** the course catalogue in `data/catalog/` (7 courses: the Semester III set plus Data Structures, with syllabus units and
  prerequisites), the 2026-27 odd-semester dates, the structure of your university portal (attendance, timetable, fees, holidays,
  notifications, assignment, enrolment, feedback, grievance, mentorship, assessment hub).
* **Generated** (`scripts/generate_scale_data.py`): people (names, phones, e-mails), attendance, marks, quiz attempts, fee payments.
  Nothing generated claims to be a real student. 240 students in 4 sections of 60, about 63,000 attendance marks,
  about 3,000 submissions, 440 payments, 130 notifications, 1,300 class sessions (exact figures differ slightly per install).
* **Fee amounts, holiday dates and room names are placeholders.** Check the holiday dates against your university calendar.

### Loading the full department handbook

The catalogue loader is finished; the handbook itself must be typed or exported into the CSVs:

```
data/catalog/courses.csv        course_code,title,credits,department_code,semester,program[,course_type]
data/catalog/prerequisites.csv  course_code,prerequisite_code
data/catalog/modules.csv        course_code,module_number,title
python scripts/import_catalog.py
```

Run it again whenever the CSVs change (it updates, never duplicates). Real students: `data/roster/students.sample.csv` shows the
format for `python scripts/import_students.py your_roster.csv` (use `--dry-run` first), then `python create_users.py`.

Before a demo: `python scripts/top_up.py` fills attendance for every class held since the data was generated and leaves
today's classes open for a live QR demonstration.

---

## 4. Project layout

```
app.py              routes for the Phase 1-3 features, login, error handling
modules/            attendance.py (QR + Attendance tab), materials.py, quiz.py, portal.py (everything else), common.py
security.py         CSRF, security headers, login throttling, safe redirects
db.py               pooled MySQL access, audit actor, transactions
config.py           all settings from .env
setup_db.py         one-command database builder (reads DELIMITER scripts itself)
database/           schema.sql, seed.sql, phase2_*.sql, phase3_*.sql, phase4_*.sql
scripts/            import_catalog, import_students, generate_scale_data, top_up, load_test, make_er_diagram
tests/              pytest suite
templates/ static/  Jinja pages, CSS, small JS files (no CDN, no inline scripts)
EduHub_LMS_Final_Report.docx   the final project report (41 pages)
docs/               PHASE2-5 notes, ER diagrams (docs/img), screenshots (docs/screenshots)
```

SQL files in order: `schema` → `seed` → `phase2_routines` → `phase2_data` → `phase2_tests` → `phase3_data` → `phase3_reports` →
`phase3_apply_indexes` → `phase3_checks` → `phase4_schema` → `phase4_routines` → `phase4_security`.
(`phase3_indexes.sql` is the optional 450,000-row before/after EXPLAIN benchmark: `python setup_db.py --with-benchmark`.)

---

## 5. Security in short

* Passwords hashed (scrypt); change-password page; admin reset issues a one-time password and forces a change.
* CSRF token on every POST; `HttpOnly`, `SameSite=Lax` (and `Secure` over HTTPS) cookies; CSP without inline scripts; `X-Frame-Options: DENY`.
* Login lockout after 5 failures per user (and per address) in 15 minutes.
* Role checks on every route, plus ownership checks (a student cannot open another student's course, attempt or material).
* All SQL is parameterised. Uploads: extension allow-list, content check, random stored name, size limit, served only to enrolled students.
* The app connects as `lms_app` with `lms_app_role`: no DDL, `audit_log` and `grade_scale` read-only. Audit rows are written by triggers.
* What is *not* covered: e-mail/SMS, two-factor login, virus scanning of uploads, GPS attendance, online fee payment.

---

## 6. Running the checks

```bash
python -m pytest                           # 60 tests; needs the database built with --with-data
python scripts/load_test.py --base http://127.0.0.1:8000     # 58 students scan the same QR at once
```
Database checks: `CALL sp_run_phase2_tests();` (35) and `CALL sp_run_phase3_checks();` (9), run on a database built *without*
`--with-data` (they expect the small seed college; `setup_db.py` runs them for you at the right moment).

## 7. Production notes

* `gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app` (Windows: `waitress-serve --port 8000 wsgi:app`) behind nginx with HTTPS; set
  `APP_ENV=production`, `COOKIE_SECURE=1`, `BEHIND_PROXY=1`, a long `SECRET_KEY`, and `client_max_body_size 30m`.
* Back up the database (`mysqldump --routines --triggers elearning_db`) and the `uploads/` folder together.
* Logs: `logs/eduhub.log` (rotating). Health check: `/healthz`.
* Why MySQL is enough: see the final report, chapter 9 (62,958 attendance rows answer the heaviest page in about 0.2 s;
  the Phase 3 benchmark at 450,000 rows is in `docs/PHASE3.md`).

## 8. Known limitations

Tested on MySQL 8.0.46 / Python 3.12 on Linux. The Docker files, the Windows instructions and the in-page camera scanner were
written to the same standard but could not be run in the build environment; try them early. Timetable generation assumes one
building with 1-hour periods. Report cards use the grade scale from Phase 2.
