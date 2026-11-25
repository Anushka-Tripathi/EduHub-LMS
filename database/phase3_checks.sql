-- =====================================================================
-- PHASE 3 ACCURACY CHECKS   (run after phase3_data.sql and phase3_reports.sql)
--   CALL sp_run_phase3_checks();
-- Each check computes the same figure two different ways (one mirrors the report SQL, one is
-- written independently) and compares them. Nothing is modified.
-- =====================================================================
USE elearning_db;
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_run_phase3_checks$$
CREATE PROCEDURE sp_run_phase3_checks()
BEGIN
    DECLARE v_a DECIMAL(14,4);
    DECLARE v_b DECIMAL(14,4);

    DROP TEMPORARY TABLE IF EXISTS check_results;
    CREATE TEMPORARY TABLE check_results (
        check_no INT AUTO_INCREMENT PRIMARY KEY,
        report   VARCHAR(24),
        what     VARCHAR(100),
        figure_a DECIMAL(14,4),
        figure_b DECIMAL(14,4),
        status   VARCHAR(4)
    );

    -- 1. Monthly attendance: every attendance record lands in exactly one month
    SELECT COUNT(*) INTO v_a FROM attendance;
    SELECT SUM(n) INTO v_b FROM (SELECT COUNT(*) AS n
                                   FROM attendance a JOIN class_session cs ON cs.session_id = a.session_id
                                  GROUP BY DATE_FORMAT(cs.session_date, '%Y-%m')) m;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Monthly attendance', 'records in table = records across all monthly buckets', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL'));

    -- 2. Monthly attendance: the months add up to the same % as the attendance function, for every enrolment
    SELECT COUNT(*) INTO v_a FROM enrollment e
     WHERE EXISTS (SELECT 1 FROM attendance a WHERE a.enrollment_id = e.enrollment_id);
    SELECT COUNT(*) INTO v_b
      FROM (SELECT x.enrollment_id,                                   -- add the monthly figures back together
                   ROUND(100 * SUM(x.pres) / NULLIF(SUM(x.cnt), 0), 2) AS pct
              FROM (SELECT a.enrollment_id, DATE_FORMAT(cs.session_date, '%Y-%m') AS mth,
                           SUM(a.status IN ('present','late')) AS pres,
                           SUM(a.status <> 'excused')          AS cnt
                      FROM attendance a JOIN class_session cs ON cs.session_id = a.session_id
                     GROUP BY a.enrollment_id, mth) x
             GROUP BY x.enrollment_id) m
     WHERE ABS(m.pct - fn_attendance_pct(m.enrollment_id)) < 0.01;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Monthly attendance', 'enrolments whose monthly roll-up equals fn_attendance_pct (count)', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL'));

    -- 3. Shortage list: grouped-subquery method vs per-row function method (same set of enrolments)
    SELECT COUNT(*) INTO v_a FROM enrollment e
     WHERE e.status = 'enrolled' AND fn_attendance_pct(e.enrollment_id) < 75;
    SELECT COUNT(*) INTO v_b FROM (SELECT enrollment_id,
                                          ROUND(100 * SUM(status IN ('present','late')) / NULLIF(SUM(status <> 'excused'), 0), 2) AS p
                                     FROM attendance GROUP BY enrollment_id HAVING p < 75) t
      JOIN enrollment e ON e.enrollment_id = t.enrollment_id AND e.status = 'enrolled';
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Attendance shortage', 'students below 75%: function method vs grouped method', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL'));

    -- 4. Late report: count of rows = submissions strictly after the deadline (seconds-based test)
    SELECT COUNT(*) INTO v_a FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
     WHERE s.submitted_on > a.due_date;
    SELECT COUNT(*) INTO v_b FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
     WHERE TIMESTAMPDIFF(SECOND, a.due_date, s.submitted_on) > 0;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Late submissions', 'late rows: date comparison vs TIMESTAMPDIFF(SECOND)', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL') );

    -- 5. Late report: no penalty above 50% and days late is always at least 1
    SELECT COUNT(*) INTO v_a FROM (
        SELECT LEAST(50, 5 * CEILING(TIMESTAMPDIFF(MINUTE, a.due_date, s.submitted_on) / 1440)) AS pen,
               CEILING(TIMESTAMPDIFF(MINUTE, a.due_date, s.submitted_on) / 1440) AS d
          FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
         WHERE s.submitted_on > a.due_date) t
     WHERE pen > 50 OR pen < 5 OR d < 1;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Late submissions', 'rows with a penalty outside 5 to 50% or days_late < 1 (must be 0)', v_a, 0, IF(v_a = 0, 'PASS', 'FAIL'));

    -- 6. Late report: only assignments that allow late work can have late submissions (trigger rule holds)
    SELECT COUNT(*) INTO v_a FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
     WHERE s.submitted_on > a.due_date AND a.allow_late = 0;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Late submissions', 'late rows on assignments that forbid late work (must be 0)', v_a, 0, IF(v_a = 0, 'PASS', 'FAIL'));

    -- 7. Report card: grade points from grade_scale equal an independent CASE ladder, for every result
    SELECT COUNT(*) INTO v_a FROM course_result;
    SELECT COUNT(*) INTO v_b FROM course_result r
      JOIN grade_scale gs ON gs.grade_letter = fn_letter_grade(r.final_percentage)
     WHERE gs.grade_points = CASE WHEN r.final_percentage >= 90 THEN 10 WHEN r.final_percentage >= 80 THEN 9
                                  WHEN r.final_percentage >= 70 THEN 8  WHEN r.final_percentage >= 60 THEN 7
                                  WHEN r.final_percentage >= 50 THEN 6  ELSE 0 END;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Report card', 'course results whose grade points match the CASE ladder', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL'));

    -- 8. Report card: term GPA of the first student computed two ways
    --    (a) grade_scale join, as in sp_report_card   (b) ladder over the percentage
    SELECT ROUND(SUM(gs.grade_points * c.credits) / SUM(c.credits), 2) INTO v_a
      FROM enrollment e JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
      JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
      JOIN course_result r ON r.enrollment_id = e.enrollment_id
      JOIN grade_scale gs ON gs.grade_letter = fn_letter_grade(r.final_percentage)
     WHERE e.student_id = (SELECT MIN(student_id) FROM student) AND e.status <> 'dropped';
    SELECT ROUND(SUM(CASE WHEN r.final_percentage >= 90 THEN 10 WHEN r.final_percentage >= 80 THEN 9
                          WHEN r.final_percentage >= 70 THEN 8  WHEN r.final_percentage >= 60 THEN 7
                          WHEN r.final_percentage >= 50 THEN 6  ELSE 0 END * c.credits) / SUM(c.credits), 2) INTO v_b
      FROM enrollment e JOIN course_offering o ON o.offering_id = e.offering_id JOIN course c ON c.course_id = o.course_id
      JOIN academic_term t ON t.term_id = o.term_id AND t.is_current
      JOIN course_result r ON r.enrollment_id = e.enrollment_id
     WHERE e.student_id = (SELECT MIN(student_id) FROM student) AND e.status <> 'dropped';
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Report card', 'term GPA: grade_scale join vs CASE ladder', v_a, v_b, IF(v_a = v_b, 'PASS', 'FAIL'));

    -- 9. Report card: every enrolment with a result has a final % between 0 and 100
    SELECT COUNT(*) INTO v_a FROM course_result WHERE final_percentage < 0 OR final_percentage > 100;
    INSERT INTO check_results (report, what, figure_a, figure_b, status)
    VALUES ('Report card', 'results outside 0 to 100 (must be 0)', v_a, 0, IF(v_a = 0, 'PASS', 'FAIL'));

    SELECT check_no, report, what, figure_a, figure_b, status FROM check_results ORDER BY check_no;
    SELECT SUM(status = 'PASS') AS passed, SUM(status = 'FAIL') AS failed, COUNT(*) AS total FROM check_results;
END$$

DELIMITER ;

CALL sp_run_phase3_checks();
