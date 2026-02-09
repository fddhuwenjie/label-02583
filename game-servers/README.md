# 游戏服务器配置示例

本目录包含常见游戏服务器的 Docker 配置示例。

## 目录结构

```
game-servers/
├── minecraft/           # Minecraft Java Edition
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── server.properties.example
└── terraria/           # Terraria
    ├── Dockerfile
    └── docker-compose.yml
```

## 使用方式

### 方式一：通过管理 API 创建

使用游戏服务器管理 API 创建和管理服务器：

```bash
# Minecraft
curl -X POST http://localhost:8081/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-minecraft",
    "image": "itzg/minecraft-server:latest",
    "port": 25565,
    "game_type": "minecraft",
    "extra_ports": [25575],
    "memory_limit": "2g"
  }'

# Terraria
curl -X POST http://localhost:8081/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-terraria",
    "image": "ryshe/terraria:latest",
    "port": 7777,
    "game_type": "terraria",
    "memory_limit": "1g"
  }'
```

### 方式二：独立部署

直接使用 docker-compose 启动游戏服务器：

```bash
cd minecraft  # 或 terraria
docker compose up -d
```

## Minecraft 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `EULA` | 接受 EULA | TRUE |
| `TYPE` | 服务器类型 | VANILLA |
| `VERSION` | 游戏版本 | LATEST |
| `MEMORY` | 内存分配 | 2G |
| `MAX_PLAYERS` | 最大玩家数 | 20 |
| `DIFFICULTY` | 难度 | normal |
| `MODE` | 游戏模式 | survival |
| `MOTD` | 服务器描述 | - |
| `ENABLE_RCON` | 启用 RCON | true |
| `RCON_PASSWORD` | RCON 密码 | minecraft |

### RCON 使用

```bash
# 进入容器使用 rcon-cli
docker exec -it minecraft-server rcon-cli

# 或通过 API
curl -X POST http://localhost:8081/servers/1/rcon \
  -H "Content-Type: application/json" \
  -d '{"command": "list"}'
```

## Terraria 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WORLD_FILENAME` | 世界文件名 | world.wld |
| `WORLD_SIZE` | 世界大小 (1-3) | 2 |
| `MAX_PLAYERS` | 最大玩家数 | 8 |
| `DIFFICULTY` | 难度 (0-3) | 0 |

## 添加新游戏服务器

1. 在 `game-servers/` 下创建新目录
2. 添加 `Dockerfile` 和 `docker-compose.yml`
3. 更新主 README.md 的支持列表
