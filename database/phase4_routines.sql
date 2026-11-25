-- =====================================================================
-- EduHub LMS | Final-phase routines: QR attendance, quiz taking, timetable,
-- notification triggers, audit triggers.  Run after phase4_schema.sql.
-- =====================================================================
USE elearning_db;
DELIMITER $$

-- ---------------------------------------------------------------------
-- Audit helper: the only way the application writes to audit_log
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_log_event$$
CREATE PROCEDURE sp_log_event(IN p_actor VARCHAR(80), IN p_action VARCHAR(40), IN p_entity VARCHAR(40),
                              IN p_entity_id VARCHAR(40), IN p_detail VARCHAR(500), IN p_ip VARCHAR(45))
BEGIN
    INSERT INTO audit_log (actor, action, entity, entity_id, detail, ip_address)
    VALUES (COALESCE(p_actor, 'system'), p_action, p_entity, p_entity_id, p_detail, p_ip);
END$$

-- ---------------------------------------------------------------------
-- QR attendance
-- ---------------------------------------------------------------------
-- Instructor opens the window for a class session held today.
DROP PROCEDURE IF EXISTS sp_open_qr_window$$
CREATE PROCEDURE sp_open_qr_window(IN p_session_id INT, IN p_instructor_id INT,
                                   IN p_minutes_open INT, IN p_late_after_minutes INT)
BEGIN
    DECLARE v_offering INT;
    DECLARE v_date     DATE;
    DECLARE v_now      DATETIME DEFAULT NOW();

    SELECT offering_id, session_date INTO v_offering, v_date
      FROM class_session WHERE session_id = p_session_id;
    IF v_offering IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'QR attendance: class session not found.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM offering_instructor
                    WHERE offering_id = v_offering AND instructor_id = p_instructor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'QR attendance: you do not teach this course.';
    END IF;
    IF v_date <> CURDATE() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'QR attendance can only be opened on the day of the class.';
    END IF;
    IF p_minutes_open NOT BETWEEN 1 AND 180 OR p_late_after_minutes NOT BETWEEN 0 AND p_minutes_open THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'QR attendance: open for 1-180 minutes; late-after must not exceed that.';
    END IF;

    INSERT INTO qr_window (session_id, secret, opened_by, opened_at, late_after, closes_at)
    VALUES (p_session_id, LOWER(HEX(RANDOM_BYTES(16))), p_instructor_id, v_now,
            v_now + INTERVAL p_late_after_minutes MINUTE, v_now + INTERVAL p_minutes_open MINUTE)
    ON DUPLICATE KEY UPDATE secret = VALUES(secret), opened_by = VALUES(opened_by),
                            opened_at = VALUES(opened_at), late_after = VALUES(late_after),
                            closes_at = VALUES(closes_at);
    CALL sp_log_event(COALESCE(@app_user, CONCAT('instructor#', p_instructor_id)), 'QR_OPEN',
                      'class_session', p_session_id,
                      CONCAT('open ', p_minutes_open, ' min, late after ', p_late_after_minutes, ' min'), NULL);
END$$

DROP PROCEDURE IF EXISTS sp_close_qr_window$$
CREATE PROCEDURE sp_close_qr_window(IN p_session_id INT, IN p_instructor_id INT)
BEGIN
    UPDATE qr_window w
      JOIN class_session cs ON cs.session_id = w.session_id
      JOIN offering_instructor oi ON oi.offering_id = cs.offering_id AND oi.instructor_id = p_instructor_id
       SET w.closes_at = LEAST(w.closes_at, NOW()), w.late_after = LEAST(w.late_after, NOW())
     WHERE w.session_id = p_session_id;
END$$

