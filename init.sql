SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;

CREATE DATABASE IF NOT EXISTS gameserver
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE gameserver;

-- Game servers table with extended fields
CREATE TABLE IF NOT EXISTS game_servers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    container_id VARCHAR(100),
    image VARCHAR(200) NOT NULL,
    port INT NOT NULL,
    status VARCHAR(20) DEFAULT 'creating',
    game_type VARCHAR(50),
    memory_limit VARCHAR(20) DEFAULT '512m',
    cpu_limit FLOAT DEFAULT 1.0,
    rcon_password VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_game_type (game_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
