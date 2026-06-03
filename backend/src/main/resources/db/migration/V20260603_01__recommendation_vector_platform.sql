CREATE TABLE IF NOT EXISTS feed_impressions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  image_id BIGINT NOT NULL,
  scene VARCHAR(32) NOT NULL DEFAULT 'home',
  position_no INT,
  source VARCHAR(32) NOT NULL DEFAULT 'mysql',
  score DECIMAL(12,6),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_feed_impressions_user_time (user_id, created_at),
  KEY idx_feed_impressions_image_time (image_id, created_at),
  CONSTRAINT fk_feed_impressions_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL,
  CONSTRAINT fk_feed_impressions_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS image_embeddings (
  image_id BIGINT NOT NULL,
  model_name VARCHAR(120) NOT NULL,
  vector_version VARCHAR(40) NOT NULL DEFAULT 'v1',
  vector_dimension INT NOT NULL DEFAULT 512,
  image_hash VARCHAR(128),
  milvus_collection VARCHAR(80) NOT NULL DEFAULT 'vibelo_image_vectors',
  milvus_pk BIGINT,
  status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
  last_error VARCHAR(500),
  embedded_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (image_id, model_name, vector_version),
  KEY idx_image_embeddings_image (image_id),
  KEY idx_image_embeddings_status (status, updated_at),
  KEY idx_image_embeddings_model_version (model_name, vector_version),
  CONSTRAINT fk_image_embeddings_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_candidates (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  scene VARCHAR(32) NOT NULL DEFAULT 'home',
  source VARCHAR(32) NOT NULL DEFAULT 'vector',
  image_id BIGINT NOT NULL,
  score DECIMAL(14,8) NOT NULL DEFAULT 0,
  reason VARCHAR(120),
  expires_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_recommendation_candidates_user_scene (user_id, scene, score, created_at),
  KEY idx_recommendation_candidates_image (image_id),
  CONSTRAINT fk_recommendation_candidates_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_recommendation_candidates_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_interest_snapshots (
  user_id BIGINT PRIMARY KEY,
  model_name VARCHAR(120) NOT NULL,
  vector_version VARCHAR(40) NOT NULL DEFAULT 'v1',
  positive_image_count INT NOT NULL DEFAULT 0,
  interest_json JSON,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_interest_snapshots_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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

CALL add_column_if_missing('image_embeddings', 'vector_dimension', 'vector_dimension INT NOT NULL DEFAULT 512 AFTER vector_version')$$
CALL add_column_if_missing('image_embeddings', 'image_hash', 'image_hash VARCHAR(128) AFTER vector_dimension')$$

CALL add_index_if_missing(
  'user_behaviors',
  'idx_user_behaviors_user_image_type_time',
  'KEY idx_user_behaviors_user_image_type_time (user_id, image_id, behavior_type, created_at)'
)$$

CALL add_index_if_missing(
  'images',
  'idx_images_vector_base',
  'KEY idx_images_vector_base (status, id, main_category_id)'
)$$

DROP PROCEDURE add_column_if_missing$$
DROP PROCEDURE add_index_if_missing$$

DELIMITER ;
