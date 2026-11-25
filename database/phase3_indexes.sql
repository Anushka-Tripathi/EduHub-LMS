-- =====================================================================
-- PHASE 3: Indexes and query-plan comparison  (MySQL 8.0.18+ for EXPLAIN ANALYZE)
--
-- WHY A SEPARATE BENCHMARK DATABASE?
--   elearning_db holds a demo-sized college (about 60 sessions, 100 submissions). At that size
--   MySQL scans a whole table in microseconds and ignores new indexes, so a before/after
--   comparison there proves nothing. This script therefore:
--     PART A  builds elearning_bench, a copy of the table structures filled with a realistic
--             volume (450,000 attendance rows, 97,000 submissions), and compares plans
--             BEFORE and AFTER adding the indexes. elearning_db is not touched in Part A.
--     PART B  applies the same indexes to elearning_db.
--   Safe to re-run: the benchmark database is rebuilt every time.
--
-- HOW TO READ THE RESULT
--   Run each EXPLAIN ANALYZE twice and read the first line: "actual time=START..END".
--   Look for the plan change too: "Table scan" -> "Index range scan", and
--   "Index scan using enrollment_id" -> "Index scan using idx_attendance_enrollment_status".
--   Timings vary between machines; the plan shapes and the ratios are what matter.
--
-- INDEXES ADDED (each one must earn its place, because every index slows writes and uses space)
--   idx_submission_submitted_on          (submitted_on)
--        Late-submission report filters submissions by date range. Without it: full table scan.
--   idx_attendance_enrollment_status     (enrollment_id, status)
--        Attendance % per enrolment (shortage list, fn_attendance_pct, dashboards). It covers the
--        query: enrollment_id and status are both in the index, so no row lookups are needed.
--        Its first column also serves the foreign key, so MySQL may drop the old single-column
--        FK index automatically.
--
-- INDEX TRIED AND REJECTED
--   class_session(session_date): the monthly attendance report already uses the Phase 1 unique key
--        (offering_id, session_date, start_time). A date-only index only changed the join order;
--        measured time did not improve. Not added.
-- =====================================================================
USE elearning_db;
DELIMITER $$

-- helpers so the script can be re-run without "duplicate key name" errors ----------------
DROP PROCEDURE IF EXISTS sp_p3_add_index$$
CREATE PROCEDURE sp_p3_add_index(IN p_db VARCHAR(64), IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_cols VARCHAR(200))
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.statistics
                    WHERE table_schema = p_db AND table_name = p_table AND index_name = p_index) THEN
        SET @p3_sql = CONCAT('ALTER TABLE `', p_db, '`.`', p_table, '` ADD INDEX `', p_index, '` (', p_cols, ')');
        PREPARE p3_st FROM @p3_sql; EXECUTE p3_st; DEALLOCATE PREPARE p3_st;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_p3_drop_index$$
CREATE PROCEDURE sp_p3_drop_index(IN p_db VARCHAR(64), IN p_table VARCHAR(64), IN p_index VARCHAR(64))
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.statistics
                WHERE table_schema = p_db AND table_name = p_table AND index_name = p_index) THEN
        SET @p3_sql = CONCAT('ALTER TABLE `', p_db, '`.`', p_table, '` DROP INDEX `', p_index, '`');
        PREPARE p3_st FROM @p3_sql; EXECUTE p3_st; DEALLOCATE PREPARE p3_st;
    END IF;
END$$
DELIMITER ;

-- =====================================================================
-- PART A.1  Build the benchmark database (same structures and Phase 1 indexes as elearning_db)
-- =====================================================================
DROP DATABASE IF EXISTS elearning_bench;
CREATE DATABASE elearning_bench CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE elearning_bench.student         LIKE elearning_db.student;
CREATE TABLE elearning_bench.course          LIKE elearning_db.course;
CREATE TABLE elearning_bench.course_offering LIKE elearning_db.course_offering;
CREATE TABLE elearning_bench.enrollment      LIKE elearning_db.enrollment;
CREATE TABLE elearning_bench.class_session   LIKE elearning_db.class_session;
CREATE TABLE elearning_bench.attendance      LIKE elearning_db.attendance;
CREATE TABLE elearning_bench.assignment      LIKE elearning_db.assignment;
CREATE TABLE elearning_bench.submission      LIKE elearning_db.submission;

