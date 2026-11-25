# Phase 5 - Final application, user interface and presentation

## What was added on top of Phases 1-4
| Requirement from the evaluation | Where |
|---|---|
| Genuine data in every module, at production scale | `scripts/generate_scale_data.py`, `data/catalog/`, `scripts/import_catalog.py`, `scripts/import_students.py` |
| Professors upload material, students access it | `modules/materials.py`, *My Courses -> course -> Study material* |
| Students mark attendance by scanning a QR | `modules/attendance.py`, `qr_window`, `sp_open_qr_window`, `sp_mark_attendance_qr`, *Scan QR* |
| Attendance tab, day-wise and overall | `/student/attendance` (Overall, Day-wise calendar); instructor and admin overviews |
| University-portal categories | timetable, holidays, notifications, fees, enrolment (course registration), feedback, grievance + request centre, mentorship, assessment hub, report card |
| Production-ready | pooled connections, `.env` configuration, `setup_db.py`, Docker files, health check, logging, tests, security (Phase 4) |

## Portal categories mapped to screens
| Portal category | EduHub screen |
|---|---|
| Attendance | Attendance tab |
| Timetable | Timetable |
| Fees | Fees |
| Holidays | More -> Holidays |
| Notifications | bell icon |
| Assignment | My Courses -> course; Assessments |
| Enrollment | More -> Course registration |
| Feedback | More -> Course feedback |
| Grievance / Request Center | More -> Request centre |
| LMS | My Courses, Study material, quizzes |
| Mentorship | More -> My mentor |
| Performance / Assessment Hub / Report Card | Assessments, More -> Report card |
| Scan QR | top-bar *Scan QR* button |
Not built (the admin/staff portal was not available): Undertaking, NEFT form, admit card and exam form.

## Database choice
MySQL 8 handles this workload comfortably, so no second database was introduced. Measured on 62,958 attendance rows with 4 workers,
20 concurrent students: the heaviest pages answer in 130-215 ms (median); 1,800 requests ran at about 119 requests/second; the Phase 3 benchmark
at 450,000 attendance rows measured the whole-college shortage report at 245 ms with its index (443 ms without). See the final report, chapter 9, for the reasoning and the point
at which read replicas or caching would be the next step.

## Presenting it (5-minute demo path)
1. Admin: dashboard -> Attendance overview -> a course with low attendance.
2. Instructor (`EMP1002`): Attendance -> today's class -> **QR attendance** -> Show QR code.
3. Student (`2501730001`) on a phone, or a second browser: **Scan QR**, type the code -> present; watch the instructor screen update.
4. Student: Attendance tab (Overall, then Day-wise), Study material download, Assessments -> take the open quiz.
5. Admin: Audit log shows the grade change, the QR opening and the logins.
