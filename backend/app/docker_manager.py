import logging
import asyncio
import docker
from docker.errors import NotFound, APIError, ImageNotFound
from typing import Optional, Tuple, Dict, Any, List
from .config import (
    DOCKER_SOCKET, DOCKER_TIMEOUT, DOCKER_PULL_TIMEOUT, DOCKER_STOP_TIMEOUT,
    DEFAULT_MEMORY_LIMIT, DEFAULT_CPU_LIMIT
)

logger = logging.getLogger(__name__)

_container_locks: dict[str, asyncio.Lock] = {}
_lock_lock = asyncio.Lock()

async def get_container_lock(container_id: str) -> asyncio.Lock:
    async with _lock_lock:
        if container_id not in _container_locks:
            _container_locks[container_id] = asyncio.Lock()
        return _container_locks[container_id]


class DockerError(Exception):
    """Base exception for Docker operations"""
    pass


class ImagePullError(DockerError):
    """Raised when image pull fails"""
    pass


class ContainerCreateError(DockerError):
    """Raised when container creation fails"""
    pass


class PortConflictError(DockerError):
    """Raised when port is already in use"""
    pass


class CommandExecutionError(DockerError):
    """Raised when command execution fails"""
    pass


class ContainerNotFoundError(DockerError):
    """Raised when container is not found"""
    pass


