-- =====================================================================
-- PHASE 3 sample data: gives the late-submission report something real to report.
-- Run after phase2_data.sql. Everything goes through the Phase 2 triggers.
--
-- Adds "Assignment 3 (Lab)" to the five technical courses of the current term. Late
-- submissions are allowed for it, so trg_submission_bi accepts submissions after the
-- deadline. Pattern per student: ~1 in 7 never submits, ~3 in 7 submit late
-- (3 to 100 hours after the deadline), the rest submit on time.
-- =====================================================================
USE elearning_db;

INSERT INTO assignment (offering_id, title, description, max_marks, assigned_on, due_date, allow_late)
SELECT o.offering_id, 'Assignment 3 (Lab)', 'Lab exercise. Late submissions are accepted with a penalty.',
       25, '2026-09-21 09:00:00', '2026-10-05 23:59:00', TRUE
FROM course_offering o
JOIN academic_term t ON t.term_id = o.term_id
WHERE t.is_current AND o.course_id IN (1, 2, 3, 4, 5) AND o.section_code = 'A';

INSERT INTO submission (assignment_id, enrollment_id, submitted_on, content_url,
                        marks_obtained, graded_by, graded_on, feedback)
SELECT a.assignment_id, e.enrollment_id,
       CASE WHEN MOD(a.assignment_id + e.enrollment_id, 7) IN (1, 2, 3)
            THEN DATE_ADD(a.due_date, INTERVAL 3 + MOD(e.enrollment_id * 11, 98) HOUR)     -- late
            ELSE DATE_SUB(a.due_date, INTERVAL MOD(e.enrollment_id * 5, 72) HOUR)          -- on time
       END,
       CONCAT('https://lms.college.edu/submissions/lab/e', e.enrollment_id, '.zip'),
       ROUND(a.max_marks * (0.55 + MOD(a.assignment_id * 3 + e.enrollment_id * 7, 40) / 100), 1),
       oi.instructor_id,
       DATE_ADD(a.due_date, INTERVAL 6 DAY),
       'Graded.'
FROM assignment a
JOIN enrollment e           ON e.offering_id = a.offering_id AND e.status = 'enrolled'
JOIN offering_instructor oi ON oi.offering_id = a.offering_id AND oi.role = 'primary'
WHERE a.title = 'Assignment 3 (Lab)'
  AND MOD(a.assignment_id + e.enrollment_id, 7) <> 0;                -- the rest never submit

-- Assignment 3 changes everyone's assignment %, so refresh the results
CALL sp_calculate_offering_results(1);
CALL sp_calculate_offering_results(2);
CALL sp_calculate_offering_results(3);
CALL sp_calculate_offering_results(4);
CALL sp_calculate_offering_results(5);

SELECT COUNT(*) AS lab_submissions,
       SUM(s.submitted_on > a.due_date) AS late_ones
FROM submission s JOIN assignment a ON a.assignment_id = s.assignment_id
WHERE a.title = 'Assignment 3 (Lab)';
