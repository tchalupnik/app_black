"""BoneIO Web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import (
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketState

from boneio.helper.config import ConfigHelper
from boneio.helper.events import GracefulExit
from boneio.helper.exceptions import ConfigurationException
from boneio.helper.yaml_util import load_config_from_file
from boneio.manager import Manager
from boneio.models import (
    InputState,
    OutputState,
    SensorState,
    StateUpdate,
)
from boneio.models.logs import LogEntry, LogsResponse
from boneio.version import __version__

from .websocket_manager import JWT_ALGORITHM, WebSocketManager

_LOGGER = logging.getLogger(__name__)


class BoneIOApp(FastAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop = asyncio.get_event_loop()

    async def shutdown_handler(self):
        """Handle application shutdown."""
        _LOGGER.debug("Shutting down All WebSocket connections...")
        if hasattr(self.state, 'websocket_manager'):
            await asyncio.sleep(1)
            await self.state.websocket_manager.close_all()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI calls with proper lifespan support."""
        message = None
        if scope["type"] == "lifespan":
            try:
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        try:
                            await send({"type": "lifespan.startup.complete"})
                        except Exception as e:
                            await send(
                                {"type": "lifespan.startup.failed", "message": str(e)}
                            )
                    elif message["type"] == "lifespan.shutdown":
                        try:
                            # First shutdown all WebSocket connections
                            _LOGGER.debug("Starting lifespan shutdown...")
                            await self.shutdown_handler()
                            _LOGGER.debug(
                                "WebSocket connections closed, sending shutdown complete..."
                            )
                            # Only after WebSocket cleanup is done, send shutdown complete
                            await send({"type": "lifespan.shutdown.complete"})
                            _LOGGER.debug("Lifespan shutdown complete sent.")
                        except Exception as e:
                            _LOGGER.error("Error during lifespan shutdown: %s", e)
                            await send(
                                {"type": "lifespan.shutdown.failed", "message": str(e)}
                            )
                        return
            except (asyncio.CancelledError, GracefulExit):
                # Handle graceful exit during lifespan
                _LOGGER.debug("GracefulExit during lifespan, cleaning up...")
                await self.shutdown_handler()
                # await send({"type": "lifespan.shutdown.complete"})
                _LOGGER.debug("Lifespan cleanup complete.")
                return
        try:
            await super().__call__(scope, receive, send)
        except Exception:
            pass


# Create FastAPI application
app = BoneIOApp(
    title="BoneIO API",
    description="BoneIO API for managing inputs, outputs, and sensors",
    version=__version__,
)



# security = HTTPBasic()
JWT_SECRET = os.getenv('JWT_SECRET', secrets.token_hex(32))  # Use environment variable or generate temporary
_auth_config = {}

# Dependency to get manager instance
def get_manager():
    """Get manager instance."""
    return app.state.manager

def get_config_helper():
    """Get config helper instance."""
    return app.state.config_helper


# Add auth required endpoint
@app.get("/api/auth/required")
async def auth_required():
    """Check if authentication is required."""
    try:
        auth_required = bool(
            _auth_config.get("username") and _auth_config.get("password")
        )
        return {"required": auth_required}
    except Exception as e:
        logging.error(f"Error checking auth requirement: {e}")
        # Default to requiring auth if there's an error
        return {"required": True}


# Configure CORS
origins = [
    "http://localhost:5173",  # Default Vite dev server
    "http://localhost:4173",  # Vite preview
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "*",  # Allow all origins during development
]


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for login endpoint and static files
        if (
            not request.url.path.startswith("/api")
            or request.url.path == "/api/login"
            or request.url.path == "/api/auth/required"
            or request.url.path == "/api/version"
        ):
            return await call_next(request)

        if not _auth_config:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "No authorization header"}
            )

        try:
            # Check if it's a Bearer token
            scheme, token = auth_header.split()
            if scheme.lower() != "bearer":
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authentication scheme"}
                )

            # Verify the JWT token
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

            # Check if token has expired
            exp = payload.get("exp")
            if not exp or datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(
                timezone.utc
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token has expired"}
                )

        except jwt.JWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"}
            )
        except ValueError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format"}
            )

        return await call_next(request)


