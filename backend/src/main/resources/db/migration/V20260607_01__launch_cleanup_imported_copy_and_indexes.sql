ALTER TABLE images
  MODIFY title VARCHAR(160) NULL,
  MODIFY content TEXT NULL;

UPDATE images
SET title = NULL,
    content = NULL
WHERE content = 'Imported image'
   OR title REGEXP '^[0-9a-fA-F]{16,64}$'
   OR author_id = (SELECT id FROM app_users WHERE username = 'mira' LIMIT 1);

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
  'images',
  'idx_images_status_published_id',
  'KEY idx_images_status_published_id (status, published_at, id)'
)$$

CALL add_index_if_missing(
  'images',
  'idx_images_status_category_ratio_hot',
  'KEY idx_images_status_category_ratio_hot (status, main_category_id, ratio, hot_score, published_at, id)'
)$$

CALL add_index_if_missing(
  'image_tags',
  'idx_image_tags_image_confidence',
  'KEY idx_image_tags_image_confidence (image_id, confidence, tag_id)'
)$$

CALL add_index_if_missing(
  'image_tags',
  'idx_image_tags_tag_image_confidence',
  'KEY idx_image_tags_tag_image_confidence (tag_id, image_id, confidence)'
)$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_user_type_time_image',
  'KEY idx_user_behaviors_user_type_time_image (user_id, behavior_type, created_at, image_id)'
)$$

CALL add_index_if_missing(
  'follows',
  'idx_follows_follower_followee_time',
  'KEY idx_follows_follower_followee_time (follower_id, followee_id, created_at)'
)$$

DROP PROCEDURE add_index_if_missing$$

DELIMITER ;
