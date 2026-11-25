-- =====================================================================
-- EduHub LMS | Final-phase schema additions (MySQL 8.0.16+)
-- Adds: file uploads, QR attendance, timetable, holidays, notifications,
-- feedback, service requests, fees, mentorship, audit trail, login throttling.
-- Phase 1 tables are only extended (new columns), never redefined.
-- Run after schema.sql, seed.sql and the phase 2/3 scripts.
-- =====================================================================
USE elearning_db;

-- ---------------------------------------------------------------------
-- 1. Study material: real file uploads next to the old link-only rows
-- ---------------------------------------------------------------------
ALTER TABLE material
    MODIFY resource_url VARCHAR(500) NULL,
    ADD COLUMN stored_name   VARCHAR(120) NULL AFTER resource_url,   -- name on disk (random)
    ADD COLUMN original_name VARCHAR(255) NULL AFTER stored_name,    -- name the professor uploaded
    ADD COLUMN file_size     INT UNSIGNED NULL AFTER original_name,
    ADD COLUMN mime_type     VARCHAR(100) NULL AFTER file_size,
    ADD COLUMN description   VARCHAR(300) NULL AFTER title,
    ADD COLUMN is_published  BOOLEAN NOT NULL DEFAULT TRUE,
    ADD CONSTRAINT chk_material_source CHECK (resource_url IS NOT NULL OR stored_name IS NOT NULL);

-- ---------------------------------------------------------------------
-- 2. Attendance: how a mark was made, and when
-- ---------------------------------------------------------------------
ALTER TABLE attendance
    ADD COLUMN marked_via ENUM('manual','qr','system') NOT NULL DEFAULT 'manual',
    ADD COLUMN marked_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- One open QR window per class session. The secret never leaves the server;
-- the QR shows a code derived from it that changes every 30 seconds.
CREATE TABLE qr_window (
    session_id INT PRIMARY KEY,
    secret     CHAR(32)  NOT NULL,
    opened_by  INT       NOT NULL,
    opened_at  DATETIME  NOT NULL,
    late_after DATETIME  NOT NULL,          -- scans after this count as 'late'
    closes_at  DATETIME  NOT NULL,          -- scans after this are refused
    FOREIGN KEY (session_id) REFERENCES class_session(session_id) ON DELETE CASCADE,
    FOREIGN KEY (opened_by)  REFERENCES instructor(instructor_id) ON DELETE RESTRICT,
    CHECK (late_after >= opened_at AND closes_at >= late_after)
);

-- Every scan, good or bad (no foreign keys on purpose: a forged id must still be logged)
CREATE TABLE attendance_scan_log (
    scan_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NULL,
    student_id INT NULL,
    scanned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    outcome    VARCHAR(40) NOT NULL,
    ip_address VARCHAR(45) NULL,
    INDEX idx_scan_student (student_id, scanned_at),
    INDEX idx_scan_session (session_id, outcome)
);

-- ---------------------------------------------------------------------
-- 3. Timetable and holidays
-- ---------------------------------------------------------------------
CREATE TABLE timetable_slot (
    slot_id     INT AUTO_INCREMENT PRIMARY KEY,
    offering_id INT NOT NULL,
    day_of_week TINYINT NOT NULL,                       -- ISO: 1 = Monday ... 7 = Sunday
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    room        VARCHAR(30) NOT NULL,
    slot_type   ENUM('lecture','lab','tutorial') NOT NULL DEFAULT 'lecture',
    UNIQUE (offering_id, day_of_week, start_time),
    FOREIGN KEY (offering_id) REFERENCES course_offering(offering_id) ON DELETE CASCADE,
    CHECK (day_of_week BETWEEN 1 AND 7),
    CHECK (end_time > start_time)
);

CREATE TABLE holiday (
    holiday_id   INT AUTO_INCREMENT PRIMARY KEY,
    holiday_date DATE NOT NULL UNIQUE,
    name         VARCHAR(100) NOT NULL,
    kind         ENUM('public','institute','exam_break') NOT NULL DEFAULT 'public'
);

