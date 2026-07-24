ALTER TABLE user_behaviors
  ADD COLUMN decision_id VARCHAR(64) NULL AFTER duration_ms,
  ADD COLUMN event_id VARCHAR(64) NULL AFTER decision_id,
  ADD COLUMN source VARCHAR(48) NULL AFTER event_id,
  ADD COLUMN score DECIMAL(12,6) NULL AFTER source,
  ADD UNIQUE KEY uk_user_behaviors_event_id (event_id),
  ADD KEY idx_user_behaviors_decision (decision_id);

ALTER TABLE feed_impressions
  MODIFY COLUMN source VARCHAR(48) NOT NULL DEFAULT 'unknown',
  ADD COLUMN decision_id VARCHAR(64) NULL AFTER score,
  ADD COLUMN event_id VARCHAR(64) NULL AFTER decision_id,
  ADD COLUMN occurred_at DATETIME NULL AFTER event_id,
  ADD UNIQUE KEY uk_feed_impressions_event_id (event_id),
  ADD KEY idx_feed_impressions_decision (decision_id),
  ADD KEY idx_feed_impressions_occurred (occurred_at);
