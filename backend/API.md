# Game Server Manager API Documentation

## Overview

REST API for managing game servers running in Docker containers.

Base URL: `http://localhost:8081`

Interactive API docs: `http://localhost:8081/docs`

## Authentication

API key authentication is supported. Set the `API_KEY` environment variable to enable authentication.

When enabled, include the API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8081/servers
```

If `API_KEY` is not set, authentication is disabled (development mode).

## Error Codes

| HTTP Code | Description |
|-----------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request - Invalid parameters, image pull failed, or server limit reached |
| 401 | Unauthorized - Invalid or missing API key |
| 404 | Not Found - Server does not exist |
| 409 | Conflict - Port already in use |
| 422 | Validation Error - Invalid input (dangerous command, invalid name, etc.) |
| 500 | Internal Server Error |

## Endpoints

### Health Check

#### GET /

Basic health check (no authentication required).

**Response:**
```json
{
  "message": "Game Server Manager API is running"
}
```

#### GET /health

Detailed health check including database and Docker status.

**Response:**
```json
{
  "status": "healthy",
  "database": "healthy",
  "docker": "healthy"
}
```

---

### State Synchronization

#### POST /servers/sync

Manually trigger synchronization between database and actual Docker container states.

**Response (200):**
```json
{
  "message": "Server states synchronized"
}
```

---

### Servers

#### POST /servers

Create a new game server.

**Request Body:**
```json
{
  "name": "string (required, 1-100 chars, alphanumeric with - and _ only)",
  "image": "string (optional, default: alpine:latest)",
  "port": "integer (required, 1024-65535)",
  "game_type": "string (optional, e.g., minecraft, csgo)",
  "extra_ports": "array of integers (optional, additional ports to expose)",
  "memory_limit": "string (optional, default: 512m, e.g., 1g)",
  "cpu_limit": "float (optional, default: 1.0, range: 0.1-4.0)",
  "rcon_password": "string (optional, 4-100 chars, RCON password for game server)"
}
```

**Response (201):**
```json
{
  "id": 1,
  "name": "my-server",
  "container_id": "abc123...",
  "image": "alpine:latest",
  "port": 25565,
  "status": "running",
  "game_type": "minecraft",
  "memory_limit": "1g",
  "cpu_limit": 2.0,
  "rcon_password": "secret123",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00"
}
```

**Errors:**
- `400`: Server name already exists / Image pull failed / Server limit reached
- `409`: Port already in use
- `422`: Invalid server name or parameters
- `500`: Container creation failed

---

#### GET /servers

List all game servers.

**Query Parameters:**
- `sync` (boolean, optional): Set to `true` to synchronize states before listing

**Response (200):**
```json
[
  {
    "id": 1,
    "name": "my-server",
    "container_id": "abc123...",
    "image": "alpine:latest",
    "port": 25565,
    "status": "running",
    "game_type": "minecraft",
    "memory_limit": "1g",
    "cpu_limit": 2.0,
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  }
]
```

---

#### GET /servers/{server_id}

Get details of a specific server.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Query Parameters:**
- `sync` (boolean, optional): Set to `true` to synchronize state before returning

**Response (200):**
```json
{
  "id": 1,
  "name": "my-server",
  "container_id": "abc123...",
  "image": "alpine:latest",
  "port": 25565,
  "status": "running",
  "game_type": "minecraft",
  "memory_limit": "1g",
  "cpu_limit": 2.0,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00"
}
```

**Errors:**
- `404`: Server not found

---

#### POST /servers/{server_id}/start

Start a stopped server.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Response (200):**
```json
{
  "message": "Server my-server started"
}
```

**Errors:**
- `400`: No container associated
- `404`: Server not found
- `500`: Failed to start server

---

#### POST /servers/{server_id}/stop

Stop a running server.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Response (200):**
```json
{
  "message": "Server my-server stopped"
}
```

**Errors:**
- `400`: No container associated
- `404`: Server not found
- `500`: Failed to stop server

---

#### DELETE /servers/{server_id}

Delete a server, its container, and optionally associated volumes.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Query Parameters:**
- `preserve_data` (boolean, optional, default: false): 
  - `false`: Deletes container AND all game data (volumes) - permanent data loss
  - `true`: Deletes container but keeps game data volumes for future use

**Response (200):**
```json
{
  "message": "Server my-server and all game data deleted."
}
```

Or with `preserve_data=true`:
```json
{
  "message": "Server my-server deleted. Game data volumes preserved."
}
```

**Errors:**
- `404`: Server not found

**Examples:**
```bash
# Delete server and all data (default)
curl -X DELETE http://localhost:8081/servers/1

# Delete server but keep game data
curl -X DELETE "http://localhost:8081/servers/1?preserve_data=true"
```

---

#### POST /servers/{server_id}/command

Execute a command inside the server container.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Request Body:**
```json
{
  "command": "string (required, 1-1000 chars)"
}
```

**Response (200):**
```json
{
  "exit_code": 0,
  "output": "command output here"
}
```

**Errors:**
- `400`: No container associated / Server is not running / Container no longer exists
- `404`: Server not found
- `422`: Command contains dangerous patterns

**Blocked Commands:**
The following patterns are blocked for security:
- `rm -rf /` and similar destructive commands
- Fork bombs
- Commands writing to system directories
- Pipe to shell (`curl ... | bash`)
- Command chaining (`&&`, `||`, `;`, `|`)
- Shell metacharacters (`` ` ``, `$(`, etc.)