-- make sure the benchmark starts with ONLY the Phase 1 indexes (matters if you re-run after Part B)
CALL sp_p3_drop_index('elearning_bench', 'submission', 'idx_submission_submitted_on');
CALL sp_p3_drop_index('elearning_bench', 'attendance', 'idx_attendance_enrollment_status');

-- number helper (1 to 200,000)
CREATE TABLE elearning_bench.digits (d INT PRIMARY KEY);
INSERT INTO elearning_bench.digits VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9);
CREATE TABLE elearning_bench.nums (n INT PRIMARY KEY);
INSERT INTO elearning_bench.nums
SELECT a.d + 10*b.d + 100*c.d + 1000*d.d + 10000*e.d + 100000*f.d + 1
  FROM elearning_bench.digits a, elearning_bench.digits b, elearning_bench.digits c,
       elearning_bench.digits d, elearning_bench.digits e, elearning_bench.digits f
 WHERE a.d + 10*b.d + 100*c.d + 1000*d.d + 10000*e.d + 100000*f.d < 200000;

-- =====================================================================
-- PART A.2  Fill it: 3,000 students, 150 offerings, 9,000 enrolments, 7,500 sessions
-- =====================================================================
USE elearning_bench;

INSERT INTO student (roll_number, first_name, last_name, email, program_id, admission_year)
SELECT CONCAT('B', LPAD(n, 6, '0')), 'Bench', CONCAT('S', n), CONCAT('b', n, '@bench.edu'), 1, 2025
  FROM nums WHERE n <= 3000;

INSERT INTO course (course_code, title, department_id, credits)
SELECT CONCAT('BCS', LPAD(n, 3, '0')), CONCAT('Bench course ', n), 1, 3 FROM nums WHERE n <= 40;

INSERT INTO course_offering (course_id, term_id, section_code)
SELECT 1 + MOD(n, 40), 2, CONCAT('S', n) FROM nums WHERE n <= 150;

INSERT INTO enrollment (student_id, offering_id, enrolled_on)
SELECT 1 + MOD(o.n * 61 + j.n * 49, 3000), o.n, '2026-01-05'
  FROM nums o JOIN nums j ON j.n <= 60 WHERE o.n <= 150;

INSERT INTO class_session (offering_id, session_date, start_time, end_time, topic)
SELECT o.n, DATE_ADD('2026-01-05', INTERVAL ((k.n - 1) * 7 + MOD(o.n, 5)) DAY),
       MAKETIME(8 + MOD(o.n, 8), 0, 0), MAKETIME(9 + MOD(o.n, 8), 0, 0), CONCAT('Lecture ', k.n)
  FROM nums o JOIN nums k ON k.n <= 50 WHERE o.n <= 150;

-- attendance: 450,000 rows in three chunks (keeps every statement short)
INSERT INTO attendance (session_id, enrollment_id, status)
SELECT cs.session_id, e.enrollment_id,
       CASE WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) < 7 THEN 'present'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 7 THEN 'late'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 8 THEN 'excused' ELSE 'absent' END
  FROM class_session cs JOIN enrollment e ON e.offering_id = cs.offering_id WHERE cs.offering_id BETWEEN 1 AND 50;
INSERT INTO attendance (session_id, enrollment_id, status)
SELECT cs.session_id, e.enrollment_id,
       CASE WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) < 7 THEN 'present'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 7 THEN 'late'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 8 THEN 'excused' ELSE 'absent' END
  FROM class_session cs JOIN enrollment e ON e.offering_id = cs.offering_id WHERE cs.offering_id BETWEEN 51 AND 100;
