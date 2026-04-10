"""Anova API Client."""

import asyncio
import copy
import json
import logging
import uuid
from typing import Dict, Callable, Any, Optional

import aiohttp
from .device import AnovaDevice, DeviceType
from .apo import APOState, APOCook
from .apc import APCState
from . import apo, apc
from .auth import FirebaseAuthManager
from .exceptions import AnovaConnectionError, AnovaAuthError, AnovaTimeoutError

_LOGGER = logging.getLogger(__name__)

ANOVA_WS_URL = "wss://devices.anovaculinary.io"


class AnovaClient:
    """Client for interacting with Anova WiFi devices."""

    def __init__(self, token: str, session: Optional[aiohttp.ClientSession] = None):
        """Initialize the Anova client."""
        self._session = session or aiohttp.ClientSession()
        self._token = None
        self._auth_manager = FirebaseAuthManager(self._session, token)

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._devices: Dict[str, AnovaDevice] = {}
        self._apc_states: Dict[str, APCState] = {}
        self._apo_states: Dict[str, APOState] = {}
        
        self._callbacks: list[Callable[[str, Any], None]] = []
        self._listen_task: Optional[asyncio.Task] = None

    @property
    def devices(self) -> Dict[str, AnovaDevice]:
        """Return discovered devices."""
        return self._devices
        
    def get_apc_state(self, device_id: str) -> Optional[APCState]:
        """Get the state of a Precision Cooker."""
        return self._apc_states.get(device_id)

    def get_apo_state(self, device_id: str) -> Optional[APOState]:
        """Get the state of a Precision Oven."""
        return self._apo_states.get(device_id)

    def register_callback(self, callback: Callable[[str, Any], None]) -> Callable[[], None]:
        """Register a callback for state updates."""
        self._callbacks.append(callback)
        def remove_callback():
            self._callbacks.remove(callback)
        return remove_callback

    async def connect(self) -> bool:
        """Connect to the Anova websocket."""
        try:
            self._token = await self._auth_manager.get_valid_token()
        except AnovaAuthError as err:
            raise ValueError("cannot_connect") from err

        url = f"{ANOVA_WS_URL}?token={self._token}&supportedAccessories=APC,APO"
        try:
            self._ws = await self._session.ws_connect(
                url,
                timeout=10,
                heartbeat=30
            )
            # Start background listener task
            self._listen_task = asyncio.create_task(self._listen())
            return True
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise AnovaAuthError("Invalid Personal Access Token") from err
            raise AnovaConnectionError(f"Connection failed: {err}") from err
        except Exception as err:
            raise AnovaConnectionError(f"Unexpected connection error: {err}") from err

    async def close(self):
        """Close connection."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def send_command(self, command: Dict[str, Any]):
        """Send a command to the websocket."""
        if not self._ws or self._ws.closed:
            raise AnovaConnectionError("Websocket not connected.")
        msg = json.dumps(command)
        _LOGGER.debug("Sending payload: %s", msg)
        await self._ws.send_str(msg)

    def _deep_update(self, d: dict, u: dict) -> dict:
        """Deep merge dict u into dict d."""
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._deep_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def get_current_cook(self, device_id: str) -> Optional[APOCook]:
        """Fetch the current universally represented active cook."""
        state = self._apo_states.get(device_id)
        if state and state.cook:
            return copy.deepcopy(state.cook)
        return None

    async def play_cook(self, device_id: str, cook: APOCook):
        """Skinny network wrapper for transmitting an APOCook transpiled payload."""
        device = self._devices.get(device_id)
        if not device or device.type != DeviceType.APO:
            return
            
        payload_dict = apo.cook_to_payload(cook, device)
        
        cmd = {
            "command": "CMD_APO_START",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "id": device_id,
                "type": "CMD_APO_START",
                "payload": payload_dict
            }
        }
        await self.send_command(cmd)

    async def stop_apo_cook(self, device_id: str):
        """Halt operation of an APO device."""
        cmd = {
            "command": "CMD_APO_STOP",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "id": device_id,
                "type": "CMD_APO_STOP"
            }
        }
        await self.send_command(cmd)

    async def play_apc_cook(self, device_id: str, target: float, unit: str, timer: int = 3600):
        """Start operation of an APC device."""
        device = self._devices.get(device_id)
        if not device or device.type != DeviceType.APC:
            return
            
        cmd = {
            "command": "CMD_APC_START",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "cookerId": device_id,
                "type": device.model,
                "targetTemperature": target,
                "unit": unit,
                "timer": timer
            }
        }
        await self.send_command(cmd)

    async def stop_apc_cook(self, device_id: str):
        """Halt operation of an APC device."""
        device = self._devices.get(device_id)
        if not device or device.type != DeviceType.APC:
            return
            
        cmd = {
            "command": "CMD_APC_STOP",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "cookerId": device_id,
                "type": device.model,
            }
        }
        await self.send_command(cmd)


    async def _listen(self):
        """Listen to websocket messages."""
        if not self._ws:
            return
            
        try:
            async for msg in self._ws:
                # Proactively rotate token if nearing expiration on the active connection
                import time
                if time.time() >= self._auth_manager._expires_at:
                    _LOGGER.debug("OAuth Token expired mid-stream, rotating via reconnect.")
                    # Rotating means we must drop and explicitly reconnect since tokens
                    # are passed dynamically in query parameters only on handshake.
                    await self.close()
                    await self.connect()
                    return
                        
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        self._handle_message(data)
                    except json.JSONDecodeError:
                        _LOGGER.error("Failed to decode message: %s", msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("Websocket error: %s", self._ws.exception())
                    break
        except Exception as e:
            _LOGGER.error("Listener loop error: %s", e)

    def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming decoded JSON messages."""
        cmd = data.get("command", "")
        payload = data.get("payload", {})
        
        # Discovery
        if cmd == "EVENT_APC_WIFI_LIST":
            self._process_discovery(payload, DeviceType.APC)
        elif cmd == "EVENT_APO_WIFI_LIST":
            self._process_discovery(payload, DeviceType.APO)
            
        # State Updates
        elif "STATE" in cmd and isinstance(payload, dict):
            # Try to identify device by extracting id from payload
            dev_id = payload.get("id") or payload.get("cookerId")
            if dev_id:
                if "APC" in cmd:
                    self._update_apc_state(dev_id, payload)
                elif "APO" in cmd:
                    self._update_apo_state(dev_id, payload)
                
                # Notify callbacks
                for cb in self._callbacks:
                    cb(dev_id, payload)
        
        # Command responses are typically RESPONSE
        elif cmd == "RESPONSE":
            _LOGGER.debug("Received command response: %s", payload)

    def _process_discovery(self, payload: list, dev_type: DeviceType):
        """Process discovery payload list."""
        if not isinstance(payload, list):
            return
            
        for dev in payload:
            device_id = dev.get("cookerId")
            if device_id and device_id not in self._devices:
                self._devices[device_id] = AnovaDevice(
                    device_id=device_id,
                    type=dev_type,
                    model=dev.get("type", "unknown"),
                    name=dev.get("name", f"Anova {dev_type.value}")
                )
                _LOGGER.info("Discovered %s: %s", dev_type.value, device_id)
                
                if dev_type == DeviceType.APC:
                    self._apc_states[device_id] = APCState()
                else:
                    self._apo_states[device_id] = APOState()

    def _update_apc_state(self, device_id: str, payload: Dict[str, Any]):
        """Update internal APC state based on raw payload."""
        existing = self._apc_states.get(device_id)
        try:
            self._apc_states[device_id] = apc.payload_to_state(payload, existing_state=existing)
        except Exception as e:
            _LOGGER.error("Transpiler failed to unmarshal APC payload: %s", e)
        
    def _update_apo_state(self, device_id: str, payload: Dict[str, Any]):
        """Update internal APO state based on raw payload."""
        # Power the APO transpilation engine
        try:
            state = apo.payload_to_state(payload)
            self._apo_states[device_id] = state
        except Exception as e:
            _LOGGER.error("Transpiler failed to unmarshal payload: %s", e)
