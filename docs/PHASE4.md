# Phase 4 - Security, transactions and testing

Files: `database/phase4_schema.sql`, `phase4_routines.sql`, `phase4_security.sql`, `security.py`, `tests/`.

## 1. Database roles (least privilege)
`phase4_security.sql` defines three roles. The web app logs in as `lms_app` and holds only `lms_app_role`.

| Role | May do | May not do |
|---|---|---|
| `lms_app_role` | SELECT/INSERT/UPDATE/DELETE on data tables, EXECUTE routines | CREATE, ALTER, DROP, GRANT; write `audit_log` or `grade_scale`; delete from `attendance_scan_log` |
| `lms_report_role` | SELECT on every table except `user_account` and `login_attempt`; EXECUTE `sp_report_*` | any change |
| `lms_dba_role` | everything on `elearning_db` | |

Audit rows are written by triggers and by `sp_log_event`, which run with their definer's rights, so the application can
append to the audit trail without being able to edit or delete it. `tests/test_security.py` proves nine dangerous statements are refused.

## 2. Audit trail
Every connection stores the logged-in username in `@app_user`; triggers record who changed a grade
(`trg_audit_submission_au`), an enrolment status, a course result, an account (activation, password) and every fee payment.
Logins (good and bad), uploads, QR openings and quiz creation are logged by the app. Admin screen: *More -> Audit log*.

## 3. Transactions
| Operation | How it stays consistent |
|---|---|
| Enrol (`sp_enroll_student`) | locks the offering row, checks seats and prerequisites, inserts; 8 students racing for 1 seat -> exactly 1 wins (`test_last_seat_goes_to_exactly_one_student`) |
| Record a payment | `trg_payment_bi` locks the invoice (`FOR UPDATE`) and refuses over-payment; two simultaneous 700 payments on a 1000 invoice -> one succeeds |
| Submit a quiz (`sp_submit_quiz_attempt`) | answers + score + `submitted_on` in one transaction; late submissions score 0 and store no answers |
| Close a class (`sp_finish_session_attendance`) | all absentees are inserted or none (`EXIT HANDLER ... ROLLBACK`) |
| Build a quiz | quiz, questions and options in one transaction (`db.transaction()`) |

Isolation level is MySQL's default (REPEATABLE READ); the row locks above are what prevent the lost-update cases.

## 4. Web security
CSRF tokens on every POST (found and fixed during testing: a POST with *no* token used to pass when the session had not yet issued one),
login lockout, safe `next=` redirects, security headers and a CSP without inline scripts, role and ownership checks, upload allow-list
with content check, password policy, one-time passwords on reset.

## 5. Testing
* `tests/` - 60 pytest tests: security (31: headers, CSRF, roles, lockout, IDOR, privileges), QR attendance (13), uploads (6), quizzes (3), concurrency and database rules (7)
* `sp_run_phase2_tests()` - 35 checks; `sp_run_phase3_checks()` - 9 checks; both still pass after the Phase 4 changes
* `scripts/load_test.py` - 58 students scan one QR within the same second: all 58 confirmed in 1.34 s
