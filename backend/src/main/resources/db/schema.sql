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
DROP TABLE IF EXISTS post_topics;
DROP TABLE IF EXISTS topics;
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

CREATE TABLE posts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  author_id BIGINT NOT NULL,
  title VARCHAR(160) NOT NULL,
  content TEXT,
  cover_url VARCHAR(512),
  thumb_url VARCHAR(512),
  post_type VARCHAR(32) NOT NULL DEFAULT 'image',
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
  KEY idx_posts_author (author_id),
  KEY idx_posts_feed (status, hot_score, published_at),
  CONSTRAINT fk_posts_author FOREIGN KEY (author_id) REFERENCES app_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE post_assets (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  post_id BIGINT NOT NULL,
  object_key VARCHAR(180) NOT NULL,
  file_url VARCHAR(512) NOT NULL,
  file_type VARCHAR(32) NOT NULL,
  thumb_url VARCHAR(512),
  width INT,
  height INT,
  sort_order INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_post_assets_post (post_id, sort_order),
  CONSTRAINT fk_post_assets_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
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

CREATE TABLE post_topics (
  post_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (post_id, topic_id),
  KEY idx_post_topics_topic (topic_id, post_id),
  CONSTRAINT fk_post_topics_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
  CONSTRAINT fk_post_topics_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE comments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  post_id BIGINT NOT NULL,
  author_id BIGINT NOT NULL,
  parent_comment_id BIGINT,
  content VARCHAR(1000) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'VISIBLE',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_comments_post (post_id, created_at),
  KEY idx_comments_author (author_id),
  CONSTRAINT fk_comments_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
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
  post_id BIGINT NOT NULL,
  interaction_type VARCHAR(24) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_post_interaction (user_id, post_id, interaction_type),
  KEY idx_user_interactions_post (post_id, interaction_type, active),
  CONSTRAINT fk_user_interactions_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_interactions_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_behaviors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  post_id BIGINT NOT NULL,
  behavior_type VARCHAR(32) NOT NULL,
  scene VARCHAR(32),
  position_no INT,
  duration_ms INT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_behaviors_user_time (user_id, created_at),
  KEY idx_user_behaviors_post_type (post_id, behavior_type),
  CONSTRAINT fk_user_behaviors_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE recommendation_candidates (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  post_id BIGINT NOT NULL,
  source VARCHAR(40) NOT NULL,
  score DECIMAL(12,6) NOT NULL DEFAULT 0,
  reason VARCHAR(120),
  expires_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_reco_candidates_user_source (user_id, source, score),
  KEY idx_reco_candidates_post (post_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE post_recommendation_features (
  post_id BIGINT PRIMARY KEY,
  topic_vector JSON,
  visual_embedding_ref VARCHAR(180),
  quality_score DECIMAL(12,6) NOT NULL DEFAULT 0,
  freshness_score DECIMAL(12,6) NOT NULL DEFAULT 0,
  engagement_score DECIMAL(12,6) NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_post_reco_features_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_interest_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  interest_key VARCHAR(80) NOT NULL,
  interest_type VARCHAR(32) NOT NULL,
  weight DECIMAL(12,6) NOT NULL DEFAULT 0,
  last_behavior_at DATETIME,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_interest (user_id, interest_type, interest_key),
  KEY idx_user_interest_weight (user_id, weight),
  CONSTRAINT fk_user_interest_user FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE feed_impressions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  request_id VARCHAR(64),
  user_id BIGINT,
  post_id BIGINT NOT NULL,
  source VARCHAR(40) NOT NULL,
  rank_no INT NOT NULL,
  score DECIMAL(12,6) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_feed_impressions_user_time (user_id, created_at),
  KEY idx_feed_impressions_post_time (post_id, created_at),
  CONSTRAINT fk_feed_impressions_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
