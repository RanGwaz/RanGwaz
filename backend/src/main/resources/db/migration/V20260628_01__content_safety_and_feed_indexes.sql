DROP PROCEDURE IF EXISTS add_index_if_missing;

DELIMITER $$

CREATE PROCEDURE add_index_if_missing(
  IN p_table_name VARCHAR(64),
  IN p_index_name VARCHAR(64),
  IN p_index_ddl TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND index_name = p_index_name
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE ', p_table_name, ' ADD ', p_index_ddl);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_user_time_image_type',
  'KEY idx_user_behaviors_user_time_image_type (user_id, created_at, image_id, behavior_type)'
)$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_visitor_time_image_type',
  'KEY idx_user_behaviors_visitor_time_image_type (visitor_id, created_at, image_id, behavior_type)'
)$$

DROP PROCEDURE add_index_if_missing$$

DELIMITER ;