-- The student's scan. The app has already checked the rotating code; this decides what is recorded.
DROP PROCEDURE IF EXISTS sp_mark_attendance_qr$$
CREATE PROCEDURE sp_mark_attendance_qr(IN p_session_id INT, IN p_student_id INT)
BEGIN
    DECLARE v_offering   INT;
    DECLARE v_enrollment INT;
    DECLARE v_late_after DATETIME;
    DECLARE v_closes     DATETIME;
    DECLARE v_old        VARCHAR(10);
    DECLARE v_status     VARCHAR(10);

    SELECT cs.offering_id, w.late_after, w.closes_at INTO v_offering, v_late_after, v_closes
      FROM class_session cs JOIN qr_window w ON w.session_id = cs.session_id
     WHERE cs.session_id = p_session_id;
    IF v_offering IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Attendance is not open for this class.';
    END IF;
    IF NOW() > v_closes THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The attendance window for this class has closed.';
    END IF;

    SELECT enrollment_id INTO v_enrollment FROM enrollment
     WHERE student_id = p_student_id AND offering_id = v_offering AND status = 'enrolled';
    IF v_enrollment IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You are not enrolled in this course.';
    END IF;

    SELECT status INTO v_old FROM attendance WHERE session_id = p_session_id AND enrollment_id = v_enrollment;
    IF v_old IN ('present', 'late') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Your attendance is already marked for this class.';
    END IF;
    IF v_old = 'excused' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You are marked excused for this class; nothing to record.';
    END IF;

    SET v_status = IF(NOW() <= v_late_after, 'present', 'late');
    INSERT INTO attendance (session_id, enrollment_id, status, marked_via, marked_at)
    VALUES (p_session_id, v_enrollment, v_status, 'qr', NOW())
    ON DUPLICATE KEY UPDATE status = VALUES(status), marked_via = 'qr', marked_at = VALUES(marked_at);

    SELECT v_status AS status, v_enrollment AS enrollment_id;
END$$

