import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, verify_api_key
from app.database import Base, get_db
from app.models import GameServer, ServerStatus
from app.schemas import DANGEROUS_PATTERNS

# Create in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


async def override_verify_api_key():
    return None


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[verify_api_key] = override_verify_api_key

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """Create tables before each test and drop after"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestHealthEndpoints:
    """Tests for health check endpoints"""
    
    def test_root(self):
        """Test root health check endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Game Server Manager API is running"}

    @patch('app.main.docker_manager')
    def test_health_all_healthy(self, mock_docker):
        """Test detailed health check when all services are healthy"""
        mock_docker.client.ping.return_value = True
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "healthy"
        assert data["docker"] == "healthy"

    @patch('app.main.docker_manager')
    def test_health_docker_unhealthy(self, mock_docker):
        """Test health check when Docker is unhealthy"""
        mock_docker.client.ping.side_effect = Exception("Docker not available")
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["docker"] == "unhealthy"


class TestServerList:
    """Tests for server listing"""
    
    def test_list_servers_empty(self):
        """Test listing servers when none exist"""
        response = client.get("/servers")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_servers_with_data(self):
        """Test listing servers with existing data"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING
        )
        db.add(server)
        db.commit()
        db.close()
        
        response = client.get("/servers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "test_server"


class TestServerGet:
    """Tests for getting individual servers"""
    
    def test_get_server_not_found(self):
        """Test getting a non-existent server"""
        response = client.get("/servers/99999")
        assert response.status_code == 404

    def test_get_server_success(self):
        """Test getting an existing server"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "test_server"