INSERT INTO attendance (session_id, enrollment_id, status)
SELECT cs.session_id, e.enrollment_id,
       CASE WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) < 7 THEN 'present'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 7 THEN 'late'
            WHEN MOD(cs.session_id * 7 + e.enrollment_id * 3, 10) = 8 THEN 'excused' ELSE 'absent' END
  FROM class_session cs JOIN enrollment e ON e.offering_id = cs.offering_id WHERE cs.offering_id BETWEEN 101 AND 150;

-- assignments (12 per offering) and about 97,000 submissions, 22% of them late
INSERT INTO assignment (offering_id, title, max_marks, assigned_on, due_date, allow_late)
SELECT o.n, CONCAT('Assignment ', k.n), 20,
       DATE_SUB(DATE_ADD('2026-01-20 23:59:00', INTERVAL ((k.n - 1) * 28 + MOD(o.n, 7)) DAY), INTERVAL 14 DAY),
       DATE_ADD('2026-01-20 23:59:00', INTERVAL ((k.n - 1) * 28 + MOD(o.n, 7)) DAY), TRUE
  FROM nums o JOIN nums k ON k.n <= 12 WHERE o.n <= 150;

INSERT INTO submission (assignment_id, enrollment_id, submitted_on, content_url, marks_obtained)
SELECT a.assignment_id, e.enrollment_id,
       IF(MOD(a.assignment_id + e.enrollment_id, 5) = 0,
          DATE_ADD(a.due_date, INTERVAL 1 + MOD(e.enrollment_id * 13, 120) HOUR),
          DATE_SUB(a.due_date, INTERVAL MOD(e.enrollment_id * 7, 96) HOUR)),
       'https://example.com/x', ROUND(20 * (0.5 + MOD(a.assignment_id * 3 + e.enrollment_id, 50) / 100), 1)
  FROM assignment a JOIN enrollment e ON e.offering_id = a.offering_id
 WHERE MOD(a.assignment_id + e.enrollment_id, 10) <> 1 AND a.offering_id BETWEEN 1 AND 75;
INSERT INTO submission (assignment_id, enrollment_id, submitted_on, content_url, marks_obtained)
SELECT a.assignment_id, e.enrollment_id,
       IF(MOD(a.assignment_id + e.enrollment_id, 5) = 0,
          DATE_ADD(a.due_date, INTERVAL 1 + MOD(e.enrollment_id * 13, 120) HOUR),
          DATE_SUB(a.due_date, INTERVAL MOD(e.enrollment_id * 7, 96) HOUR)),
       'https://example.com/x', ROUND(20 * (0.5 + MOD(a.assignment_id * 3 + e.enrollment_id, 50) / 100), 1)
  FROM assignment a JOIN enrollment e ON e.offering_id = a.offering_id
 WHERE MOD(a.assignment_id + e.enrollment_id, 10) <> 1 AND a.offering_id BETWEEN 76 AND 150;

DROP TABLE digits;
DROP TABLE nums;
ANALYZE TABLE student, course, course_offering, enrollment, class_session, attendance, assignment, submission;

SELECT 'attendance' AS tbl, COUNT(*) AS `rows` FROM attendance
UNION ALL SELECT 'submission', COUNT(*) FROM submission
UNION ALL SELECT 'class_session', COUNT(*) FROM class_session;

-- =====================================================================
-- PART A.3  BEFORE: plans with the Phase 1 indexes only
--   (run each EXPLAIN ANALYZE twice; read "actual time" on the first line)
-- =====================================================================
SET @from_month = '2026-03-01 00:00:00', @to_month = '2026-03-31 23:59:59';
SET @from_week  = '2026-03-09 00:00:00', @to_week  = '2026-03-15 23:59:59';

-- Report 1c: attendance shortage list (every enrolment below 75%)
EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, t.attendance_pct
  FROM (SELECT enrollment_id,
               ROUND(100 * SUM(status IN ('present','late')) / NULLIF(SUM(status <> 'excused'), 0), 2) AS attendance_pct
          FROM attendance GROUP BY enrollment_id HAVING attendance_pct < 75) t
  JOIN enrollment e      ON e.enrollment_id = t.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = e.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 ORDER BY t.attendance_pct, s.roll_number LIMIT 25;

