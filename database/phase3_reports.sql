-- =====================================================================
-- PHASE 3: Query & report development  (MySQL 8.0)
-- Run after phase3_data.sql. Schema unchanged; only report procedures are added.
--
--   Payroll brief              ->  this project
--   monthly attendance summary ->  sp_report_monthly_attendance, sp_report_attendance_by_month,
--                                  sp_report_attendance_shortage
--   salary slip per employee   ->  sp_report_card   (one slip per student per term)
--   late-marks report          ->  sp_report_late_submissions
--
-- Each report is one stored procedure, so the same SQL is used from Workbench and from the
-- web app. Date filters are written as ranges (col >= x AND col < y) on the bare column,
-- never as MONTH(col) = 9, so that an index on the column can be used.
-- =====================================================================
USE elearning_db;
DELIMITER $$

-- ---------------------------------------------------------------------
-- 1a. Monthly attendance summary: one row per student per course for one month.
--     p_month_start: any date in the month.  p_offering_id: NULL = every course.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_report_monthly_attendance$$
CREATE PROCEDURE sp_report_monthly_attendance(IN p_month_start DATE, IN p_offering_id INT)
BEGIN
    DECLARE v_from DATE;
    DECLARE v_to   DATE;
    SET v_from = DATE_SUB(p_month_start, INTERVAL DAYOFMONTH(p_month_start) - 1 DAY);   -- 1st of the month
    SET v_to   = DATE_ADD(v_from, INTERVAL 1 MONTH);

    SELECT t.roll_number, t.student, t.course_code, t.course,
           t.sessions_marked, t.present, t.late, t.absent, t.excused, t.attendance_pct,
           IF(t.attendance_pct < 75, 'Shortage', 'OK') AS standing
      FROM (SELECT s.roll_number,
                   CONCAT(s.first_name, ' ', s.last_name)                           AS student,
                   c.course_code, c.title                                           AS course,
                   COUNT(*)                                                         AS sessions_marked,
                   SUM(a.status = 'present')                                        AS present,
                   SUM(a.status = 'late')                                           AS late,
                   SUM(a.status = 'absent')                                         AS absent,
                   SUM(a.status = 'excused')                                        AS excused,
                   ROUND(100 * SUM(a.status IN ('present','late'))
                             / NULLIF(SUM(a.status <> 'excused'), 0), 1)            AS attendance_pct
              FROM class_session cs
              JOIN attendance a        ON a.session_id    = cs.session_id
              JOIN enrollment e        ON e.enrollment_id = a.enrollment_id
              JOIN student s           ON s.student_id    = e.student_id
              JOIN course_offering o   ON o.offering_id   = cs.offering_id
              JOIN course c            ON c.course_id     = o.course_id
             WHERE cs.session_date >= v_from AND cs.session_date < v_to
               AND cs.offering_id BETWEEN COALESCE(p_offering_id, 0) AND COALESCE(p_offering_id, 2147483647)
             GROUP BY e.enrollment_id, s.roll_number, s.first_name, s.last_name, c.course_code, c.title) t
     ORDER BY t.attendance_pct, t.roll_number, t.course_code;
END$$

-- ---------------------------------------------------------------------
-- 1b. Month-by-month attendance trend per course for a term (NULL = current term)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_report_attendance_by_month$$
CREATE PROCEDURE sp_report_attendance_by_month(IN p_term_id INT)
BEGIN
    DECLARE v_term INT;
    SELECT term_id INTO v_term FROM academic_term WHERE is_current LIMIT 1;
    SET v_term = COALESCE(p_term_id, v_term);

    SELECT c.course_code, c.title AS course,
           DATE_FORMAT(cs.session_date, '%Y-%m')                               AS month,
           COUNT(DISTINCT cs.session_id)                                       AS sessions_held,
           COUNT(*)                                                            AS attendance_records,
           ROUND(100 * SUM(a.status IN ('present','late'))
                     / NULLIF(SUM(a.status <> 'excused'), 0), 1)               AS attendance_pct
      FROM course_offering o
      JOIN course c        ON c.course_id  = o.course_id
      JOIN class_session cs ON cs.offering_id = o.offering_id
      JOIN attendance a    ON a.session_id = cs.session_id
     WHERE o.term_id = v_term
     GROUP BY c.course_code, c.title, DATE_FORMAT(cs.session_date, '%Y-%m')
     ORDER BY c.course_code, month;
END$$

