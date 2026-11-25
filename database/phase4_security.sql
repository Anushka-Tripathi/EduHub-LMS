-- =====================================================================
-- EduHub LMS | Phase 4: database roles and least-privilege grants (MySQL 8.0)
-- The web application connects as a low-privilege user that holds lms_app_role:
--   * data changes only (no CREATE / ALTER / DROP / GRANT)
--   * audit_log is read-only: rows are written by triggers and sp_log_event (definer rights)
--   * grade_scale (the marking policy) cannot be edited by the app
-- setup_db.py creates the login and attaches the role:
--   CREATE USER 'lms_app'@'<host>' IDENTIFIED BY '<DB_PASSWORD>';  GRANT 'lms_app_role' TO ...;
-- =====================================================================
USE elearning_db;

CREATE ROLE IF NOT EXISTS 'lms_app_role', 'lms_report_role', 'lms_dba_role';

-- ---- application role --------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.academic_term TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.assignment TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.attendance TO 'lms_app_role';
GRANT SELECT, INSERT ON elearning_db.attendance_scan_log TO 'lms_app_role';
GRANT SELECT ON elearning_db.audit_log TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.class_session TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.course TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.course_feedback TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.course_offering TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.course_prerequisite TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.course_result TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.department TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.enrollment TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.fee_invoice TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.fee_payment TO 'lms_app_role';
GRANT SELECT ON elearning_db.grade_scale TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.holiday TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.instructor TO 'lms_app_role';
GRANT SELECT, INSERT, DELETE ON elearning_db.login_attempt TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.material TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.mentorship TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.module TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.notification TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.notification_read TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.offering_instructor TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.program TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.program_course TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.qr_window TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.question TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.question_option TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.quiz TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.quiz_answer TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.quiz_attempt TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.service_request TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.student TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.submission TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.timetable_slot TO 'lms_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON elearning_db.user_account TO 'lms_app_role';
GRANT SELECT ON elearning_db.v_attendance_detail TO 'lms_app_role';
GRANT SELECT ON elearning_db.v_fee_invoice_status TO 'lms_app_role';
GRANT EXECUTE ON elearning_db.* TO 'lms_app_role';          -- stored procedures and functions

-- ---- reporting role: read-only, no password hashes or login history ----------
GRANT SELECT ON elearning_db.academic_term TO 'lms_report_role';
GRANT SELECT ON elearning_db.assignment TO 'lms_report_role';
GRANT SELECT ON elearning_db.attendance TO 'lms_report_role';
GRANT SELECT ON elearning_db.attendance_scan_log TO 'lms_report_role';
GRANT SELECT ON elearning_db.audit_log TO 'lms_report_role';
GRANT SELECT ON elearning_db.class_session TO 'lms_report_role';
GRANT SELECT ON elearning_db.course TO 'lms_report_role';
GRANT SELECT ON elearning_db.course_feedback TO 'lms_report_role';
GRANT SELECT ON elearning_db.course_offering TO 'lms_report_role';
GRANT SELECT ON elearning_db.course_prerequisite TO 'lms_report_role';
GRANT SELECT ON elearning_db.course_result TO 'lms_report_role';
GRANT SELECT ON elearning_db.department TO 'lms_report_role';
GRANT SELECT ON elearning_db.enrollment TO 'lms_report_role';
GRANT SELECT ON elearning_db.fee_invoice TO 'lms_report_role';
GRANT SELECT ON elearning_db.fee_payment TO 'lms_report_role';
GRANT SELECT ON elearning_db.grade_scale TO 'lms_report_role';
GRANT SELECT ON elearning_db.holiday TO 'lms_report_role';
GRANT SELECT ON elearning_db.instructor TO 'lms_report_role';
GRANT SELECT ON elearning_db.material TO 'lms_report_role';
GRANT SELECT ON elearning_db.mentorship TO 'lms_report_role';
GRANT SELECT ON elearning_db.module TO 'lms_report_role';
GRANT SELECT ON elearning_db.notification TO 'lms_report_role';
GRANT SELECT ON elearning_db.notification_read TO 'lms_report_role';
GRANT SELECT ON elearning_db.offering_instructor TO 'lms_report_role';
GRANT SELECT ON elearning_db.program TO 'lms_report_role';
GRANT SELECT ON elearning_db.program_course TO 'lms_report_role';
GRANT SELECT ON elearning_db.qr_window TO 'lms_report_role';
GRANT SELECT ON elearning_db.question TO 'lms_report_role';
GRANT SELECT ON elearning_db.question_option TO 'lms_report_role';
GRANT SELECT ON elearning_db.quiz TO 'lms_report_role';
GRANT SELECT ON elearning_db.quiz_answer TO 'lms_report_role';
GRANT SELECT ON elearning_db.quiz_attempt TO 'lms_report_role';
GRANT SELECT ON elearning_db.service_request TO 'lms_report_role';
GRANT SELECT ON elearning_db.student TO 'lms_report_role';
GRANT SELECT ON elearning_db.submission TO 'lms_report_role';
GRANT SELECT ON elearning_db.timetable_slot TO 'lms_report_role';
GRANT SELECT ON elearning_db.v_attendance_detail TO 'lms_report_role';
GRANT SELECT ON elearning_db.v_fee_invoice_status TO 'lms_report_role';
GRANT EXECUTE ON PROCEDURE elearning_db.sp_report_attendance_by_month TO 'lms_report_role';
GRANT EXECUTE ON PROCEDURE elearning_db.sp_report_attendance_shortage TO 'lms_report_role';
GRANT EXECUTE ON PROCEDURE elearning_db.sp_report_card TO 'lms_report_role';
GRANT EXECUTE ON PROCEDURE elearning_db.sp_report_late_submissions TO 'lms_report_role';
GRANT EXECUTE ON PROCEDURE elearning_db.sp_report_monthly_attendance TO 'lms_report_role';   -- reports only, no data-changing procedures

-- ---- database administrator --------------------------------------------
GRANT ALL PRIVILEGES ON elearning_db.* TO 'lms_dba_role';