@app.post("/api/login")
async def login(username: str = Body(...), password: str = Body(...)):
    if not _auth_config:
        token = create_token({"sub": "default"})
        return {"token": token}

    if username == _auth_config.get("username") and password == _auth_config.get(
        "password"
    ):
        token = create_token({"sub": username})
        return {"token": token}
    raise HTTPException(status_code=401, detail="Invalid credentials")


def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=7)  # Token expires in 7 days
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def is_running_as_service():
    """Check if running as a systemd service."""
    try:
        with open("/proc/1/comm", "r") as f:
            return "systemd" in f.read()
    except Exception:
        return False


def _clean_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def _decode_ascii_list(ascii_list: list) -> str:
    """Decode a list of ASCII codes into a string and clean ANSI codes."""
    try:
        # Convert ASCII codes to string
        text = ''.join(chr(code) for code in ascii_list)
        # Remove ANSI escape sequences
        return _clean_ansi(text)
    except Exception as e:
        _LOGGER.error(f"Error decoding ASCII list: {e}")
        return str(ascii_list)

def _parse_systemd_log_entry(entry: dict) -> dict:
    """Parse a systemd journal log entry."""
    # Handle MESSAGE field if it's a list of ASCII codes
    if isinstance(entry.get('MESSAGE'), list):
        try:
            # First try to decode the outer message
            decoded_msg = _decode_ascii_list(entry['MESSAGE'])
            
            # Check if the decoded message is a JSON string
            try:
                json_msg = json.loads(decoded_msg)
                # If it has a nested MESSAGE field that's also ASCII codes
                if isinstance(json_msg.get('MESSAGE'), list):
                    json_msg['MESSAGE'] = _decode_ascii_list(json_msg['MESSAGE'])
                entry['MESSAGE'] = json_msg.get('MESSAGE', decoded_msg)
            except json.JSONDecodeError:
                # Not a JSON string, use the decoded message as is
                entry['MESSAGE'] = decoded_msg
            except Exception as e:
                _LOGGER.debug(f"Error parsing nested message: {e}")
                entry['MESSAGE'] = decoded_msg
                
        except Exception as e:
            _LOGGER.error(f"Error parsing message: {e}")
            entry['MESSAGE'] = "Can't decode message"
    
    # Convert timestamps if present
    for ts_field in ('__REALTIME_TIMESTAMP', '__MONOTONIC_TIMESTAMP'):
        if ts_field in entry:
            try:
                entry[ts_field] = int(entry[ts_field])
            except (TypeError, ValueError):
                pass
    
    return entry


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

