-- Clean development schema for the RanGwaz image website.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS feed_impressions;
DROP TABLE IF EXISTS user_interest_snapshots;
DROP TABLE IF EXISTS post_recommendation_features;
DROP TABLE IF EXISTS recommendation_candidates;
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
DROP TABLE IF EXISTS app_users;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE app_users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(128) NOT NULL,
  nickname VARCHAR(64) NOT NULL,
  avatar_url VARCHAR(512),
  background_url VARCHAR(512),
  bio VARCHAR(280),
  status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_app_users_nickname (nickname)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE categories (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  parent_id BIGINT,
  slug VARCHAR(120) NOT NULL UNIQUE,
  sort_no INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_categories_parent_name (parent_id, name),
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
  title VARCHAR(160) NOT NULL,
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
  KEY idx_images_feed (status, hot_score, published_at),
  KEY idx_images_status_time (status, created_at),
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
  image_id BIGINT NOT NULL,
  behavior_type VARCHAR(32) NOT NULL,
  scene VARCHAR(32),
  position_no INT,
  duration_ms INT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_behaviors_user_time (user_id, created_at),
  KEY idx_user_behaviors_image_type (image_id, behavior_type),
  CONSTRAINT fk_user_behaviors_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
