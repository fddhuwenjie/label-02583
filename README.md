# 游戏服务器管理器

## How to Run

### Docker 启动（推荐）

```bash
# 启动所有服务
docker compose up --build -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 清理数据重新开始
docker compose down -v
docker compose up --build -d
```

API 访问地址：http://localhost:8081

### 本地启动

```bash
# 1. 先启动 MySQL（可以用 Docker）
docker run -d --name mysql-local \
  -e MYSQL_ROOT_PASSWORD=gameserver123 \
  -e MYSQL_DATABASE=gameserver \
  -p 3306:3306 \
  mysql:8.0

# 2. 安装 Python 依赖
cd backend
pip install -r requirements.txt

# 3. 设置环境变量
export DATABASE_URL="mysql+pymysql://root:gameserver123@localhost:3306/gameserver?charset=utf8mb4"
export DOCKER_SOCKET="unix:///var/run/docker.sock"

# 4. 启动服务
uvicorn app.main:app --reload --port 8000
```

本地 API 访问地址：http://localhost:8000

## Services

| 服务 | 端口 | 说明 |
|------|------|------|
| Backend API | 8081 | FastAPI 游戏服务器管理接口 |
| MySQL | 3583 | 数据库存储 |

## 测试账号

| 类型 | 值 |
|------|-----|
| MySQL 用户 | root |
| MySQL 密码 | gameserver123 |
| MySQL 数据库 | gameserver |

## 题目内容

创建一个服务器，在 Docker 容器里面运行游戏服务器程序，并且可以接收指令创建或者开始删除游戏服务器。将指令设计成 API 并提供文档。并且支持用 API 控制游戏服务器发送指令。语言选择 Python。

---

## 项目介绍

一个用于管理运行在 Docker 容器中的游戏服务器的 REST API 服务。

### 功能特性

- 创建/删除游戏服务器（支持资源限制）
- 启动/停止游戏服务器
- 在运行中的服务器上执行命令（带安全过滤）
- 游戏日志查看 API
- 服务器资源监控（CPU/内存/网络）
- RCON 远程控制支持（Minecraft）
- 使用 MySQL 进行持久化存储
- API Key 认证支持
- 容器状态同步机制
- 多端口映射支持
- 日志文件轮转

### 支持的游戏服务器

| 游戏 | 镜像 | 默认端口 | 配置示例 |
|------|------|----------|----------|
| Minecraft Java | `itzg/minecraft-server:latest` | 25565, 25575(RCON) | [查看](game-servers/minecraft/) |
| Terraria | `ryshe/terraria:latest` | 7777 | [查看](game-servers/terraria/) |

---

## 系统要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Docker | 20.10+ | 需要支持 Docker API 1.41+ |
| Docker Compose | 2.0+ | 使用 Compose V2 语法 |
| 操作系统 | Linux/macOS/Windows | Windows 需要 WSL2 |

### Docker 环境兼容性

**Linux:**
```bash
# 确保当前用户在 docker 组
sudo usermod -aG docker $USER
```

**macOS (Docker Desktop):**
- 需要 Docker Desktop 4.0+
- 在 Settings > Resources 中分配足够内存（建议 4GB+）

**Windows (WSL2):**
- 需要 Windows 10 2004+ 或 Windows 11
- 启用 WSL2 并安装 Docker Desktop

---

## 🎮 Minecraft 服务器完整示例

### 1. 创建 Minecraft 服务器

```bash
curl -X POST http://localhost:8081/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-minecraft",
    "image": "itzg/minecraft-server:latest",
    "port": 25565,
    "game_type": "minecraft",
    "extra_ports": [25575],
    "memory_limit": "2g",
    "cpu_limit": 2.0,
    "rcon_password": "your-secure-password"
  }'
```

### 2. 查看服务器日志

```bash
curl "http://localhost:8081/servers/1/logs?tail=50"
```

### 3. 监控服务器资源

```bash
curl http://localhost:8081/servers/1/stats
```

### 4. 使用 RCON 管理服务器

```bash
# 列出在线玩家
curl -X POST http://localhost:8081/servers/1/rcon \
  -H "Content-Type: application/json" \
  -d '{"command": "list"}'

# 广播消息
curl -X POST http://localhost:8081/servers/1/rcon \
  -H "Content-Type: application/json" \
  -d '{"command": "say Hello everyone!"}'
```

### 5. 停止和删除服务器

```bash
# 停止服务器
curl -X POST http://localhost:8081/servers/1/stop

# 删除服务器（同时删除游戏数据）
curl -X DELETE http://localhost:8081/servers/1

# 删除服务器（保留游戏数据）
curl -X DELETE "http://localhost:8081/servers/1?preserve_data=true"
```

---

## API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |
| GET | `/health` | 详细健康检查 |
| POST | `/servers/sync` | 手动同步服务器状态 |
| GET | `/servers` | 获取所有服务器列表 |
| POST | `/servers` | 创建新服务器 |
| GET | `/servers/{id}` | 获取服务器详情 |
| POST | `/servers/{id}/start` | 启动服务器 |
| POST | `/servers/{id}/stop` | 停止服务器 |
| DELETE | `/servers/{id}` | 删除服务器 |
| POST | `/servers/{id}/command` | 执行命令 |
| GET | `/servers/{id}/logs` | 获取服务器日志 |
| GET | `/servers/{id}/stats` | 获取资源使用统计 |
| POST | `/servers/{id}/rcon` | 发送 RCON 命令 |

### API 文档

- 交互式文档：http://localhost:8081/docs
- 详细 API 参考：[API.md](backend/API.md)

---

## 测试指南

```bash
# Docker 环境运行测试
docker exec gameserver_backend pytest tests/ -v

# 本地运行测试
cd backend
pytest tests/ -v
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | MySQL 连接字符串 | 数据库连接 |
| `DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Docker socket 路径 |
| `API_KEY` | (空) | API Key（空则禁用认证） |
| `MAX_SERVERS` | `10` | 最大服务器数量 |
| `DEFAULT_MEMORY_LIMIT` | `512m` | 默认内存限制 |
| `DEFAULT_CPU_LIMIT` | `1.0` | 默认 CPU 限制 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 服务器状态说明

| 状态 | 说明 |
|------|------|
| `creating` | 服务器正在创建中 |
| `running` | 服务器正在运行 |
| `stopped` | 服务器已停止 |
| `error` | 服务器遇到错误 |
