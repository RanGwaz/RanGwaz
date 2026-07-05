-- Clean development schema for the RanGwaz image website.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS feed_impressions;
DROP TABLE IF EXISTS user_interest_snapshots;
DROP TABLE IF EXISTS post_recommendation_features;
DROP TABLE IF EXISTS recommendation_candidates;
DROP TABLE IF EXISTS image_embeddings;
DROP TABLE IF EXISTS user_behaviors;
DROP TABLE IF EXISTS user_interactions;
DROP TABLE IF EXISTS follows;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS image_topics;
DROP TABLE IF EXISTS post_topics;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS image_tags;
DROP TABLE IF EXISTS images;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS post_assets;
DROP TABLE IF EXISTS posts;
DROP TABLE IF EXISTS user_notifications;
DROP TABLE IF EXISTS profile_update_reviews;
DROP TABLE IF EXISTS app_users;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE app_users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  phone VARCHAR(32),
  password_hash VARCHAR(128) NOT NULL,
  nickname VARCHAR(64) NOT NULL,
  avatar_url VARCHAR(512),
  background_url VARCHAR(512),
  bio VARCHAR(280),
  status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_app_users_nickname (nickname),
  UNIQUE KEY uk_app_users_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE profile_update_reviews (
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

CREATE TABLE user_notifications (
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

CREATE TABLE categories (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  parent_id BIGINT,
  slug VARCHAR(120) NOT NULL UNIQUE,
  sort_no INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_categories_name (name),
  KEY idx_categories_parent (parent_id, sort_no),
  CONSTRAINT fk_categories_parent FOREIGN KEY (parent_id) REFERENCES categories(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE tags (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  type VARCHAR(32) NOT NULL,
  slug VARCHAR(120) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tags_type_name (type, name),
  UNIQUE KEY uk_tags_type_slug (type, slug),
  KEY idx_tags_type (type, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE images (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  author_id BIGINT NOT NULL,
  title VARCHAR(160),
  content TEXT,
  post_type VARCHAR(32) NOT NULL DEFAULT 'image',
  description TEXT,
  object_key VARCHAR(180) NOT NULL,
  file_url VARCHAR(512) NOT NULL,
  file_type VARCHAR(32) NOT NULL DEFAULT 'image',
  thumbnail_url VARCHAR(512),
  width INT,
  height INT,
  ratio VARCHAR(32),
  file_size BIGINT,
  hash VARCHAR(128),
  main_category_id BIGINT,
  status VARCHAR(24) NOT NULL DEFAULT 'PUBLISHED',
  review_reason VARCHAR(500),
  reviewed_at DATETIME,
  like_count INT NOT NULL DEFAULT 0,
  favorite_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  share_count INT NOT NULL DEFAULT 0,
  view_count INT NOT NULL DEFAULT 0,
  hot_score DECIMAL(12,4) NOT NULL DEFAULT 0,
  published_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_images_author (author_id),
  KEY idx_images_hash (hash),
  KEY idx_images_category (main_category_id),
  KEY idx_images_ratio (ratio),
  KEY idx_images_author_status_time (author_id, status, created_at),
  KEY idx_images_feed (status, hot_score, published_at),
  KEY idx_images_status_time (status, created_at),
  KEY idx_images_status_published_id (status, published_at, id),
  KEY idx_images_status_hot_published_id (status, hot_score, published_at, id),
  KEY idx_images_status_category_ratio_hot (status, main_category_id, ratio, hot_score, published_at, id),
  CONSTRAINT fk_images_author FOREIGN KEY (author_id) REFERENCES app_users(id),
  CONSTRAINT fk_images_category FOREIGN KEY (main_category_id) REFERENCES categories(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE image_tags (
  image_id BIGINT NOT NULL,
  tag_id BIGINT NOT NULL,
  confidence DECIMAL(6,4) NOT NULL DEFAULT 1,
  source VARCHAR(32) NOT NULL DEFAULT 'script',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (image_id, tag_id),
  KEY idx_image_tags_tag (tag_id, confidence),
  KEY idx_image_tags_image_confidence (image_id, confidence, tag_id),
  KEY idx_image_tags_tag_image_confidence (tag_id, image_id, confidence),
  KEY idx_image_tags_source (source),
  CONSTRAINT fk_image_tags_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  CONSTRAINT fk_image_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE topics (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL UNIQUE,
  slug VARCHAR(80) NOT NULL UNIQUE,
  description VARCHAR(280),
  cover_url VARCHAR(512),
  post_count INT NOT NULL DEFAULT 0,
  follower_count INT NOT NULL DEFAULT 0,
  hot_score DECIMAL(12,4) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_topics_hot (hot_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE image_topics (
  image_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (image_id, topic_id),
  KEY idx_image_topics_topic (topic_id, image_id),
  CONSTRAINT fk_image_topics_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  CONSTRAINT fk_image_topics_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE comments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  image_id BIGINT NOT NULL,
  author_id BIGINT NOT NULL,
  parent_comment_id BIGINT,
  content VARCHAR(1000) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'VISIBLE',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_comments_image (image_id, created_at),
  KEY idx_comments_author (author_id),
  CONSTRAINT fk_comments_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  CONSTRAINT fk_comments_author FOREIGN KEY (author_id) REFERENCES app_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE follows (
  follower_id BIGINT NOT NULL,
  followee_id BIGINT NOT NULL,
  scene VARCHAR(32) NOT NULL DEFAULT 'detail',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (follower_id, followee_id),
  KEY idx_follows_followee (followee_id),
  KEY idx_follows_follower_followee_time (follower_id, followee_id, created_at),
  CONSTRAINT fk_follows_follower FOREIGN KEY (follower_id) REFERENCES app_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_follows_followee FOREIGN KEY (followee_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_interactions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  image_id BIGINT NOT NULL,
  interaction_type VARCHAR(24) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_image_interaction (user_id, image_id, interaction_type),
  KEY idx_user_interactions_image (image_id, interaction_type, active),
  CONSTRAINT fk_user_interactions_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_interactions_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_behaviors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  visitor_id VARCHAR(64),
  image_id BIGINT NOT NULL,
  behavior_type VARCHAR(32) NOT NULL,
  scene VARCHAR(32),
  position_no INT,
  duration_ms INT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_behaviors_user_time (user_id, created_at),
  KEY idx_user_behaviors_visitor_time (visitor_id, created_at),
  KEY idx_user_behaviors_user_image_type_time (user_id, image_id, behavior_type, created_at),
  KEY idx_user_behaviors_visitor_image_type_time (visitor_id, image_id, behavior_type, created_at),
  KEY idx_user_behaviors_image_type (image_id, behavior_type),
  KEY idx_user_behaviors_user_type_time_image (user_id, behavior_type, created_at, image_id),
  KEY idx_user_behaviors_visitor_type_time_image (visitor_id, behavior_type, created_at, image_id),
  KEY idx_user_behaviors_user_time_image_type (user_id, created_at, image_id, behavior_type),
  KEY idx_user_behaviors_visitor_time_image_type (visitor_id, created_at, image_id, behavior_type),
  CONSTRAINT fk_user_behaviors_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE feed_impressions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  visitor_id VARCHAR(64),
  image_id BIGINT NOT NULL,
  scene VARCHAR(32) NOT NULL DEFAULT 'home',
  position_no INT,
  source VARCHAR(32) NOT NULL DEFAULT 'mysql',
  score DECIMAL(12,6),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_feed_impressions_user_time (user_id, created_at),
  KEY idx_feed_impressions_visitor_time (visitor_id, created_at),
  KEY idx_feed_impressions_image_time (image_id, created_at),
  CONSTRAINT fk_feed_impressions_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL,
  CONSTRAINT fk_feed_impressions_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE image_embeddings (
  image_id BIGINT NOT NULL,
  model_name VARCHAR(120) NOT NULL,
  vector_version VARCHAR(40) NOT NULL DEFAULT 'v1',
  vector_dimension INT NOT NULL DEFAULT 512,
  image_hash VARCHAR(128),
  milvus_collection VARCHAR(80) NOT NULL DEFAULT 'vibelo_image_vectors_siglip2_base_p224_d512',
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

CREATE TABLE recommendation_candidates (
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

CREATE TABLE user_interest_snapshots (
  user_id BIGINT PRIMARY KEY,
  model_name VARCHAR(120) NOT NULL,
  vector_version VARCHAR(40) NOT NULL DEFAULT 'v1',
  positive_image_count INT NOT NULL DEFAULT 0,
  interest_json JSON,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_interest_snapshots_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