class DockerManager:
    def __init__(self, socket_url: str = DOCKER_SOCKET):
        self.socket_url = socket_url
        self.timeout = DOCKER_TIMEOUT
        self.pull_timeout = DOCKER_PULL_TIMEOUT
        self.stop_timeout = DOCKER_STOP_TIMEOUT
        self._client = None
        logger.info(f"DockerManager initialized with socket: {socket_url}")

    @property
    def client(self):
        if self._client is None:
            logger.info(f"Connecting to Docker at: {self.socket_url}")
            try:
                self._client = docker.DockerClient(base_url=self.socket_url, timeout=self.timeout)
                logger.info("Docker client connected successfully")
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                raise
        return self._client

    def create_container(
        self, 
        name: str, 
        image: str, 
        port: int,
        extra_ports: Optional[List[int]] = None,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        cpu_limit: float = DEFAULT_CPU_LIMIT
    ) -> str:
        logger.info(f"Creating container: name={name}, image={image}, port={port}, memory={memory_limit}, cpu={cpu_limit}")
        
        # Pull image
        try:
            logger.info(f"Pulling image: {image}")
            self.client.images.pull(image)
            logger.info(f"Image pulled successfully: {image}")
        except ImageNotFound as e:
            logger.error(f"Image not found: {image} - {e}")
            raise ImagePullError(f"Image not found: {image}")
        except APIError as e:
            logger.error(f"Failed to pull image {image}: {e}")
            raise ImagePullError(f"Failed to pull image {image}: {e}")
        
        # Build port mappings
        port_bindings = {f"{port}/tcp": port}
        if extra_ports:
            for p in extra_ports:
                port_bindings[f"{p}/tcp"] = p
        
        # Create container with resource limits
        try:
            container = self.client.containers.run(
                image=image,
                name=f"game_{name}",
                ports=port_bindings,
                detach=True,
                stdin_open=True,
                tty=True,
                restart_policy={"Name": "unless-stopped"},
                mem_limit=memory_limit,
                nano_cpus=int(cpu_limit * 1e9),  # Convert to nanoseconds
            )
            logger.info(f"Container created: id={container.id}, name=game_{name}")
            return container.id
        except APIError as e:
            error_msg = str(e)
            if "port is already allocated" in error_msg or "address already in use" in error_msg:
                logger.error(f"Port conflict on port {port}: {e}")
                raise PortConflictError(f"Port {port} is already in use")
            elif "Conflict" in error_msg:
                logger.error(f"Container name conflict: game_{name}")
                raise ContainerCreateError(f"Container name 'game_{name}' already exists")
            else:
                logger.error(f"Failed to create container: {e}")
                raise ContainerCreateError(f"Failed to create container: {e}")

    def start_container(self, container_id: str) -> bool:
        logger.info(f"Starting container: {container_id}")
        try:
            container = self.client.containers.get(container_id)
            container.start()
            logger.info(f"Container started: {container_id}")
            return True
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            return False
        except APIError as e:
            logger.error(f"Failed to start container {container_id}: {e}")
            return False

    def stop_container(self, container_id: str) -> bool:
        logger.info(f"Stopping container: {container_id}")
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=self.stop_timeout)
            logger.info(f"Container stopped: {container_id}")
            return True
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            return False
        except APIError as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            return False

    def delete_container(self, container_id: str, remove_volumes: bool = True) -> bool:
        """Delete container, optionally preserving volumes"""
        logger.info(f"Deleting container: {container_id}, remove_volumes={remove_volumes}")
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True, v=remove_volumes)
            logger.info(f"Container deleted: {container_id}")
            return True
        except NotFound:
            logger.info(f"Container already removed: {container_id}")
            return True
        except APIError as e:
            logger.error(f"Failed to delete container {container_id}: {e}")
            return False

    def exec_command(self, container_id: str, command: str) -> Tuple[int, str]:
        logger.info(f"Executing command on container {container_id}: {command}")
        try:
            container = self.client.containers.get(container_id)
            result = container.exec_run(command, demux=True)
            output = ""
            if result.output[0]:
                output += result.output[0].decode("utf-8", errors="replace")
            if result.output[1]:
                output += result.output[1].decode("utf-8", errors="replace")
            logger.info(f"Command executed: exit_code={result.exit_code}")
            return result.exit_code, output
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            raise ContainerNotFoundError(f"Container {container_id} not found")
        except APIError as e:
            logger.error(f"Failed to execute command on {container_id}: {e}")
            raise CommandExecutionError(f"Failed to execute command: {e}")

    def get_container_status(self, container_id: str) -> Optional[str]:
        logger.debug(f"Getting status for container: {container_id}")
        try:
            container = self.client.containers.get(container_id)
            status = container.status
            logger.debug(f"Container {container_id} status: {status}")
            return status
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            return None

    def get_container_info(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed container information"""
        try:
            container = self.client.containers.get(container_id)
            return {
                "id": container.id,
                "status": container.status,
                "name": container.name,
                "image": container.image.tags[0] if container.image.tags else "unknown",
            }
        except NotFound:
            return None

    def sync_container_status(self, container_id: str) -> Optional[str]:
        """
        Sync and return the actual container status.
        Returns None if container doesn't exist.
        """
        return self.get_container_status(container_id)

    def cleanup_volumes(self, container_name: str) -> bool:
        """Clean up volumes associated with a container"""
        try:
            volumes = self.client.volumes.list(filters={"name": container_name})
            for volume in volumes:
                try:
                    volume.remove(force=True)
                    logger.info(f"Removed volume: {volume.name}")
                except APIError as e:
                    logger.warning(f"Failed to remove volume {volume.name}: {e}")
            return True
        except APIError as e:
            logger.error(f"Failed to cleanup volumes for {container_name}: {e}")
            return False
    def get_container_logs(self, container_id: str, tail: int = 100, since: Optional[int] = None) -> str:
        """Get container logs"""
        logger.info(f"Getting logs for container: {container_id}, tail={tail}")
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail, since=since, timestamps=True)
            return logs.decode("utf-8", errors="replace")
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            raise ContainerNotFoundError(f"Container {container_id} not found")
        except APIError as e:
            logger.error(f"Failed to get logs for {container_id}: {e}")
            return f"Error getting logs: {e}"

    def get_container_stats(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get container resource usage statistics"""
        logger.debug(f"Getting stats for container: {container_id}")
        try:
            container = self.client.containers.get(container_id)
            stats = container.stats(stream=False)

            # Parse CPU usage
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                          stats['precpu_stats']['system_cpu_usage']
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0

            # Parse memory usage
            memory_usage = stats['memory_stats'].get('usage', 0)
            memory_limit = stats['memory_stats'].get('limit', 0)
            memory_percent = (memory_usage / memory_limit * 100) if memory_limit > 0 else 0

            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_usage": memory_usage,
                "memory_limit": memory_limit,
                "memory_percent": round(memory_percent, 2),
                "network_rx": stats.get('networks', {}).get('eth0', {}).get('rx_bytes', 0),
                "network_tx": stats.get('networks', {}).get('eth0', {}).get('tx_bytes', 0),
            }
        except NotFound:
            logger.warning(f"Container not found: {container_id}")
            return None
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to parse stats for {container_id}: {e}")
            return None
        except APIError as e:
            logger.error(f"Failed to get stats for {container_id}: {e}")
            return None

    def send_rcon_command(self, container_id: str, command: str, rcon_password: str = "minecraft", rcon_port: int = 25575) -> Tuple[int, str]:
        """Send RCON command to game server (for Minecraft and similar games)"""
        logger.info(f"Sending RCON command to container {container_id}: {command}")
        # Use mcrcon inside the container
        rcon_cmd = f"rcon-cli --password {rcon_password} {command}"
        return self.exec_command(container_id, rcon_cmd)


docker_manager = DockerManager()
