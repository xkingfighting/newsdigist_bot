-- NewsDigest 数据库初始化脚本
-- MySQL 8.0+

CREATE DATABASE IF NOT EXISTS `newsdigest`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `newsdigest`;

-- 创建应用用户（如需要）
-- CREATE USER IF NOT EXISTS 'dev'@'%' IDENTIFIED BY '6s40UNEEyziL5CHWj71m';
-- GRANT ALL PRIVILEGES ON newsdigest.* TO 'dev'@'%';
-- FLUSH PRIVILEGES;

-- ============================
-- 用户表
-- ============================
CREATE TABLE IF NOT EXISTS `users` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `platform`         VARCHAR(32)     NOT NULL DEFAULT 'talkonly',
  `platform_user_id` BIGINT          NOT NULL,
  `username`         VARCHAR(128)    NOT NULL DEFAULT '',
  `display_name`     VARCHAR(128)    NOT NULL DEFAULT '',
  `timezone`         VARCHAR(64)     NOT NULL DEFAULT 'Asia/Singapore',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_platform_user` (`platform`, `platform_user_id`),
  INDEX `idx_platform_user_id` (`platform`, `platform_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================
-- 订阅表
-- ============================
CREATE TABLE IF NOT EXISTS `subscriptions` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL,
  `keyword`     VARCHAR(128)    NOT NULL,
  `push_time`   VARCHAR(8)      NOT NULL COMMENT 'HH:MM',
  `timezone`    VARCHAR(64)     NOT NULL DEFAULT 'Asia/Singapore',
  `chat_id`     BIGINT          NOT NULL DEFAULT 0 COMMENT '推送目标：私聊=user_id, 群聊=group_id',
  `chat_type`   VARCHAR(16)     NOT NULL DEFAULT 'private' COMMENT 'private|group',
  `status`      ENUM('active','paused','deleted') NOT NULL DEFAULT 'active',
  `platform`    VARCHAR(32)     NOT NULL DEFAULT 'talkonly',
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_user_status` (`user_id`, `status`),
  INDEX `idx_status_push_time` (`status`, `push_time`),
  INDEX `idx_user_keyword_chat` (`user_id`, `keyword`, `platform`, `chat_id`, `chat_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================
-- 推送日志表
-- ============================
CREATE TABLE IF NOT EXISTS `push_logs` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`          BIGINT UNSIGNED NOT NULL,
  `subscription_id`  BIGINT UNSIGNED NOT NULL,
  `keyword`          VARCHAR(128)    NOT NULL,
  `raw_sources_json` TEXT            DEFAULT NULL,
  `summary_text`     TEXT            DEFAULT NULL,
  `status`           ENUM('success','failed') NOT NULL DEFAULT 'success',
  `error_message`    TEXT            DEFAULT NULL,
  `pushed_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_push_user_time` (`user_id`, `pushed_at`),
  INDEX `idx_subscription_id` (`subscription_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================
-- Bot 更新偏移量表
-- ============================
CREATE TABLE IF NOT EXISTS `bot_update_offsets` (
  `id`             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `platform`       VARCHAR(32)  NOT NULL,
  `last_update_id` BIGINT       NOT NULL DEFAULT 0,
  `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_platform` (`platform`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 初始化 TalkOnly 平台 offset 记录
INSERT IGNORE INTO `bot_update_offsets` (`platform`, `last_update_id`) VALUES ('talkonly', 0);
