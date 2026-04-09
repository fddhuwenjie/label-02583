from sqlalchemy import Column, Integer, String, DateTime, Enum, Float, Boolean
from sqlalchemy.sql import func
from .database import Base
import enum

class ServerStatus(str, enum.Enum):
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    DELETING = "deleting"
    ERROR = "error"

class GameServer(Base):
    __tablename__ = "game_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    container_id = Column(String(100), nullable=True)
    image = Column(String(200), nullable=False)
    port = Column(Integer, nullable=False)
    status = Column(String(20), default=ServerStatus.CREATING)
    game_type = Column(String(50), nullable=True)  # e.g., minecraft, csgo
    memory_limit = Column(String(20), default="512m")
    cpu_limit = Column(Float, default=1.0)
    rcon_password = Column(String(100), nullable=True)  # RCON password for game servers
    operating = Column(Boolean, default=False)  # Operation in progress flag
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