-- Report 3: late submissions in one MONTH
EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, a.title, TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on) AS hours_late
  FROM submission sub
  JOIN assignment a      ON a.assignment_id = sub.assignment_id
  JOIN enrollment e      ON e.enrollment_id = sub.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = a.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 WHERE sub.submitted_on >= @from_month AND sub.submitted_on <= @to_month AND sub.submitted_on > a.due_date
 ORDER BY hours_late DESC LIMIT 50;

-- Report 3: late submissions in one WEEK
EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, a.title, TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on) AS hours_late
  FROM submission sub
  JOIN assignment a      ON a.assignment_id = sub.assignment_id
  JOIN enrollment e      ON e.enrollment_id = sub.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = a.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 WHERE sub.submitted_on >= @from_week AND sub.submitted_on <= @to_week AND sub.submitted_on > a.due_date
 ORDER BY hours_late DESC LIMIT 50;

-- =====================================================================
-- PART A.4  Create the indexes on the benchmark, refresh statistics
-- =====================================================================
CALL elearning_db.sp_p3_add_index('elearning_bench', 'submission', 'idx_submission_submitted_on', 'submitted_on');
CALL elearning_db.sp_p3_add_index('elearning_bench', 'attendance', 'idx_attendance_enrollment_status', 'enrollment_id, status');
ANALYZE TABLE elearning_bench.submission, elearning_bench.attendance;

-- =====================================================================
-- PART A.5  AFTER: the same three statements, now with the indexes
--   Expect: Table scan on sub  ->  Index range scan on sub using idx_submission_submitted_on
--           Index scan on attendance using enrollment_id -> ... using idx_attendance_enrollment_status
-- =====================================================================
EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, t.attendance_pct
  FROM (SELECT enrollment_id,
               ROUND(100 * SUM(status IN ('present','late')) / NULLIF(SUM(status <> 'excused'), 0), 2) AS attendance_pct
          FROM attendance GROUP BY enrollment_id HAVING attendance_pct < 75) t
  JOIN enrollment e      ON e.enrollment_id = t.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = e.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 ORDER BY t.attendance_pct, s.roll_number LIMIT 25;

EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, a.title, TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on) AS hours_late
  FROM submission sub
  JOIN assignment a      ON a.assignment_id = sub.assignment_id
  JOIN enrollment e      ON e.enrollment_id = sub.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = a.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 WHERE sub.submitted_on >= @from_month AND sub.submitted_on <= @to_month AND sub.submitted_on > a.due_date
 ORDER BY hours_late DESC LIMIT 50;

EXPLAIN ANALYZE
SELECT s.roll_number, c.course_code, a.title, TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on) AS hours_late
  FROM submission sub
  JOIN assignment a      ON a.assignment_id = sub.assignment_id
  JOIN enrollment e      ON e.enrollment_id = sub.enrollment_id
  JOIN student s         ON s.student_id    = e.student_id
  JOIN course_offering o ON o.offering_id   = a.offering_id
  JOIN course c          ON c.course_id     = o.course_id
 WHERE sub.submitted_on >= @from_week AND sub.submitted_on <= @to_week AND sub.submitted_on > a.due_date
 ORDER BY hours_late DESC LIMIT 50;

-- =====================================================================
-- PART B  Apply the same indexes to the real database
-- =====================================================================
USE elearning_db;
CALL sp_p3_add_index('elearning_db', 'submission', 'idx_submission_submitted_on', 'submitted_on');
CALL sp_p3_add_index('elearning_db', 'attendance', 'idx_attendance_enrollment_status', 'enrollment_id, status');
ANALYZE TABLE elearning_db.submission, elearning_db.attendance;

SELECT table_name, index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_in_index
  FROM information_schema.statistics
 WHERE table_schema = 'elearning_db' AND table_name IN ('attendance', 'submission')
 GROUP BY table_name, index_name
 ORDER BY table_name, index_name;

-- Optional clean-up when you have recorded your screenshots:
-- DROP DATABASE elearning_bench;