-- ---------------------------------------------------------------------
-- 1c. Attendance shortage list: active enrolments below a threshold (e.g. 75)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_report_attendance_shortage$$
CREATE PROCEDURE sp_report_attendance_shortage(IN p_threshold DECIMAL(5,2))
BEGIN
    SELECT s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student,
           c.course_code, t.records_counted, t.attendance_pct,
           fn_attendance_deduction(t.attendance_pct)             AS result_deduction
      FROM (SELECT enrollment_id, COUNT(*) AS records_counted,
                   ROUND(100 * SUM(status IN ('present','late'))
                             / NULLIF(SUM(status <> 'excused'), 0), 2) AS attendance_pct
              FROM attendance
             GROUP BY enrollment_id
            HAVING attendance_pct < p_threshold) t
      JOIN enrollment e      ON e.enrollment_id = t.enrollment_id AND e.status = 'enrolled'
      JOIN student s         ON s.student_id    = e.student_id
      JOIN course_offering o ON o.offering_id   = e.offering_id
      JOIN course c          ON c.course_id     = o.course_id
     ORDER BY t.attendance_pct, s.roll_number;
END$$

-- ---------------------------------------------------------------------
-- 2. Report card (the "salary slip"): one student, one term (NULL = current term).
--    Returns 3 result sets: header, one line per course, totals.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_report_card$$
CREATE PROCEDURE sp_report_card(IN p_roll VARCHAR(20), IN p_term_id INT)
BEGIN
    DECLARE v_sid  INT;
    DECLARE v_term INT;
    DECLARE v_cgpa DECIMAL(4,2);
    DECLARE v_cgpa_credits INT;

    SELECT student_id INTO v_sid FROM student WHERE roll_number = p_roll;
    IF v_sid IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Report card: student not found.';
    END IF;
    SELECT term_id INTO v_term FROM academic_term WHERE is_current LIMIT 1;
    SET v_term = COALESCE(p_term_id, v_term);

    -- cumulative GPA over finished courses (completed or failed), all terms
    SELECT ROUND(SUM(gs.grade_points * c.credits) / SUM(c.credits), 2), SUM(c.credits)
      INTO v_cgpa, v_cgpa_credits
      FROM enrollment e
      JOIN course_offering o ON o.offering_id = e.offering_id
      JOIN course c          ON c.course_id   = o.course_id
      JOIN course_result r   ON r.enrollment_id = e.enrollment_id
      JOIN grade_scale gs    ON gs.grade_letter = fn_letter_grade(r.final_percentage)
     WHERE e.student_id = v_sid AND e.status IN ('completed', 'failed');

    -- result set 1: header
    SELECT s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student, p.program_name,
           s.current_semester, t.term_name
      FROM student s
      JOIN program p       ON p.program_id = s.program_id
      JOIN academic_term t ON t.term_id    = v_term
     WHERE s.student_id = v_sid;

    -- result set 2: one line per course of the term
    SELECT c.course_code, c.title AS course, c.credits,
           fn_assignment_pct(e.enrollment_id)                              AS assignment_pct,
           fn_quiz_pct(e.enrollment_id)                                    AS quiz_pct,
           fn_attendance_pct(e.enrollment_id)                              AS attendance_pct,
           fn_attendance_deduction(fn_attendance_pct(e.enrollment_id))     AS attendance_deduction,
           r.final_percentage,
           fn_letter_grade(r.final_percentage)                             AS grade,
           gs.grade_points,
           e.status
      FROM enrollment e
      JOIN course_offering o ON o.offering_id = e.offering_id
      JOIN course c          ON c.course_id   = o.course_id
      LEFT JOIN course_result r ON r.enrollment_id = e.enrollment_id
      LEFT JOIN grade_scale gs  ON gs.grade_letter = fn_letter_grade(r.final_percentage)
     WHERE e.student_id = v_sid AND o.term_id = v_term AND e.status <> 'dropped'
     ORDER BY c.course_code;

    -- result set 3: totals (term GPA counts only courses that already have a result)
    SELECT COUNT(*)                                                         AS courses,
           SUM(c.credits)                                                   AS credits_registered,
           SUM(CASE WHEN gs.grade_points IS NOT NULL THEN c.credits END)    AS credits_graded,
           ROUND(SUM(gs.grade_points * c.credits)
                 / NULLIF(SUM(CASE WHEN gs.grade_points IS NOT NULL THEN c.credits END), 0), 2) AS term_gpa,
           v_cgpa                                                           AS cgpa,
           v_cgpa_credits                                                   AS cgpa_credits
      FROM enrollment e
      JOIN course_offering o ON o.offering_id = e.offering_id
      JOIN course c          ON c.course_id   = o.course_id
      LEFT JOIN course_result r ON r.enrollment_id = e.enrollment_id
      LEFT JOIN grade_scale gs  ON gs.grade_letter = fn_letter_grade(r.final_percentage)
     WHERE e.student_id = v_sid AND o.term_id = v_term AND e.status <> 'dropped';