-- ---------------------------------------------------------------------
-- 4. Notifications (broadcast, per course, or to one student)
-- ---------------------------------------------------------------------
CREATE TABLE notification (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    audience        ENUM('all','students','instructors','offering','student') NOT NULL DEFAULT 'all',
    offering_id     INT NULL,
    student_id      INT NULL,
    category        ENUM('general','academic','exam','fees','event') NOT NULL DEFAULT 'general',
    title           VARCHAR(150) NOT NULL,
    body            TEXT,
    created_by_user INT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (offering_id)     REFERENCES course_offering(offering_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id)      REFERENCES student(student_id)          ON DELETE CASCADE,
    FOREIGN KEY (created_by_user) REFERENCES user_account(user_id)        ON DELETE SET NULL,
    CHECK ((audience = 'offering') = (offering_id IS NOT NULL)),
    CHECK ((audience = 'student')  = (student_id  IS NOT NULL)),
    INDEX idx_notification_created (created_at),
    INDEX idx_notification_offering (offering_id, created_at),
    INDEX idx_notification_student (student_id, created_at)
);

CREATE TABLE notification_read (
    user_id         INT NOT NULL,
    notification_id INT NOT NULL,
    read_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, notification_id),
    FOREIGN KEY (user_id)         REFERENCES user_account(user_id)           ON DELETE CASCADE,
    FOREIGN KEY (notification_id) REFERENCES notification(notification_id)  ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 5. Feedback, service requests, fees, mentorship
-- ---------------------------------------------------------------------
CREATE TABLE course_feedback (
    enrollment_id     INT PRIMARY KEY,
    rating_content    TINYINT NOT NULL,
    rating_teaching   TINYINT NOT NULL,
    rating_assessment TINYINT NOT NULL,
    comment           VARCHAR(1000),
    submitted_on      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (enrollment_id) REFERENCES enrollment(enrollment_id) ON DELETE CASCADE,
    CHECK (rating_content    BETWEEN 1 AND 5),
    CHECK (rating_teaching   BETWEEN 1 AND 5),
    CHECK (rating_assessment BETWEEN 1 AND 5)
);

CREATE TABLE service_request (
    request_id      INT AUTO_INCREMENT PRIMARY KEY,
    student_id      INT NOT NULL,
    category        ENUM('grievance','bonafide_certificate','transcript','id_card',
                         'fee_issue','attendance_correction','other') NOT NULL,
    subject         VARCHAR(150) NOT NULL,
    description     TEXT,
    status          ENUM('open','in_progress','resolved','rejected') NOT NULL DEFAULT 'open',
    response        TEXT NULL,
    handled_by_user INT NULL,
    created_on      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_on     DATETIME NULL,
    FOREIGN KEY (student_id)      REFERENCES student(student_id)   ON DELETE CASCADE,
    FOREIGN KEY (handled_by_user) REFERENCES user_account(user_id) ON DELETE SET NULL,
    INDEX idx_request_status (status, created_on),
    INDEX idx_request_student (student_id, created_on)
);

CREATE TABLE fee_invoice (
    invoice_id  INT AUTO_INCREMENT PRIMARY KEY,
    student_id  INT NOT NULL,
    term_id     INT NOT NULL,
    description VARCHAR(150) NOT NULL,
    amount      DECIMAL(10,2) NOT NULL,
    due_date    DATE NOT NULL,
    created_on  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student(student_id)        ON DELETE CASCADE,
    FOREIGN KEY (term_id)    REFERENCES academic_term(term_id)     ON DELETE RESTRICT,
    CHECK (amount > 0),
    INDEX idx_invoice_student (student_id, term_id)
);

CREATE TABLE fee_payment (
    payment_id       INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id       INT NOT NULL,
    amount           DECIMAL(10,2) NOT NULL,
    paid_on          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mode             ENUM('upi','card','netbanking','neft','cash') NOT NULL,
    reference_no     VARCHAR(40) NOT NULL UNIQUE,
    recorded_by_user INT NULL,
    FOREIGN KEY (invoice_id)       REFERENCES fee_invoice(invoice_id) ON DELETE RESTRICT,
    FOREIGN KEY (recorded_by_user) REFERENCES user_account(user_id)   ON DELETE SET NULL,
    CHECK (amount > 0)
);

