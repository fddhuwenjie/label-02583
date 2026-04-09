import logging
import logging.handlers
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Security, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from .database import engine, get_db, Base
from .models import GameServer, ServerStatus
from .schemas import (
    ServerCreate, ServerCommand, ServerResponse, CommandResult, 
    MessageResponse, HealthResponse, ServerLogsResponse, ServerStatsResponse,
    RconCommand, GameServerConfig
)
from .docker_manager import docker_manager, ImagePullError, PortConflictError, ContainerCreateError, ContainerNotFoundError, CommandExecutionError
from .config import (
    API_KEY, API_KEY_HEADER, MAX_SERVERS,
    LOG_LEVEL, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT,
    STATE_SYNC_INTERVAL
)


def setup_logging():
    """Configure logging with both console and file handlers"""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler with rotation
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        logging.warning(f"Could not setup file logging: {e}")


setup_logging()
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

# Container operation lock management
_container_locks: dict[str, asyncio.Lock] = {}
_server_locks: dict[int, asyncio.Lock] = {}
_lock_management_lock = asyncio.Lock()  # Protects access to _container_locks and _server_locks


async def get_container_lock(container_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific container"""
    async with _lock_management_lock:
        if container_id not in _container_locks:
            _container_locks[container_id] = asyncio.Lock()
        return _container_locks[container_id]


async def get_server_lock(server_id: int) -> asyncio.Lock:
    """Get or create a lock for a specific server"""
    async with _lock_management_lock:
        if server_id not in _server_locks:
            _server_locks[server_id] = asyncio.Lock()
        return _server_locks[server_id]

# API Key security
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    """Verify API key if configured"""
    if not API_KEY:  # No API key configured, skip auth
        return None
    if api_key != API_KEY:
        logger.warning("Invalid or missing API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def sync_server_states(db: Session):
    """Synchronize database server states with actual Docker container states"""
    logger.info("Starting server state synchronization")
    servers = db.query(GameServer).filter(GameServer.container_id.isnot(None)).all()
    
    for server in servers:
        actual_status = docker_manager.sync_container_status(server.container_id)
        
        if actual_status is None:
            # Container no longer exists
            logger.warning(f"Container {server.container_id} for server {server.name} no longer exists")
            server.status = ServerStatus.ERROR
            server.container_id = None
        else:
            # Map Docker status to our status
            status_map = {
                "running": ServerStatus.RUNNING,
                "exited": ServerStatus.STOPPED,
                "paused": ServerStatus.STOPPED,
                "restarting": ServerStatus.RUNNING,
                "created": ServerStatus.STOPPED,
            }
            new_status = status_map.get(actual_status, ServerStatus.ERROR)
            if server.status != new_status:
                logger.info(f"Updating server {server.name} status: {server.status} -> {new_status}")
                server.status = new_status
    
    db.commit()
    logger.info("Server state synchronization completed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler with background state sync"""
    logger.info("Application starting up")
    
    # Start background sync task
    sync_task = asyncio.create_task(periodic_state_sync())
    
    yield
    
    # Cancel background task on shutdown
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shutting down")


async def periodic_state_sync():
    """Periodically sync server states with Docker"""
    from .database import SessionLocal
    
    logger.info(f"Starting periodic state sync (interval: {STATE_SYNC_INTERVAL}s)")
    while True:
        try:
            await asyncio.sleep(STATE_SYNC_INTERVAL)
            db = SessionLocal()
            try:
                sync_server_states(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Periodic state sync cancelled")
            break
        except Exception as e:
            logger.error(f"Error in periodic state sync: {e}")


app = FastAPI(
    title="Game Server Manager API",
    description="API for managing game servers in Docker containers",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=MessageResponse)
def root():
    """Health check endpoint"""
    logger.info("Health check requested")
    return {"message": "Game Server Manager API is running"}


@app.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """Detailed health check endpoint"""
    logger.info("Detailed health check requested")
    
    # Check database
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"
    
    # Check Docker
    docker_status = "healthy"
    try:
        docker_manager.client.ping()
    except Exception as e:
        logger.error(f"Docker health check failed: {e}")
        docker_status = "unhealthy"
    
    overall = "healthy" if db_status == "healthy" and docker_status == "healthy" else "unhealthy"
    
    return {
        "status": overall,
        "database": db_status,
        "docker": docker_status
    }


@app.post("/servers/sync", response_model=MessageResponse)
def sync_servers(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Manually trigger server state synchronization"""
    logger.info("Manual state sync requested")
    sync_server_states(db)
    return {"message": "Server states synchronized"}


@app.post("/servers", response_model=ServerResponse, status_code=201)
async def create_server(
    server: ServerCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Create a new game server"""
    logger.info(f"Creating server: name={server.name}, image={server.image}, port={server.port}")
    
    # Check server limit
    current_count = db.query(GameServer).count()
    if current_count >= MAX_SERVERS:
        logger.warning(f"Server limit reached: {current_count}/{MAX_SERVERS}")
        raise HTTPException(
            status_code=400,
            detail=f"Maximum server limit ({MAX_SERVERS}) reached"
        )
    
    existing = db.query(GameServer).filter(GameServer.name == server.name).first()
    if existing:
        logger.warning(f"Server name already exists: {server.name}")
        raise HTTPException(status_code=400, detail="Server name already exists")
    
    db_server = GameServer(
        name=server.name,
        image=server.image,
        port=server.port,
        status=ServerStatus.CREATING,
        game_type=server.game_type,
        memory_limit=server.memory_limit,
        cpu_limit=server.cpu_limit,
        rcon_password=server.rcon_password,
        operating=True
    )
    db.add(db_server)
    db.commit()
    db.refresh(db_server)
    
    # Get server-level lock for the newly created server
    lock = await get_server_lock(db_server.id)
    
    async with lock:
        try:
            container_id = await asyncio.to_thread(
                docker_manager.create_container,
                server.name,
                server.image,
                server.port,
                extra_ports=server.extra_ports,
                memory_limit=server.memory_limit or "512m",
                cpu_limit=server.cpu_limit or 1.0
            )
            db_server.container_id = container_id
            db_server.status = ServerStatus.RUNNING
            db_server.operating = False
            db.commit()
            logger.info(f"Server created successfully: id={db_server.id}, container={container_id}")
        except ImagePullError as e:
            logger.error(f"Image pull failed for server {server.name}: {e}")
            db.delete(db_server)
            db.commit()
            raise HTTPException(status_code=400, detail=f"Image pull failed: {e}")
        except PortConflictError as e:
            logger.error(f"Port conflict for server {server.name}: {e}")
            db.delete(db_server)
            db.commit()
            raise HTTPException(status_code=409, detail=str(e))
        except ContainerCreateError as e:
            logger.error(f"Container creation failed for server {server.name}: {e}")
            db.delete(db_server)
            db.commit()
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected error creating server {server.name}: {e}")
            db.delete(db_server)
            db.commit()
            raise HTTPException(status_code=500, detail=f"Internal error: {e}")
        finally:
            db_server.operating = False
            db.commit()
        
        db.refresh(db_server)
        return db_server


@app.get("/servers", response_model=List[ServerResponse])
def list_servers(
    sync: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """List all game servers. Use sync=true to synchronize states first."""
    logger.info(f"Listing all servers (sync={sync})")
    
    if sync:
        sync_server_states(db)
    
    servers = db.query(GameServer).all()
    logger.info(f"Found {len(servers)} servers")
    return servers


@app.get("/servers/{server_id}", response_model=ServerResponse)
def get_server(
    server_id: int,
    sync: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Get a specific game server. Use sync=true to synchronize state first."""
    logger.info(f"Getting server: id={server_id}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        logger.warning(f"Server not found: id={server_id}")
        raise HTTPException(status_code=404, detail="Server not found")
    
    if sync and server.container_id:
        actual_status = docker_manager.sync_container_status(server.container_id)
        if actual_status is None:
            server.status = ServerStatus.ERROR
            server.container_id = None
            db.commit()
        elif actual_status == "running" and server.status != ServerStatus.RUNNING:
            server.status = ServerStatus.RUNNING
            db.commit()
        elif actual_status in ("exited", "stopped") and server.status != ServerStatus.STOPPED:
            server.status = ServerStatus.STOPPED
            db.commit()
    
    return server


@app.post("/servers/{server_id}/start", response_model=MessageResponse)
async def start_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Start a game server"""
    logger.info(f"Starting server: id={server_id}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        logger.warning(f"Server not found: id={server_id}")
        raise HTTPException(status_code=404, detail="Server not found")
    
    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")
    
    if not server.container_id:
        logger.warning(f"No container associated with server: id={server_id}")
        raise HTTPException(status_code=400, detail="No container associated")
    
    server.operating = True
    db.commit()
    
    lock = await get_server_lock(server_id)
    container_lock = await get_container_lock(server.container_id)
    
    async with lock, container_lock:
        try:
            success = await asyncio.to_thread(docker_manager.start_container, server.container_id)
            if success:
                server.status = ServerStatus.RUNNING
                logger.info(f"Server started: id={server_id}")
            else:
                logger.error(f"Failed to start server: id={server_id}")
                raise HTTPException(status_code=500, detail="Failed to start server")
        finally:
            server.operating = False
            db.commit()
    
    db.commit()
    return {"message": f"Server {server.name} started"}


@app.post("/servers/{server_id}/stop", response_model=MessageResponse)
async def stop_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Stop a game server"""
    logger.info(f"Stopping server: id={server_id}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        logger.warning(f"Server not found: id={server_id}")
        raise HTTPException(status_code=404, detail="Server not found")
    
    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")
    
    if not server.container_id:
        logger.warning(f"No container associated with server: id={server_id}")
        raise HTTPException(status_code=400, detail="No container associated")
    
    server.operating = True
    db.commit()
    
    lock = await get_server_lock(server_id)
    container_lock = await get_container_lock(server.container_id)
    
    async with lock, container_lock:
        try:
            success = await asyncio.to_thread(docker_manager.stop_container, server.container_id)
            if success:
                server.status = ServerStatus.STOPPED
                logger.info(f"Server stopped: id={server_id}")
            else:
                logger.error(f"Failed to stop server: id={server_id}")
                raise HTTPException(status_code=500, detail="Failed to stop server")
        finally:
            server.operating = False
            db.commit()
    
    db.commit()
    return {"message": f"Server {server.name} stopped"}


@app.delete("/servers/{server_id}", response_model=MessageResponse)
async def delete_server(
    server_id: int,
    preserve_data: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Delete a game server.
    
    - preserve_data=false (default): Deletes container AND all game data (volumes)
    - preserve_data=true: Deletes container but keeps game data volumes for future use
    """
    logger.info(f"Deleting server: id={server_id}, preserve_data={preserve_data}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        logger.warning(f"Server not found: id={server_id}")
        raise HTTPException(status_code=404, detail="Server not found")
    
    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")
    
    server.status = ServerStatus.DELETING
    server.operating = True
    db.commit()
    
    lock = await get_server_lock(server_id)
    
    async with lock:
        try:
            if server.container_id:
                container_lock = await get_container_lock(server.container_id)
                async with container_lock:
                    # remove_volumes is opposite of preserve_data
                    await asyncio.to_thread(
                        docker_manager.delete_container,
                        server.container_id,
                        remove_volumes=not preserve_data
                    )
                    if not preserve_data:
                        # Also clean up named volumes
                        await asyncio.to_thread(docker_manager.cleanup_volumes, f"game_{server.name}")
            
            db.delete(server)
            db.commit()
            
            if preserve_data:
                logger.info(f"Server deleted (data preserved): id={server_id}, name={server.name}")
                return {"message": f"Server {server.name} deleted. Game data volumes preserved."}
            else:
                logger.info(f"Server deleted (with data): id={server_id}, name={server.name}")
                return {"message": f"Server {server.name} and all game data deleted."}
        finally:
            # Try to reset operating status in case of error (though server might be deleted)
            try:
                server.operating = False
                db.commit()
            except:
                pass


@app.post("/servers/{server_id}/command", response_model=CommandResult)
async def execute_command(
    server_id: int,
    cmd: ServerCommand,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Execute a command on a game server"""
    logger.info(f"Executing command on server: id={server_id}, command={cmd.command}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        logger.warning(f"Server not found: id={server_id}")
        raise HTTPException(status_code=404, detail="Server not found")

    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")

    if not server.container_id:
        logger.warning(f"No container associated with server: id={server_id}")
        raise HTTPException(status_code=400, detail="No container associated")

    if server.status != ServerStatus.RUNNING:
        logger.warning(f"Server not running: id={server_id}, status={server.status}")
        raise HTTPException(status_code=400, detail="Server is not running")

    server.operating = True
    db.commit()

    container_lock = await get_container_lock(server.container_id)
    async with container_lock:
        try:
            exit_code, output = await asyncio.to_thread(
                docker_manager.exec_command, server.container_id, cmd.command
            )
            logger.info(f"Command executed: server_id={server_id}, exit_code={exit_code}")
            return {"exit_code": exit_code, "output": output}
        except ContainerNotFoundError:
            # Container was deleted externally, update status
            server.status = ServerStatus.ERROR
            server.container_id = None
            raise HTTPException(
                status_code=400,
                detail="Container no longer exists. Server status has been updated."
            )
        except CommandExecutionError as e:
            logger.error(f"Command execution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            server.operating = False
            db.commit()


# ==================== Game Server Specific Endpoints ====================

@app.get("/servers/{server_id}/logs", response_model=ServerLogsResponse)
async def get_server_logs(
    server_id: int,
    tail: int = 100,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Get game server logs"""
    logger.info(f"Getting logs for server: id={server_id}, tail={tail}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")

    if not server.container_id:
        raise HTTPException(status_code=400, detail="No container associated")

    server.operating = True
    db.commit()

    container_lock = await get_container_lock(server.container_id)
    async with container_lock:
        try:
            logs = await asyncio.to_thread(
                docker_manager.get_container_logs, server.container_id, tail=tail
            )
            lines = len(logs.splitlines()) if logs else 0
            return {"logs": logs, "lines": lines}
        except ContainerNotFoundError:
            server.status = ServerStatus.ERROR
            server.container_id = None
            raise HTTPException(status_code=400, detail="Container no longer exists")
        finally:
            server.operating = False
            db.commit()


@app.get("/servers/{server_id}/stats", response_model=ServerStatsResponse)
async def get_server_stats(
    server_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Get game server resource usage statistics"""
    logger.info(f"Getting stats for server: id={server_id}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")

    if not server.container_id:
        raise HTTPException(status_code=400, detail="No container associated")

    if server.status != ServerStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Server is not running")

    server.operating = True
    db.commit()

    container_lock = await get_container_lock(server.container_id)
    async with container_lock:
        try:
            stats = await asyncio.to_thread(docker_manager.get_container_stats, server.container_id)
            if not stats:
                raise HTTPException(status_code=500, detail="Failed to get server stats")
            return stats
        finally:
            server.operating = False
            db.commit()


@app.post("/servers/{server_id}/rcon", response_model=CommandResult)
async def send_rcon_command(
    server_id: int,
    cmd: RconCommand,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """Send RCON command to game server (Minecraft, etc.)"""
    logger.info(f"Sending RCON command to server: id={server_id}")
    server = db.query(GameServer).filter(GameServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if server.operating:
        logger.warning(f"Server operation already in progress: id={server_id}")
        raise HTTPException(status_code=409, detail=f"Server {server.name} is currently busy with another operation")

    if not server.container_id:
        raise HTTPException(status_code=400, detail="No container associated")

    if server.status != ServerStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Server is not running")

    if server.game_type != "minecraft":
        raise HTTPException(status_code=400, detail="RCON is only supported for Minecraft servers")

    server.operating = True
    db.commit()

    # Use provided password, fall back to server's stored password, then default
    rcon_password = cmd.password or server.rcon_password or "minecraft"

    container_lock = await get_container_lock(server.container_id)
    async with container_lock:
        try:
            exit_code, output = await asyncio.to_thread(
                docker_manager.send_rcon_command,
                server.container_id,
                cmd.command,
                rcon_password=rcon_password
            )
            return {"exit_code": exit_code, "output": output}
        except ContainerNotFoundError:
            server.status = ServerStatus.ERROR
            server.container_id = None
            db.commit()
            raise HTTPException(status_code=400, detail="Container no longer exists")
        except CommandExecutionError as e:
            logger.error(f"RCON command failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            server.operating = False
            db.commit()
