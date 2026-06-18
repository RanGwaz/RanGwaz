ALTER TABLE app_users
  ADD COLUMN phone VARCHAR(32) NULL AFTER username,
  ADD UNIQUE KEY uk_app_users_phone (phone);
