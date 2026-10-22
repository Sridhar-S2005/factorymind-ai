CREATE DATABASE IF NOT EXISTS factorymind_ai
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE factorymind_ai;

CREATE TABLE IF NOT EXISTS reviews (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  created_at VARCHAR(40) NOT NULL,
  category VARCHAR(80) NOT NULL,
  severity VARCHAR(30) NOT NULL,
  sensor_name VARCHAR(160),
  parameter VARCHAR(160),
  equipment_id VARCHAR(120),
  sensor_value VARCHAR(80),
  unit VARCHAR(40),
  source_alarm VARCHAR(120),
  machine_state VARCHAR(120),
  notes TEXT,
  status VARCHAR(30) NOT NULL DEFAULT 'Open',
  INDEX idx_reviews_created_at (created_at),
  INDEX idx_reviews_severity (severity),
  INDEX idx_reviews_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
