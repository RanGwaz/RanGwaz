DROP PROCEDURE IF EXISTS drop_index_if_exists;
DROP PROCEDURE IF EXISTS add_index_if_missing;

DELIMITER $$

CREATE PROCEDURE drop_index_if_exists(
  IN p_table_name VARCHAR(64),
  IN p_index_name VARCHAR(64)
)
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND index_name = p_index_name
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE ', p_table_name, ' DROP INDEX ', p_index_name);
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

CALL drop_index_if_exists('categories', 'uk_categories_parent_name')$$

DROP TEMPORARY TABLE IF EXISTS category_keep$$
CREATE TEMPORARY TABLE category_keep AS
SELECT name, MIN(id) AS keep_id
FROM categories
GROUP BY name$$

DROP TEMPORARY TABLE IF EXISTS category_duplicate_map$$
CREATE TEMPORARY TABLE category_duplicate_map AS
SELECT c.id AS duplicate_id, k.keep_id
FROM categories c
JOIN category_keep k ON k.name = c.name
WHERE c.id <> k.keep_id$$

UPDATE images i
JOIN category_duplicate_map m ON m.duplicate_id = i.main_category_id
SET i.main_category_id = m.keep_id$$

UPDATE categories c
JOIN category_duplicate_map m ON m.duplicate_id = c.parent_id
SET c.parent_id = m.keep_id$$

UPDATE categories
SET parent_id = NULL
WHERE parent_id = id$$

DELETE c
FROM categories c
JOIN category_duplicate_map m ON m.duplicate_id = c.id$$

UPDATE categories
SET parent_id = NULL,
    sort_no = 0$$

CALL add_index_if_missing(
  'categories',
  'uk_categories_name',
  'UNIQUE KEY uk_categories_name (name)'
)$$

DROP PROCEDURE drop_index_if_exists$$
DROP PROCEDURE add_index_if_missing$$

DELIMITER ;
