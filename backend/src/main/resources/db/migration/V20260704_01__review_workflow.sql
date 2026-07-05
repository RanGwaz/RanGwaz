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

CALL add_column_if_missing('images', 'review_reason', 'review_reason VARCHAR(500) NULL AFTER status')$$
CALL add_column_if_missing('images', 'reviewed_at', 'reviewed_at DATETIME NULL AFTER review_reason')$$
CALL add_index_if_missing('images', 'idx_images_author_status_time', 'KEY idx_images_author_status_time (author_id, status, created_at)')$$

DROP PROCEDURE add_column_if_missing$$
DROP PROCEDURE add_index_if_missing$$

DELIMITER ;

CREATE TABLE IF NOT EXISTS profile_update_reviews (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  nickname VARCHAR(80),
  avatar_url VARCHAR(500),
  background_url VARCHAR(500),
  bio VARCHAR(500),
  status VARCHAR(24) NOT NULL DEFAULT 'PENDING_REVIEW',
  review_reason VARCHAR(500),
  reviewed_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_profile_reviews_user_status_time (user_id, status, created_at),
  KEY idx_profile_reviews_status_time (status, created_at),
  CONSTRAINT fk_profile_reviews_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_notifications (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  type VARCHAR(40) NOT NULL,
  title VARCHAR(120) NOT NULL,
  content VARCHAR(500),
  target_type VARCHAR(40),
  target_id BIGINT,
  is_read TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_notifications_user_time (user_id, created_at),
  KEY idx_user_notifications_user_read_time (user_id, is_read, created_at),
  CONSTRAINT fk_user_notifications_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
