from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime
import re

# Dangerous command patterns that should be blocked
DANGEROUS_PATTERNS = [
    r'\brm\s+(-[rf]+\s+)?/',  # rm -rf / or rm /
    r'\brm\s+(-[rf]+\s+)?\*',  # rm * or rm -rf *
    r'>\s*/dev/sd[a-z]',  # Write to disk devices
    r'\bmkfs\b',  # Format filesystem
    r'\bdd\s+.*of=/dev/',  # dd to devices
    r':\(\)\s*{\s*:\|:&\s*}\s*;:',  # Fork bomb
    r'\bshutdown\b',  # Shutdown
    r'\breboot\b',  # Reboot
    r'\bhalt\b',  # Halt
    r'\binit\s+0',  # Init 0
    r'\bkillall\b',  # Killall
    r'\bchmod\s+(-R\s+)?777\s+/',  # chmod 777 /
    r'\bchown\s+.*\s+/',  # chown /
    r'>\s*/etc/',  # Write to /etc
    r'>\s*/boot/',  # Write to /boot
    r'\bcurl\s+.*\|\s*(ba)?sh',  # Curl pipe to shell
    r'\bwget\s+.*\|\s*(ba)?sh',  # Wget pipe to shell
]

# Allowed command whitelist (optional, for strict mode)
ALLOWED_COMMANDS = [
    'ls', 'cat', 'echo', 'pwd', 'whoami', 'date', 'uptime',
    'ps', 'top', 'df', 'du', 'free', 'uname', 'hostname',
    'head', 'tail', 'grep', 'find', 'wc', 'sort', 'uniq',
]


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Server name", pattern=r'^[a-zA-Z0-9_-]+$')
    image: str = Field(default="alpine:latest", description="Docker image")
    port: int = Field(..., ge=1024, le=65535, description="Host port")
    game_type: Optional[str] = Field(default=None, description="Game type (e.g., minecraft, csgo)")
    extra_ports: Optional[List[int]] = Field(default=None, description="Additional ports to expose")
    memory_limit: Optional[str] = Field(default="512m", description="Memory limit (e.g., 512m, 1g)")
    cpu_limit: Optional[float] = Field(default=1.0, ge=0.1, le=4.0, description="CPU limit (cores)")
    rcon_password: Optional[str] = Field(default=None, min_length=4, max_length=100, description="RCON password for game server")

    @field_validator('image')
    @classmethod
    def validate_image(cls, v: str) -> str:
        # Basic image name validation
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._/-]*:[a-zA-Z0-9._-]+$', v):
            if ':' not in v:
                v = f"{v}:latest"
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._/-]*:[a-zA-Z0-9._-]+$', v):
                raise ValueError('Invalid image name format')
        return v


class ServerCommand(BaseModel):
    command: str = Field(..., min_length=1, max_length=1000, description="Command to execute")

    @field_validator('command')
    @classmethod
    def validate_command(cls, v: str) -> str:
        # Check for dangerous patterns
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError('Command contains dangerous pattern and is not allowed')
        
        # Check for shell metacharacters that could be used for injection
        dangerous_chars = ['`', '$(', '&&', '||', ';', '|', '>', '<', '\n', '\r']
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f'Command contains forbidden character: {char}')
        
        return v.strip()


class ServerResponse(BaseModel):
    id: int
    name: str
    container_id: Optional[str]
    image: str
    port: int
    status: str
    game_type: Optional[str] = None
    memory_limit: Optional[str] = None
    cpu_limit: Optional[float] = None
    rcon_password: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommandResult(BaseModel):
    exit_code: int
    output: str


class MessageResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall health status: healthy or unhealthy")
    database: str = Field(..., description="Database connection status")
    docker: str = Field(..., description="Docker daemon connection status")


class ServerLogsResponse(BaseModel):
    logs: str = Field(..., description="Container logs")
    lines: int = Field(..., description="Number of lines returned")


class ServerStatsResponse(BaseModel):
    cpu_percent: float = Field(..., description="CPU usage percentage")
    memory_usage: int = Field(..., description="Memory usage in bytes")
    memory_limit: int = Field(..., description="Memory limit in bytes")
    memory_percent: float = Field(..., description="Memory usage percentage")
    network_rx: int = Field(..., description="Network bytes received")
    network_tx: int = Field(..., description="Network bytes transmitted")


class RconCommand(BaseModel):
    command: str = Field(..., min_length=1, max_length=500, description="RCON command to execute")
    password: Optional[str] = Field(default=None, description="RCON password (uses server's stored password if not provided)")


class GameServerConfig(BaseModel):
    """Game-specific configuration for popular game servers"""
    # Minecraft specific
    max_players: Optional[int] = Field(default=None, ge=1, le=100, description="Maximum players")
    difficulty: Optional[str] = Field(default=None, description="Game difficulty")
    gamemode: Optional[str] = Field(default=None, description="Game mode")
    motd: Optional[str] = Field(default=None, max_length=200, description="Server message of the day")
    seed: Optional[str] = Field(default=None, description="World seed")
    whitelist: Optional[bool] = Field(default=None, description="Enable whitelist")
    pvp: Optional[bool] = Field(default=None, description="Enable PvP")
    
    # Generic settings
    extra_env: Optional[Dict[str, str]] = Field(default=None, description="Additional environment variables")
