DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;

DELIMITER $$

CREATE PROCEDURE add_column_if_missing(
  IN p_table_name VARCHAR(64),
  IN p_column_name VARCHAR(64),
  IN p_column_ddl TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE ', p_table_name, ' ADD COLUMN ', p_column_ddl);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$

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

CALL add_column_if_missing(
  'user_behaviors',
  'visitor_id',
  'visitor_id VARCHAR(64) NULL AFTER user_id'
)$$

CALL add_column_if_missing(
  'feed_impressions',
  'visitor_id',
  'visitor_id VARCHAR(64) NULL AFTER user_id'
)$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_visitor_time',
  'KEY idx_user_behaviors_visitor_time (visitor_id, created_at)'
)$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_visitor_image_type_time',
  'KEY idx_user_behaviors_visitor_image_type_time (visitor_id, image_id, behavior_type, created_at)'
)$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_visitor_type_time_image',
  'KEY idx_user_behaviors_visitor_type_time_image (visitor_id, behavior_type, created_at, image_id)'
)$$

CALL add_index_if_missing(
  'feed_impressions',
  'idx_feed_impressions_visitor_time',
  'KEY idx_feed_impressions_visitor_time (visitor_id, created_at)'
)$$

CALL add_index_if_missing(
  'images',
  'idx_images_status_hot_published_id',
  'KEY idx_images_status_hot_published_id (status, hot_score, published_at, id)'
)$$

DROP PROCEDURE add_column_if_missing$$
DROP PROCEDURE add_index_if_missing$$

DELIMITER ;