-- After the window closes: everybody enrolled without a mark becomes absent (all or nothing)
DROP PROCEDURE IF EXISTS sp_finish_session_attendance$$
CREATE PROCEDURE sp_finish_session_attendance(IN p_session_id INT, IN p_instructor_id INT)
BEGIN
    DECLARE v_offering INT;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

    SELECT offering_id INTO v_offering FROM class_session WHERE session_id = p_session_id;
    IF NOT EXISTS (SELECT 1 FROM offering_instructor
                    WHERE offering_id = v_offering AND instructor_id = p_instructor_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You do not teach this course.';
    END IF;
    START TRANSACTION;
    INSERT INTO attendance (session_id, enrollment_id, status, marked_via)
    SELECT p_session_id, e.enrollment_id, 'absent', 'system'
      FROM enrollment e
     WHERE e.offering_id = v_offering AND e.status = 'enrolled'
       AND NOT EXISTS (SELECT 1 FROM attendance a
                        WHERE a.session_id = p_session_id AND a.enrollment_id = e.enrollment_id);
    SELECT ROW_COUNT() AS marked_absent;
    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Timetable -> class sessions (skips holidays)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_generate_sessions$$
CREATE PROCEDURE sp_generate_sessions(IN p_offering_id INT, IN p_from DATE, IN p_to DATE)
BEGIN
    IF p_to < p_from OR DATEDIFF(p_to, p_from) > 366 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose a date range of at most one year.';
    END IF;
    INSERT IGNORE INTO class_session (offering_id, session_date, start_time, end_time, topic)
    WITH RECURSIVE d (dt) AS (
        SELECT p_from UNION ALL SELECT dt + INTERVAL 1 DAY FROM d WHERE dt < p_to
    )
    SELECT p_offering_id, d.dt, ts.start_time, ts.end_time, NULL
      FROM d
      JOIN timetable_slot ts ON ts.offering_id = p_offering_id AND ts.day_of_week = WEEKDAY(d.dt) + 1
      LEFT JOIN holiday h ON h.holiday_date = d.dt
     WHERE h.holiday_id IS NULL;
    SELECT ROW_COUNT() AS sessions_created;
END$$

-- ---------------------------------------------------------------------
-- Quiz taking: start (or resume) an attempt, hand in all answers at once
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_start_quiz_attempt$$
CREATE PROCEDURE sp_start_quiz_attempt(IN p_quiz_id INT, IN p_enrollment_id INT)
BEGIN
    DECLARE v_limit   SMALLINT;
    DECLARE v_open    INT;
    SELECT time_limit_minutes INTO v_limit FROM quiz WHERE quiz_id = p_quiz_id;
    -- resume an unfinished attempt that is still inside its time limit
    SELECT attempt_id INTO v_open FROM quiz_attempt
     WHERE quiz_id = p_quiz_id AND enrollment_id = p_enrollment_id AND submitted_on IS NULL
       AND attempted_on + INTERVAL v_limit MINUTE > NOW()
     ORDER BY attempt_id DESC LIMIT 1;
    IF v_open IS NULL THEN
        INSERT INTO quiz_attempt (quiz_id, enrollment_id) VALUES (p_quiz_id, p_enrollment_id); -- trigger checks open window, attempts, enrolment
        SET v_open = LAST_INSERT_ID();
    END IF;
    SELECT v_open AS attempt_id;
END$$

-- p_answers: JSON array like [{"q": 12, "o": 40}, {"q": 13, "o": 44}]
DROP PROCEDURE IF EXISTS sp_submit_quiz_attempt$$
CREATE PROCEDURE sp_submit_quiz_attempt(IN p_attempt_id INT, IN p_enrollment_id INT, IN p_answers JSON)
BEGIN
    DECLARE v_start  DATETIME;
    DECLARE v_done   DATETIME;
    DECLARE v_limit  SMALLINT;
    DECLARE v_score  DECIMAL(6,2);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

    SELECT qa.attempted_on, qa.submitted_on, q.time_limit_minutes INTO v_start, v_done, v_limit
      FROM quiz_attempt qa JOIN quiz q ON q.quiz_id = qa.quiz_id
     WHERE qa.attempt_id = p_attempt_id AND qa.enrollment_id = p_enrollment_id;
    IF v_start IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Quiz attempt not found.';
    END IF;
    IF v_done IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This attempt was already submitted.';
    END IF;

    START TRANSACTION;
    IF NOW() > v_start + INTERVAL v_limit MINUTE + INTERVAL 30 SECOND THEN      -- 30 s grace for the network
        UPDATE quiz_attempt SET score = 0, submitted_on = NOW() WHERE attempt_id = p_attempt_id;
        COMMIT;
        SELECT 'timed_out' AS outcome, 0 AS score;
    ELSE
        INSERT INTO quiz_answer (attempt_id, question_id, selected_option_id)
        SELECT p_attempt_id, jt.q, jt.o
          FROM JSON_TABLE(p_answers, '$[*]' COLUMNS (q INT PATH '$.q', o INT PATH '$.o')) jt;
        CALL sp_score_quiz_attempt(p_attempt_id);
        UPDATE quiz_attempt SET submitted_on = NOW() WHERE attempt_id = p_attempt_id;
        SELECT score INTO v_score FROM quiz_attempt WHERE attempt_id = p_attempt_id;
        COMMIT;
        SELECT 'submitted' AS outcome, v_score AS score;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Notification triggers: students hear about new work without anyone typing a notice
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_assignment_ai$$
CREATE TRIGGER trg_assignment_ai AFTER INSERT ON assignment
FOR EACH ROW
BEGIN
    IF COALESCE(@suppress_notifications, 0) = 0 THEN      -- bulk loaders set this to 1
        INSERT INTO notification (audience, offering_id, category, title, body)
        VALUES ('offering', NEW.offering_id, 'academic', CONCAT('New assignment: ', NEW.title),
                CONCAT('Due ', DATE_FORMAT(NEW.due_date, '%d %b %Y, %H:%i'), '. Max marks ', NEW.max_marks, '.'));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_material_ai$$
CREATE TRIGGER trg_material_ai AFTER INSERT ON material
FOR EACH ROW
BEGIN
    DECLARE v_off INT;
    SELECT offering_id INTO v_off FROM module WHERE module_id = NEW.module_id;
    IF NEW.is_published AND COALESCE(@suppress_notifications, 0) = 0 THEN
        INSERT INTO notification (audience, offering_id, category, title, body)
        VALUES ('offering', v_off, 'academic', CONCAT('New study material: ', NEW.title), NEW.description);
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_quiz_ai$$
CREATE TRIGGER trg_quiz_ai AFTER INSERT ON quiz
FOR EACH ROW
BEGIN
    IF COALESCE(@suppress_notifications, 0) = 0 THEN
        INSERT INTO notification (audience, offering_id, category, title, body)
        VALUES ('offering', NEW.offering_id, 'exam', CONCAT('New quiz: ', NEW.title),
                CONCAT('Open ', DATE_FORMAT(NEW.available_from, '%d %b %H:%i'), ' to ',
                       DATE_FORMAT(NEW.available_until, '%d %b %H:%i'), '. ', NEW.time_limit_minutes, ' minutes.'));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_submission_graded_au$$
CREATE TRIGGER trg_submission_graded_au AFTER UPDATE ON submission
FOR EACH ROW
BEGIN
    DECLARE v_student INT;
    DECLARE v_title   VARCHAR(150);
    IF OLD.marks_obtained IS NULL AND NEW.marks_obtained IS NOT NULL AND COALESCE(@suppress_notifications, 0) = 0 THEN
        SELECT e.student_id INTO v_student FROM enrollment e WHERE e.enrollment_id = NEW.enrollment_id;
        SELECT title INTO v_title FROM assignment WHERE assignment_id = NEW.assignment_id;
        INSERT INTO notification (audience, student_id, category, title, body)
        VALUES ('student', v_student, 'academic', CONCAT('Graded: ', v_title),
                CONCAT('You scored ', NEW.marks_obtained, '.'));
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Audit triggers (who changed marks, results, enrolments, accounts, payments)
-- @app_user is set by the application on every connection; falls back to the MySQL user.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_audit_submission_au$$
CREATE TRIGGER trg_audit_submission_au AFTER UPDATE ON submission
FOR EACH ROW
BEGIN
    IF NOT (OLD.marks_obtained <=> NEW.marks_obtained) THEN
        INSERT INTO audit_log (actor, action, entity, entity_id, detail)
        VALUES (COALESCE(@app_user, CURRENT_USER()), 'GRADE', 'submission', NEW.submission_id,
                CONCAT('marks ', COALESCE(OLD.marks_obtained, 'none'), ' -> ', COALESCE(NEW.marks_obtained, 'none')));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_audit_enrollment_au$$
CREATE TRIGGER trg_audit_enrollment_au AFTER UPDATE ON enrollment
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO audit_log (actor, action, entity, entity_id, detail)
        VALUES (COALESCE(@app_user, CURRENT_USER()), 'ENROLLMENT', 'enrollment', NEW.enrollment_id,
                CONCAT('status ', OLD.status, ' -> ', NEW.status));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_audit_result_ai$$
CREATE TRIGGER trg_audit_result_ai AFTER INSERT ON course_result
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (actor, action, entity, entity_id, detail)
    VALUES (COALESCE(@app_user, CURRENT_USER()), 'RESULT', 'course_result', NEW.enrollment_id,
            CONCAT('final ', NEW.final_percentage, '%'));
END$$

DROP TRIGGER IF EXISTS trg_audit_result_au$$
CREATE TRIGGER trg_audit_result_au AFTER UPDATE ON course_result
FOR EACH ROW
BEGIN
    IF NOT (OLD.final_percentage <=> NEW.final_percentage) THEN
        INSERT INTO audit_log (actor, action, entity, entity_id, detail)
        VALUES (COALESCE(@app_user, CURRENT_USER()), 'RESULT', 'course_result', NEW.enrollment_id,
                CONCAT('final ', OLD.final_percentage, '% -> ', NEW.final_percentage, '%'));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_audit_user_au$$
CREATE TRIGGER trg_audit_user_au AFTER UPDATE ON user_account
FOR EACH ROW
BEGIN
    IF OLD.is_active <> NEW.is_active OR OLD.password_hash <> NEW.password_hash THEN
        INSERT INTO audit_log (actor, action, entity, entity_id, detail)
        VALUES (COALESCE(@app_user, CURRENT_USER()), 'ACCOUNT', 'user_account', NEW.user_id,
                CONCAT(IF(OLD.is_active <> NEW.is_active, CONCAT('active ', OLD.is_active, ' -> ', NEW.is_active, '; '), ''),
                       IF(OLD.password_hash <> NEW.password_hash, 'password changed', '')));
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_audit_payment_ai$$
CREATE TRIGGER trg_audit_payment_ai AFTER INSERT ON fee_payment
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (actor, action, entity, entity_id, detail)
    VALUES (COALESCE(@app_user, CURRENT_USER()), 'PAYMENT', 'fee_invoice', NEW.invoice_id,
            CONCAT(NEW.amount, ' via ', NEW.mode, ' ref ', NEW.reference_no));
END$$

-- Over-payment guard
DROP TRIGGER IF EXISTS trg_payment_bi$$
CREATE TRIGGER trg_payment_bi BEFORE INSERT ON fee_payment
FOR EACH ROW
BEGIN
    DECLARE v_balance DECIMAL(10,2);
    SELECT amount - COALESCE((SELECT SUM(amount) FROM fee_payment WHERE invoice_id = NEW.invoice_id), 0)
      INTO v_balance FROM fee_invoice WHERE invoice_id = NEW.invoice_id FOR UPDATE;
    IF NEW.amount > v_balance THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment rejected: amount is more than the outstanding balance.';
    END IF;
END$$

DELIMITER ;
