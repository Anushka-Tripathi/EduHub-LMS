# Phase 3: Query and report development

Schema (`schema.sql`) is unchanged. Phase 3 adds report procedures, two indexes, and a query-plan comparison.

## Load order

`schema.sql` → `seed.sql` → `phase2_routines.sql` → `phase2_data.sql` → **`phase3_data.sql`** → **`phase3_reports.sql`** → **`phase3_indexes.sql`**
Optional checks: `phase3_checks.sql` (expects 9 passed, 0 failed) and `phase2_tests.sql` (35 passed, 0 failed).

## Mapping from the payroll brief

| Brief | This project | Procedure |
|---|---|---|
| Monthly attendance summary | Attendance per student per course for a month, plus month-by-month trend and a shortage list | `sp_report_monthly_attendance`, `sp_report_attendance_by_month`, `sp_report_attendance_shortage` |
| Salary slip per employee | Report card per student per term: courses, assignment/quiz/attendance, deduction, final %, grade, term GPA, CGPA | `sp_report_card` |
| Late-marks report | Submissions after the deadline with hours late, days late, penalty %, and repeat offenders | `sp_report_late_submissions` |

Examples (also at the end of `phase3_reports.sql`):
```sql
CALL sp_report_monthly_attendance('2026-09-01', NULL);   -- all courses; give an offering id to limit
CALL sp_report_attendance_by_month(NULL);                -- current term
CALL sp_report_attendance_shortage(75);
CALL sp_report_card('2501730001', NULL);                 -- 3 result sets: header, course lines, totals
CALL sp_report_late_submissions('2026-10-01 00:00:00', '2026-10-31 23:59:59', NULL);
```

**Rules used** (adjust if your teacher's policy differs)
- Attendance % = (present + late) / (all sessions except excused). Below 75% is a shortage.
- Late penalty = 5% of the marks for every started day late, capped at 50%. It is reported, not applied to course results.
- Term GPA = sum(grade points × credits) / sum(credits) over courses that already have a result. CGPA uses finished (completed or failed) courses of all terms.

**Design point:** date filters are written as `col >= x AND col < y` on the bare column, never `MONTH(col) = 9`, so an index can be used. Optional filters use `col BETWEEN COALESCE(p, 0) AND COALESCE(p, 2147483647)` instead of `p IS NULL OR col = p`, which keeps the filter usable by an index.

## Data added: `phase3_data.sql`
"Assignment 3 (Lab)" in the five technical courses (late work allowed): 32 submissions, 13 of them late by 3 to 100 hours, loaded through the Phase 2 triggers. Without it the late report would be empty.

## Indexes: `phase3_indexes.sql`

| Index | Table (columns) | Used by |
|---|---|---|
| `idx_submission_submitted_on` | `submission (submitted_on)` | late-submission report (date range) |
| `idx_attendance_enrollment_status` | `attendance (enrollment_id, status)` | attendance % per enrolment: shortage list, `fn_attendance_pct`, dashboards (a covering index) |

MySQL dropped the old single-column foreign-key index on `attendance.enrollment_id` automatically, because the new index starts with the same column.

### Why the comparison runs on a separate benchmark database
`elearning_db` has about 60 sessions and 100 submissions. At that size MySQL scans a whole table in microseconds and ignores a new index, so a before/after comparison on it shows nothing (tested: identical plan, 1.3 ms either way). `phase3_indexes.sql` therefore builds `elearning_bench`, the same table structures with 450,000 attendance rows and 97,000 submissions, shows `EXPLAIN ANALYZE` before and after the indexes, and then applies the indexes to the real database. The script is safe to re-run.

### Results (my test machine; yours will differ, the plan changes and ratios should match)
Median of interleaved runs, with and without the index in the same session:

| Report | Plan before | Plan after | Before | After | Gain |
|---|---|---|---|---|---|
| Attendance shortage (<75%), whole college | index scan on the FK index, row lookups | covering index scan on `idx_attendance_enrollment_status` | 443 ms | 245 ms | 1.8x |
| Late submissions, one month | table scan on `submission` (97,200 rows) | index range scan on `idx_submission_submitted_on` | 61 ms | 33 ms | 1.8x |
| Late submissions, one week | table scan on `submission` | index range scan | 50 ms | 2.6 ms | 19x |

The more selective the date range, the bigger the win. `EXPLAIN ANALYZE` single runs in the script are noisier (for example 1,699 ms to 331 ms for the shortage list), so read the plan shapes and run each twice.

### Index tried and rejected
`class_session (session_date)` for the college-wide monthly report. The plan changed (the join order flipped) but the measured time did not improve, because the Phase 1 unique key `(offering_id, session_date, start_time)` already serves that query. Every index slows inserts and uses space, so it was not added. Lesson for the viva: an index that changes the plan is not necessarily a faster plan; measure it.

Early single-run timings in this phase were misleading (the same plan measured 91 ms, then 54 ms). The numbers above come from interleaved A/B runs for that reason.

## Accuracy checks: `phase3_checks.sql`
Nine checks, each computing a figure two ways and comparing: every attendance record lands in exactly one month; monthly figures add back up to `fn_attendance_pct` for every enrolment; shortage list by function vs grouped query; late-row count by date comparison vs `TIMESTAMPDIFF(SECOND)`; no penalty outside 5 to 50%; no late submissions on assignments that forbid them; grade points from `grade_scale` vs an independent CASE ladder; term GPA two ways; no result outside 0 to 100. Hand check: Aarav's term GPA = (6×2 + 9×4 + 7×3 + 8×4) / 13 = 7.77.

## In the web app
- Admin: **Reports** tab (monthly attendance with a trend chart, shortage, late submissions, report card lookup). Each table has **Download CSV**.
- Admin student page: **Report card** button. Student: **Report card** tab with term selector and **Print**.
- Instructor: **Attendance report** and **Late submissions** buttons on each of their own courses (limited to that course).

## Calendar fixes made in this phase
Assignment 2 and Quiz 2 dates in `seed.sql` are now relative to today (`CURDATE()`), so "due soon" always has content. A Phase 2 test that silently depended on Assignment 2 being in the future was made date-independent.