---

### Game Server Specific Endpoints

#### GET /servers/{server_id}/logs

Get game server container logs.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Query Parameters:**
- `tail` (integer, optional, default: 100): Number of log lines to return

**Response (200):**
```json
{
  "logs": "[10:30:15] [Server thread/INFO]: Starting minecraft server...\n[10:30:20] [Server thread/INFO]: Done!",
  "lines": 50
}
```

**Errors:**
- `400`: No container associated / Container no longer exists
- `404`: Server not found

---

#### GET /servers/{server_id}/stats

Get game server resource usage statistics.

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Response (200):**
```json
{
  "cpu_percent": 15.5,
  "memory_usage": 1073741824,
  "memory_limit": 2147483648,
  "memory_percent": 50.0,
  "network_rx": 102400,
  "network_tx": 51200
}
```

**Errors:**
- `400`: No container associated / Server is not running
- `404`: Server not found
- `500`: Failed to get server stats

---

#### POST /servers/{server_id}/rcon

Send RCON command to game server (Minecraft only).

**Path Parameters:**
- `server_id` (integer, required): Server ID

**Request Body:**
```json
{
  "command": "string (required, 1-500 chars)",
  "password": "string (optional, uses server's stored password if not provided)"
}
```

**Response (200):**
```json
{
  "exit_code": 0,
  "output": "There are 5 of a max of 20 players online"
}
```

**Password Priority:**
1. Password provided in request body
2. Server's stored `rcon_password` (set during creation)
3. Default: "minecraft"
```

**Common RCON Commands (Minecraft):**
- `list` - List online players
- `say <message>` - Broadcast message to all players
- `kick <player> [reason]` - Kick a player
- `ban <player> [reason]` - Ban a player
- `op <player>` - Give operator status
- `deop <player>` - Remove operator status
- `whitelist add <player>` - Add player to whitelist
- `whitelist remove <player>` - Remove player from whitelist
- `time set <day|night|noon|midnight>` - Set game time
- `weather <clear|rain|thunder>` - Set weather
- `difficulty <peaceful|easy|normal|hard>` - Set difficulty
- `gamemode <survival|creative|adventure|spectator> <player>` - Set player game mode
- `tp <player> <x> <y> <z>` - Teleport player
- `give <player> <item> [amount]` - Give item to player
- `stop` - Stop the server gracefully

**Errors:**
- `400`: No container associated / Server is not running / RCON only supported for Minecraft
- `404`: Server not found

---

## Server Status Values

| Status | Description |
|--------|-------------|
| `creating` | Server is being created |
| `running` | Server is running |
| `stopped` | Server is stopped |
| `error` | Server encountered an error (container may be missing) |

## Usage Examples

### Create a Minecraft Server

```bash
curl -X POST http://localhost:8081/servers \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "name": "minecraft-survival",
    "image": "itzg/minecraft-server:latest",
    "port": 25565,
    "game_type": "minecraft",
    "memory_limit": "2g",
    "cpu_limit": 2.0,
    "extra_ports": [25575]
  }'
```

### Execute Server Command

```bash
curl -X POST http://localhost:8081/servers/1/command \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"command": "ls -la"}'
```

### List Servers with State Sync

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:8081/servers?sync=true"
```

### Stop Server

```bash
curl -X POST http://localhost:8081/servers/1/stop \
  -H "X-API-Key: your-api-key"
```

### Delete Server

```bash
curl -X DELETE http://localhost:8081/servers/1 \
  -H "X-API-Key: your-api-key"
```

### Health Check

```bash
curl http://localhost:8081/health
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | MySQL connection string | Database connection |
| `DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Docker socket path |
| `DOCKER_TIMEOUT` | `30` | Docker API timeout (seconds) |
| `DOCKER_PULL_TIMEOUT` | `300` | Image pull timeout (seconds) |
| `DOCKER_STOP_TIMEOUT` | `10` | Container stop timeout (seconds) |
| `API_KEY` | (empty) | API key for authentication (empty = disabled) |
| `MAX_SERVERS` | `10` | Maximum number of servers allowed |
| `DEFAULT_MEMORY_LIMIT` | `512m` | Default memory limit for containers |
| `DEFAULT_CPU_LIMIT` | `1.0` | Default CPU limit for containers |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FILE` | `/var/log/gameserver/app.log` | Log file path |
| `LOG_MAX_BYTES` | `10485760` | Max log file size (10MB) |
| `LOG_BACKUP_COUNT` | `5` | Number of log backup files |
| `STATE_SYNC_INTERVAL` | `60` | State sync interval (seconds) |

## Resource Limits

- Maximum servers: Configurable via `MAX_SERVERS` (default: 10)
- Memory limit per container: Configurable per server (default: 512m)
- CPU limit per container: 0.1 to 4.0 cores (default: 1.0)