async def get_systemd_logs(since: str = "-15m") -> List[LogEntry]:
    """Get logs from journalctl."""
    cmd = [
        "journalctl",
        "-u", "boneio",
        "--no-pager",
        "--no-hostname",
        "--output=json",
        "--output-fields=MESSAGE,__REALTIME_TIMESTAMP,PRIORITY",
        "--no-tail",
        "--since", since
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()
    if stderr:
        _LOGGER.error(f"Error getting systemd logs: {stderr.decode()}")
    if not stdout.strip():
        _LOGGER.warning("No logs found")
        return []
    raw_log = json.loads(b'[' + stdout.replace(b'\n', b',')[:-1] + b']')

    log_entries = []
    for log in raw_log:
        if isinstance(log.get('MESSAGE'), list):
            # Handle ASCII-encoded messages
            try:
                message_bytes = bytes(log['MESSAGE'])
                message = message_bytes.decode('utf-8', errors='ignore')
                message = strip_ansi_codes(message)
            except Exception as e:
                message = "Error decoding message: {}".format(e)
        else:
            message = log.get('MESSAGE', '')
        log_entries.append(
            LogEntry(
                timestamp=log.get("__REALTIME_TIMESTAMP", ""),
                message=message,
                level=log.get("PRIORITY", ""),
            )
        )

    return log_entries


def get_standalone_logs(since: str, limit: int) -> List[LogEntry]:
    """Get logs from log file when running standalone."""
    # log_file = Path(app.state.yaml_config_file).parent / "boneio.log"
    log_file = Path("/tmp/boneio.log")
    if not log_file.exists():
        return []

    # Parse since parameter
    if since:
        if since[-1] in ["h", "d"]:
            amount = int(since[:-1])
            unit = since[-1]
            delta = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
            since_time = datetime.now() - delta
        else:
            try:
                since_time = datetime.fromisoformat(since)
            except ValueError:
                since_time = None
    else:
        since_time = None

    log_entries = []
    try:
        with open(log_file, "r") as f:
            # Read from the end of file
            lines = f.readlines()[-limit:]
            for line in lines:
                try:
                    # Assuming log format: "2023-12-27 15:13:44 INFO Message"
                    parts = line.split(" ", 3)
                    if len(parts) >= 4:
                        timestamp_str = f"{parts[0]} {parts[1]}"
                        level = parts[2]
                        message = parts[3].strip()

                        # Convert level to priority
                        level_map = {
                            "DEBUG": "7",
                            "INFO": "6",
                            "WARNING": "4",
                            "ERROR": "3",
                            "CRITICAL": "2",
                        }

                        # Check if log is after since_time
                        if since_time:
                            try:
                                log_time = datetime.strptime(
                                    timestamp_str, "%Y-%m-%d %H:%M:%S"
                                )
                                if log_time < since_time:
                                    continue
                            except ValueError:
                                continue

                        log_entries.append(
                            LogEntry(
                                timestamp=timestamp_str,
                                message=message,
                                level=level_map.get(level.upper(), "6"),
                            )
                        )
                except (IndexError, ValueError):
                    continue
    except Exception as e:
        _LOGGER.warning(f"Error reading log file: {e}")
        return []

    return log_entries


@app.get("/api/logs")
async def get_logs(since: str = "", limit: int = 100) -> LogsResponse:
    """Get logs from either systemd journal or standalone log file."""
    try:
        # Try systemd logs first if running as service
        if is_running_as_service():
            _LOGGER.debug("Fetching from systemd journal...")
            log_entries = await get_systemd_logs(since)
            if log_entries:
                return LogsResponse(logs=log_entries)

        # Fall back to standalone logs
        _LOGGER.debug("Fetching from standalone log file...")
        log_entries = get_standalone_logs(since, limit)
        if log_entries:
            return LogsResponse(logs=log_entries)

        # If no logs found, return a message
        return LogsResponse(
            logs=[
                LogEntry(
                    timestamp=datetime.now().isoformat(),
                    message="No logs available. Please check if logging is properly configured.",
                    level="4",
                )
            ]
        )

    except Exception as e:
        _LOGGER.warning(f"Error fetching logs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/outputs/{output_id}/toggle")
async def toggle_output(output_id: str, manager: Manager = Depends(get_manager)):
    """Toggle output state."""
    if output_id not in manager.outputs:
        raise HTTPException(status_code=404, detail="Output not found")
    await manager.toggle_output(output_id=output_id)
    return {"status": "success"}


@app.post("/api/restart")
async def restart_service(background_tasks: BackgroundTasks):
    """Restart the BoneIO service."""
    if not is_running_as_service():
        return {"status": "not available"}

    async def shutdown_and_restart():
        # First stop the web server
        if app.state.web_server:
            await asyncio.sleep(0.1)  # Allow time for the response to be sent
            os._exit(0)  # Terminate the process

    background_tasks.add_task(shutdown_and_restart)
    return {"status": "success"}


@app.get("/api/version")
async def get_version():
    """Get application version."""
    return {"version": __version__} 

@app.get("/api/name")
async def get_name(config_helper: ConfigHelper = Depends(get_config_helper)):
    """Get application version."""
    return {"name": config_helper.name} 

@app.get("/api/check_configuration")
async def check_configuration():
    """Check if the configuration is valid."""
    try:
        load_config_from_file(config_file=app.state.yaml_config_file)
        return {"status": "success"}
    except ConfigurationException as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/files")
async def list_files(path: str = None):
    """List files in the config directory."""
    config_dir = Path(app.state.yaml_config_file).parent
    base_dir = config_dir / path if path else config_dir

    if not os.path.exists(base_dir):
        raise HTTPException(status_code=404, detail="Path not found")
    
    if not os.path.isdir(base_dir):
        raise HTTPException(status_code=400, detail="Path is not a directory")
    
    def scan_directory(directory: Path):
        items = []
        for entry in os.scandir(directory):
            if entry.name == ".git" or entry.name.startswith("venv"):
                continue
            relative_path = os.path.relpath(entry.path, config_dir)
            if entry.is_dir():
                children = scan_directory(Path(entry.path))
                if children:  # Only include directories that have yaml files in them
                    items.append({
                        "name": entry.name,
                        "path": relative_path,
                        "type": "directory",
                        "children": children
                    })
            elif entry.is_file():
                if entry.name.endswith(('.yaml', '.yml')):
                    items.append({
                        "name": entry.name,
                        "path": relative_path,
                        "type": "file"
                    })
        return items

    try:
        items = [{"name": "config", "path": "", "type": "directory", "children": scan_directory(base_dir)}]
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files/{file_path:path}")
async def get_file_content(file_path: str):
    """Get content of a file."""
    config_dir = Path(app.state.yaml_config_file).parent
    full_path = os.path.join(config_dir, file_path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail="Path is not a file")
    
    if not full_path.endswith(('.yaml', '.yml', '.json')):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/files/{file_path:path}")
async def update_file_content(file_path: str, content: dict = Body(...)):
    """Update content of a file."""
    config_dir = Path(app.state.yaml_config_file).parent
    full_path = os.path.join(config_dir, file_path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail="Path is not a file")
    
    if not full_path.endswith(('.yaml', '.yml', '.json')):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    try:
        with open(full_path, 'w') as f:
            f.write(content["content"])
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def on_exit(self) -> None:
    asyncio.create_task(app.state.websocket_manager.close_all())


async def input_state_changed(input_: InputState):
    """Callback when input state changes."""
    await app.state.websocket_manager.broadcast_state("input", input_)


async def output_state_changed(event: OutputState):
    """Callback when output state changes."""
    await app.state.websocket_manager.broadcast_state("output", event)


async def sensor_state_changed(event: SensorState):
    """Callback when output state changes."""
    await app.state.websocket_manager.broadcast_state("sensor", event)


async def modbus_sensor_state_changed(event: SensorState):
    """Callback when output state changes."""
    await app.state.websocket_manager.broadcast_state("modbus_sensor", event)


def init_app(
    manager: Manager,
    yaml_config_file: str,
    config_helper: ConfigHelper,
    auth_config: dict = {},
    jwt_secret: str = None,
    web_server = None,
) -> BoneIOApp:
    """Initialize the FastAPI application with manager."""
    global _auth_config, JWT_SECRET
    
    # Set JWT secret
    if jwt_secret:
        JWT_SECRET = jwt_secret
    else:
        JWT_SECRET = secrets.token_hex(32)  # Fallback to temporary secret
    
    app.state.manager = manager
    app.state.auth_config = auth_config
    app.state.yaml_config_file = yaml_config_file
    app.state.web_server = web_server
    app.state.config_helper = config_helper
    app.state.websocket_manager = WebSocketManager(
        jwt_secret=jwt_secret,
        auth_required=bool(auth_config)
    )

    if auth_config:
        username = auth_config.get("username")
        password = auth_config.get("password")
        if not username or not password:
            _LOGGER.error("Missing username or password in config!")
        else:
            _auth_config = auth_config
            app.add_middleware(AuthMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def add_listener_for_all_outputs(boneio_manager: Manager):
    for output in boneio_manager.outputs.values():
        boneio_manager.event_bus.add_output_listener(
            output_id=output.id,
            listener_id="ws",
            target=output_state_changed,
        )


def remove_listener_for_all_outputs(boneio_manager: Manager):
    for output in boneio_manager.outputs.values():
        boneio_manager.event_bus.remove_output_listener(
            output_id=output.id, listener_id=f"ws${output.id}"
        )

def add_listener_for_all_inputs(boneio_manager: Manager):
    for input in boneio_manager.inputs:
        boneio_manager.event_bus.add_event_listener(
            event_type="input",
            entity_id=input.pin,
            listener_id="ws",
            target=input_state_changed,
        )


def remove_listener_for_all_inputs(boneio_manager: Manager):
    boneio_manager.event_bus.remove_event_listener_by_type("input")


def sensor_listener_for_all_sensors(boneio_manager: Manager):
    for modbus_sensors in boneio_manager.modbus_sensors.values():
        if not modbus_sensors:
            continue
        for sensor in modbus_sensors.get_all_sensors():
            for single_sensor in sensor.values():
                boneio_manager.event_bus.add_event_listener(
                    event_type="modbus_sensor",
                    entity_id=single_sensor.id,
                    listener_id="ws",
                    target=modbus_sensor_state_changed,
                )
    for single_ina_device in boneio_manager.ina219_sensors:
        for ina in single_ina_device.sensors.values():
            boneio_manager.event_bus.add_event_listener(
                event_type="sensor",
                entity_id=ina.id,
                listener_id="ws",
                target=sensor_state_changed,
            )
    for sensor in boneio_manager.temp_sensors:
        boneio_manager.event_bus.add_event_listener(
            event_type="sensor",
            entity_id=sensor.id,
            listener_id="ws",
            target=sensor_state_changed,
        )


def remove_listener_for_all_sensors(boneio_manager: Manager):
    boneio_manager.event_bus.remove_event_listener_by_type(listener_id="ws")
    boneio_manager.event_bus.remove_event_listener_by_type(listener_id="ws")



@app.websocket("/ws/state")
async def websocket_endpoint(
    websocket: WebSocket, boneio_manager: Manager = Depends(get_manager)
):
    """WebSocket endpoint for all state updates."""
    try:
        # Connect to WebSocket manager
        if await app.state.websocket_manager.connect(websocket):
            _LOGGER.info("New WebSocket connection established")

            async def send_state_update(update: StateUpdate) -> bool:
                """Send state update and return True if successful."""
                try:
                    if websocket.application_state == WebSocketState.CONNECTED:
                        await websocket.send_json(update.dict())
                        return True
                except Exception as e:
                    _LOGGER.error(f"Error sending state update: {type(e).__name__} - {e}")
                return False

            # Send initial states
            try:
                # Send inputs
                for input_ in boneio_manager.inputs:
                    try:
                        input_state = InputState(
                            name=input_.name,
                            state=input_.last_state,
                            type=input_.input_type,
                            pin=input_.pin,
                            timestamp=input_.last_press_timestamp,
                            boneio_input=input_.boneio_input
                        )
                        update = StateUpdate(type="input", data=input_state)
                        if not await send_state_update(update):
                            return

                    except Exception as e:
                        _LOGGER.error(f"Error preparing input state: {type(e).__name__} - {e}")

                # Send outputs
                for output in boneio_manager.outputs.values():
                    try:
                        output_state = OutputState(
                            id=output.id,
                            name=output.name,
                            state=output.state,
                            type=output.output_type,
                            pin=output.pin_id,
                            expander_id=output.expander_id,
                            timestamp=output.last_timestamp,
                        )
                        update = StateUpdate(type="output", data=output_state)
                        if not await send_state_update(update):
                            return

                    except Exception as e:
                        _LOGGER.error(f"Error preparing output state: {type(e).__name__} - {e}")

                # Send modbus sensor states
                for modbus_sensors in boneio_manager.modbus_sensors.values():
                    if not modbus_sensors:
                        continue
                    for sensor in modbus_sensors.get_all_sensors():
                        for single_sensor in sensor.values():
                            try:
                                sensor_state = SensorState(
                                    id=single_sensor.id,
                                    name=single_sensor.name,
                                    state=single_sensor.state,
                                    unit=single_sensor.unit_of_measurement,
                                    timestamp=single_sensor.last_timestamp,
                                )
                                update = StateUpdate(type="modbus_sensor", data=sensor_state)
                                if not await send_state_update(update):
                                    return

                            except Exception as e:
                                _LOGGER.error(f"Error preparing modbus sensor state: {type(e).__name__} - {e}")

                # Send INA219 sensor states
                for single_ina_device in boneio_manager.ina219_sensors:
                    for ina_sensor in single_ina_device.sensors.values():
                        try:
                            sensor_state = SensorState(
                                id=ina_sensor.id,
                                name=ina_sensor.name,
                                state=ina_sensor.state,
                                unit=ina_sensor.unit_of_measurement,
                                timestamp=ina_sensor.last_timestamp,
                            )
                            update = StateUpdate(type="sensor", data=sensor_state)
                            if not await send_state_update(update):
                                return

                        except Exception as e:
                            _LOGGER.error(f"Error preparing INA219 sensor state: {type(e).__name__} - {e}")

                # Send temperature sensor states
                for sensor in boneio_manager.temp_sensors:
                    try:
                        sensor_state = SensorState(
                            id=sensor.id,
                            name=sensor.name,
                            state=sensor.state,
                            unit=sensor.unit_of_measurement,
                            timestamp=sensor.last_timestamp,
                        )
                        update = StateUpdate(type="sensor", data=sensor_state)
                        if not await send_state_update(update):
                            return

                    except Exception as e:
                        _LOGGER.error(f"Error preparing temperature sensor state: {type(e).__name__} - {e}")

            except WebSocketDisconnect:
                _LOGGER.info("WebSocket disconnected while sending initial states")
                return
            except Exception as e:
                _LOGGER.error(f"Error sending initial states: {type(e).__name__} - {e}")
                return

            if websocket.application_state == WebSocketState.CONNECTED:
                _LOGGER.debug("Initial states sent, setting up event listeners")
                add_listener_for_all_outputs(boneio_manager=boneio_manager)
                add_listener_for_all_inputs(boneio_manager=boneio_manager)
                sensor_listener_for_all_sensors(boneio_manager=boneio_manager)

                while True:
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")
    except asyncio.CancelledError:
        _LOGGER.info("WebSocket connection cancelled during setup")
        await app.state.websocket_manager.disconnect(websocket)
        raise
    except WebSocketDisconnect as err:
        _LOGGER.info("WebSocket connection exiting gracefully %s", err)
        await app.state.websocket_manager.disconnect(websocket)
    except KeyboardInterrupt:
        _LOGGER.info("WebSocket connection interrupted by user.")
    except Exception as e:
        _LOGGER.error(f"Unexpected error in WebSocket handler: {type(e).__name__} - {e}")
    finally:
        _LOGGER.debug("Cleaning up WebSocket connection")
        if not app.state.websocket_manager.active_connections:
            remove_listener_for_all_outputs(boneio_manager=boneio_manager)
            remove_listener_for_all_inputs(boneio_manager=boneio_manager)
            remove_listener_for_all_sensors(boneio_manager=boneio_manager)
        # if connection_active:
        #     try:
        #         await asyncio.wait_for(
        #             app.state.websocket_manager.disconnect(websocket),
        #             timeout=2.0
        #         )
        #     except (asyncio.TimeoutError, Exception) as e:
        #         _LOGGER.error(f"Error during WebSocket cleanup: {type(e).__name__} - {e}")

# Static files setup
APP_DIR = Path(__file__).parent
FRONTEND_DIR = APP_DIR / "frontend-dist"


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=f"{FRONTEND_DIR}/assets"), name="assets")
    app.mount("/schema", StaticFiles(directory=f"{APP_DIR}/schema"), name="schema")
    # Route to serve React index.html (for client-side routing)
    @app.get("/{catchall:path}")
    async def serve_react_app(catchall: str):
        return FileResponse(f"{FRONTEND_DIR}/index.html")