END$$

-- ---------------------------------------------------------------------
-- 3. Late-submission report (the "late-marks report").
--    Submissions made after the deadline between p_from and p_to; NULL offering = all courses.
--    Penalty rule used here: 5% of the marks for every started day late, at most 50%.
--    The penalty is shown for information; it is not applied to course results.
--    Result set 1: every late submission.  Result set 2: students who were late 2+ times.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_report_late_submissions$$
CREATE PROCEDURE sp_report_late_submissions(IN p_from DATETIME, IN p_to DATETIME, IN p_offering_id INT)
BEGIN
    SELECT t.roll_number, t.student, t.course_code, t.assignment, t.due_date, t.submitted_on,
           t.hours_late, t.days_late, t.penalty_pct, t.max_marks, t.marks_obtained,
           ROUND(t.marks_obtained * (1 - t.penalty_pct / 100), 1) AS marks_after_penalty
      FROM (SELECT s.roll_number,
                   CONCAT(s.first_name, ' ', s.last_name)                         AS student,
                   c.course_code, a.title AS assignment, a.due_date, sub.submitted_on,
                   TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on)              AS hours_late,
                   CEILING(TIMESTAMPDIFF(MINUTE, a.due_date, sub.submitted_on) / 1440) AS days_late,
                   LEAST(50, 5 * CEILING(TIMESTAMPDIFF(MINUTE, a.due_date, sub.submitted_on) / 1440)) AS penalty_pct,
                   a.max_marks, sub.marks_obtained
              FROM submission sub
              JOIN assignment a        ON a.assignment_id = sub.assignment_id
              JOIN enrollment e        ON e.enrollment_id = sub.enrollment_id
              JOIN student s           ON s.student_id    = e.student_id
              JOIN course_offering o   ON o.offering_id   = a.offering_id
              JOIN course c            ON c.course_id     = o.course_id
             WHERE sub.submitted_on >= p_from AND sub.submitted_on <= p_to
               AND sub.submitted_on > a.due_date
               AND a.offering_id BETWEEN COALESCE(p_offering_id, 0) AND COALESCE(p_offering_id, 2147483647)) t
     ORDER BY t.hours_late DESC, t.roll_number;

    SELECT s.roll_number, CONCAT(s.first_name, ' ', s.last_name) AS student,
           COUNT(*) AS late_submissions,
           ROUND(AVG(TIMESTAMPDIFF(HOUR, a.due_date, sub.submitted_on)), 1) AS avg_hours_late
      FROM submission sub
      JOIN assignment a      ON a.assignment_id = sub.assignment_id
      JOIN enrollment e      ON e.enrollment_id = sub.enrollment_id
      JOIN student s         ON s.student_id    = e.student_id
     WHERE sub.submitted_on >= p_from AND sub.submitted_on <= p_to
       AND sub.submitted_on > a.due_date
       AND a.offering_id BETWEEN COALESCE(p_offering_id, 0) AND COALESCE(p_offering_id, 2147483647)
     GROUP BY s.student_id, s.roll_number, s.first_name, s.last_name
    HAVING COUNT(*) >= 2
     ORDER BY late_submissions DESC, avg_hours_late DESC;
END$$

DELIMITER ;

-- =====================================================================
-- Example runs (each CALL opens its own result tab in Workbench)
-- =====================================================================
CALL sp_report_monthly_attendance('2026-09-01', NULL);          -- all courses, September 2026
CALL sp_report_monthly_attendance('2026-09-01', 1);             -- DBMS only
CALL sp_report_attendance_by_month(NULL);                       -- trend per course, current term
CALL sp_report_attendance_shortage(75);                         -- below 75%
CALL sp_report_card('2501730001', NULL);                        -- report card, current term
CALL sp_report_late_submissions('2026-10-01 00:00:00', '2026-10-31 23:59:59', NULL);