class TestServerCreate:
    """Tests for server creation"""
    
    def test_create_server_invalid_port_low(self):
        """Test creating server with port below allowed range"""
        response = client.post(
            "/servers",
            json={"name": "test", "image": "alpine:latest", "port": 80}
        )
        assert response.status_code == 422

    def test_create_server_invalid_port_high(self):
        """Test creating server with port above allowed range"""
        response = client.post(
            "/servers",
            json={"name": "test", "image": "alpine:latest", "port": 70000}
        )
        assert response.status_code == 422

    def test_create_server_invalid_name(self):
        """Test creating server with invalid name characters"""
        response = client.post(
            "/servers",
            json={"name": "test server!", "image": "alpine:latest", "port": 25565}
        )
        assert response.status_code == 422

    def test_create_server_duplicate_name(self):
        """Test creating server with duplicate name"""
        db = TestingSessionLocal()
        server = GameServer(
            name="existing",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING
        )
        db.add(server)
        db.commit()
        db.close()
        
        response = client.post(
            "/servers",
            json={"name": "existing", "image": "alpine:latest", "port": 25566}
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @patch('app.main.docker_manager')
    def test_create_server_success(self, mock_docker):
        """Test successful server creation"""
        mock_docker.create_container.return_value = "container123"
        
        response = client.post(
            "/servers",
            json={
                "name": "minecraft_server",
                "image": "alpine:latest",
                "port": 25565,
                "game_type": "minecraft",
                "memory_limit": "1g",
                "cpu_limit": 2.0
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "minecraft_server"
        assert data["game_type"] == "minecraft"
        assert data["memory_limit"] == "1g"
        assert data["cpu_limit"] == 2.0

    @patch('app.main.MAX_SERVERS', 1)
    def test_create_server_limit_reached(self):
        """Test server creation when limit is reached"""
        db = TestingSessionLocal()
        server = GameServer(
            name="existing",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING
        )
        db.add(server)
        db.commit()
        db.close()
        
        response = client.post(
            "/servers",
            json={"name": "new_server", "image": "alpine:latest", "port": 25566}
        )
        assert response.status_code == 400
        assert "limit" in response.json()["detail"].lower()


class TestServerOperations:
    """Tests for server start/stop/delete operations"""
    
    @patch('app.main.docker_manager')
    def test_start_server_success(self, mock_docker):
        """Test starting a server"""
        mock_docker.start_container.return_value = True
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(f"/servers/{server_id}/start")
        assert response.status_code == 200

    @patch('app.main.docker_manager')
    def test_stop_server_success(self, mock_docker):
        """Test stopping a server"""
        mock_docker.stop_container.return_value = True
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(f"/servers/{server_id}/stop")
        assert response.status_code == 200

    @patch('app.main.docker_manager')
    def test_delete_server_success(self, mock_docker):
        """Test deleting a server"""
        mock_docker.delete_container.return_value = True
        mock_docker.cleanup_volumes.return_value = True
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.delete(f"/servers/{server_id}")
        assert response.status_code == 200

    def test_start_server_no_container(self):
        """Test starting server without container"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.ERROR,
            container_id=None
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(f"/servers/{server_id}/start")
        assert response.status_code == 400


class TestCommandExecution:
    """Tests for command execution"""
    
    def test_command_dangerous_rm_rf(self):
        """Test that rm -rf / is blocked"""
        response = client.post(
            "/servers/1/command",
            json={"command": "rm -rf /"}
        )
        assert response.status_code == 422

    def test_command_dangerous_pipe_injection(self):
        """Test that pipe injection is blocked"""
        response = client.post(
            "/servers/1/command",
            json={"command": "ls | rm -rf /"}
        )
        assert response.status_code == 422

    def test_command_dangerous_command_chain(self):
        """Test that command chaining is blocked"""
        response = client.post(
            "/servers/1/command",
            json={"command": "ls && rm -rf /"}
        )
        assert response.status_code == 422

    @patch('app.main.docker_manager')
    def test_command_safe_ls(self, mock_docker):
        """Test that safe commands are allowed"""
        mock_docker.exec_command.return_value = (0, "file1\nfile2")
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(
            f"/servers/{server_id}/command",
            json={"command": "ls -la"}
        )
        assert response.status_code == 200

    def test_command_server_not_running(self):
        """Test command execution on stopped server"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(
            f"/servers/{server_id}/command",
            json={"command": "ls"}
        )
        assert response.status_code == 400
        assert "not running" in response.json()["detail"]


class TestStateSync:
    """Tests for state synchronization"""
    
    @patch('app.main.docker_manager')
    def test_sync_servers_endpoint(self, mock_docker):
        """Test manual sync endpoint"""
        mock_docker.sync_container_status.return_value = "running"
        
        response = client.post("/servers/sync")
        assert response.status_code == 200
        assert "synchronized" in response.json()["message"].lower()

    @patch('app.main.docker_manager')
    def test_sync_detects_missing_container(self, mock_docker):
        """Test that sync detects externally deleted containers"""
        mock_docker.sync_container_status.return_value = None
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}?sync=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["container_id"] is None


class TestInputValidation:
    """Tests for input validation"""
    
    def test_server_name_with_spaces(self):
        """Test that server names with spaces are rejected"""
        response = client.post(
            "/servers",
            json={"name": "my server", "image": "alpine:latest", "port": 25565}
        )
        assert response.status_code == 422

    def test_server_name_with_special_chars(self):
        """Test that server names with special characters are rejected"""
        response = client.post(
            "/servers",
            json={"name": "server@123", "image": "alpine:latest", "port": 25565}
        )
        assert response.status_code == 422

    def test_server_name_valid(self):
        """Test that valid server names are accepted"""
        with patch('app.main.docker_manager') as mock_docker:
            mock_docker.create_container.return_value = "container123"
            response = client.post(
                "/servers",
                json={"name": "my-server_123", "image": "alpine:latest", "port": 25565}
            )
            assert response.status_code == 201

    def test_cpu_limit_too_high(self):
        """Test that CPU limit above max is rejected"""
        response = client.post(
            "/servers",
            json={"name": "test", "image": "alpine:latest", "port": 25565, "cpu_limit": 10.0}
        )
        assert response.status_code == 422

    def test_cpu_limit_too_low(self):
        """Test that CPU limit below min is rejected"""
        response = client.post(
            "/servers",
            json={"name": "test", "image": "alpine:latest", "port": 25565, "cpu_limit": 0.01}
        )
        assert response.status_code == 422


class TestServerLogs:
    """Tests for server logs endpoint"""
    
    @patch('app.main.docker_manager')
    def test_get_logs_success(self, mock_docker):
        """Test getting server logs"""
        mock_docker.get_container_logs.return_value = "line1\nline2\nline3"
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}/logs?tail=50")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert data["lines"] == 3

    def test_get_logs_no_container(self):
        """Test getting logs for server without container"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.ERROR,
            container_id=None
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}/logs")
        assert response.status_code == 400


class TestServerStats:
    """Tests for server stats endpoint"""
    
    @patch('app.main.docker_manager')
    def test_get_stats_success(self, mock_docker):
        """Test getting server stats"""
        mock_docker.get_container_stats.return_value = {
            "cpu_percent": 15.5,
            "memory_usage": 1073741824,
            "memory_limit": 2147483648,
            "memory_percent": 50.0,
            "network_rx": 102400,
            "network_tx": 51200
        }
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["cpu_percent"] == 15.5
        assert data["memory_percent"] == 50.0

    def test_get_stats_server_not_running(self):
        """Test getting stats for stopped server"""
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.get(f"/servers/{server_id}/stats")
        assert response.status_code == 400


class TestRconCommand:
    """Tests for RCON command endpoint"""
    
    @patch('app.main.docker_manager')
    def test_rcon_success(self, mock_docker):
        """Test successful RCON command"""
        mock_docker.send_rcon_command.return_value = (0, "There are 5 players online")
        
        db = TestingSessionLocal()
        server = GameServer(
            name="minecraft_server",
            image="itzg/minecraft-server:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123",
            game_type="minecraft",
            rcon_password="secret123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(
            f"/servers/{server_id}/rcon",
            json={"command": "list"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["exit_code"] == 0

    def test_rcon_non_minecraft(self):
        """Test RCON on non-Minecraft server"""
        db = TestingSessionLocal()
        server = GameServer(
            name="terraria_server",
            image="ryshe/terraria:latest",
            port=7777,
            status=ServerStatus.RUNNING,
            container_id="container123",
            game_type="terraria"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(
            f"/servers/{server_id}/rcon",
            json={"command": "list"}
        )
        assert response.status_code == 400
        assert "Minecraft" in response.json()["detail"]

    @patch('app.main.docker_manager')
    def test_rcon_uses_stored_password(self, mock_docker):
        """Test that RCON uses stored password when not provided"""
        mock_docker.send_rcon_command.return_value = (0, "OK")
        
        db = TestingSessionLocal()
        server = GameServer(
            name="minecraft_server",
            image="itzg/minecraft-server:latest",
            port=25565,
            status=ServerStatus.RUNNING,
            container_id="container123",
            game_type="minecraft",
            rcon_password="stored_secret"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.post(
            f"/servers/{server_id}/rcon",
            json={"command": "list"}
        )
        assert response.status_code == 200
        # Verify stored password was used
        mock_docker.send_rcon_command.assert_called_once()
        call_args = mock_docker.send_rcon_command.call_args
        assert call_args[1]["rcon_password"] == "stored_secret"


class TestDeleteWithPreserveData:
    """Tests for delete with preserve_data option"""
    
    @patch('app.main.docker_manager')
    def test_delete_with_data(self, mock_docker):
        """Test deleting server with data"""
        mock_docker.delete_container.return_value = True
        mock_docker.cleanup_volumes.return_value = True
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.delete(f"/servers/{server_id}")
        assert response.status_code == 200
        assert "all game data deleted" in response.json()["message"]
        mock_docker.delete_container.assert_called_with("container123", remove_volumes=True)

    @patch('app.main.docker_manager')
    def test_delete_preserve_data(self, mock_docker):
        """Test deleting server while preserving data"""
        mock_docker.delete_container.return_value = True
        
        db = TestingSessionLocal()
        server = GameServer(
            name="test_server",
            image="alpine:latest",
            port=25565,
            status=ServerStatus.STOPPED,
            container_id="container123"
        )
        db.add(server)
        db.commit()
        server_id = server.id
        db.close()
        
        response = client.delete(f"/servers/{server_id}?preserve_data=true")
        assert response.status_code == 200
        assert "preserved" in response.json()["message"]
        mock_docker.delete_container.assert_called_with("container123", remove_volumes=False)