CREATE TABLE mentorship (
    student_id    INT PRIMARY KEY,
    instructor_id INT NOT NULL,
    assigned_on   DATE NOT NULL DEFAULT (CURRENT_DATE),
    FOREIGN KEY (student_id)    REFERENCES student(student_id)       ON DELETE CASCADE,
    FOREIGN KEY (instructor_id) REFERENCES instructor(instructor_id) ON DELETE RESTRICT,
    INDEX idx_mentor_instructor (instructor_id)
);

-- ---------------------------------------------------------------------
-- 6. Security support: audit trail (append-only), login throttling
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    log_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    occurred_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    actor       VARCHAR(80)  NOT NULL,
    action      VARCHAR(40)  NOT NULL,
    entity      VARCHAR(40)  NOT NULL,
    entity_id   VARCHAR(40)  NULL,
    detail      VARCHAR(500) NULL,
    ip_address  VARCHAR(45)  NULL,
    INDEX idx_audit_time (occurred_at),
    INDEX idx_audit_entity (entity, entity_id)
);

CREATE TABLE login_attempt (
    attempt_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
    username     VARCHAR(50) NOT NULL,
    ip_address   VARCHAR(45) NOT NULL,
    attempted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success      BOOLEAN NOT NULL,
    INDEX idx_login_user (username, attempted_at),
    INDEX idx_login_ip (ip_address, attempted_at)
);

ALTER TABLE user_account
    ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN password_changed_on  DATETIME NULL;

-- ---------------------------------------------------------------------
-- 7. Quizzes: remember when an attempt was handed in
-- ---------------------------------------------------------------------
ALTER TABLE quiz_attempt ADD COLUMN submitted_on DATETIME NULL;
UPDATE quiz_attempt SET submitted_on = attempted_on WHERE score IS NOT NULL;

-- ---------------------------------------------------------------------
-- 8. Views used by the app and the reports
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_attendance_detail AS
SELECT e.student_id, e.enrollment_id, e.offering_id, c.course_code, c.title AS course_title,
       cs.session_id, cs.session_date, cs.start_time, cs.end_time, cs.topic,
       a.status, a.marked_via, a.marked_at
  FROM enrollment e
  JOIN class_session cs   ON cs.offering_id = e.offering_id
  JOIN course_offering o  ON o.offering_id = e.offering_id
  JOIN course c           ON c.course_id = o.course_id
  LEFT JOIN attendance a  ON a.session_id = cs.session_id AND a.enrollment_id = e.enrollment_id
 WHERE e.status <> 'dropped';

CREATE OR REPLACE VIEW v_fee_invoice_status AS
SELECT i.invoice_id, i.student_id, i.term_id, i.description, i.amount, i.due_date,
       COALESCE(SUM(p.amount), 0) AS paid,
       i.amount - COALESCE(SUM(p.amount), 0) AS balance,
       CASE WHEN COALESCE(SUM(p.amount), 0) >= i.amount THEN 'paid'
            WHEN i.due_date < CURRENT_DATE               THEN 'overdue'
            WHEN COALESCE(SUM(p.amount), 0) > 0          THEN 'partial'
            ELSE 'due' END AS status
  FROM fee_invoice i
  LEFT JOIN fee_payment p ON p.invoice_id = i.invoice_id
 GROUP BY i.invoice_id, i.student_id, i.term_id, i.description, i.amount, i.due_date;

-- ---------------------------------------------------------------------
-- 9. Curriculum map: which course belongs to which semester of which programme
--    (filled from the department handbook by scripts/import_catalog.py)
-- ---------------------------------------------------------------------
CREATE TABLE program_course (
    program_id  INT NOT NULL,
    course_id   INT NOT NULL,
    semester    TINYINT NOT NULL,
    course_type ENUM('core','elective','lab','non_credit') NOT NULL DEFAULT 'core',
    PRIMARY KEY (program_id, course_id),
    FOREIGN KEY (program_id) REFERENCES program(program_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id)  REFERENCES course(course_id)   ON DELETE CASCADE,
    CHECK (semester BETWEEN 1 AND 12),
    INDEX idx_program_semester (program_id, semester)
);
