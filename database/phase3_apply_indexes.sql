-- =====================================================================
-- PHASE 3 (indexes only): the helper procedures and the two indexes that earned their place.
-- Part of the standard install. The 450,000-row before/after benchmark lives in phase3_indexes.sql
-- and is optional:  python setup_db.py --with-benchmark
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
