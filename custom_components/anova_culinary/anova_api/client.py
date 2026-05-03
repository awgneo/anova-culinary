"""Anova API Client."""

import asyncio
import copy
import json
import logging
import uuid
from typing import Dict, Callable, Any, Optional, Union

import aiohttp
from .device import AnovaDevice, AnovaProduct
from .apo import AnovaPOState, AnovaPOCook
from .apc import AnovaPCState, AnovaPCCook
from . import apo, apc
from .auth import AnovaAuth
from .exceptions import AnovaConnectionError, AnovaAuthError

_LOGGER = logging.getLogger(__name__)

ANOVA_WS_URL = "wss://devices.anovaculinary.io"


class AnovaClient:
    """Client for interacting with Anova WiFi devices."""

    def __init__(self, token: str, session: Optional[aiohttp.ClientSession] = None):
        """Initialize the Anova client."""
        self._session = session or aiohttp.ClientSession()
        self._token = None
        self._auth_manager = AnovaAuth(self._session, token)

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._devices: Dict[str, AnovaDevice] = {}
        
        self._callbacks: list[Callable[[str], None]] = []
        self._listen_task: Optional[asyncio.Task] = None

    @property
    def devices(self) -> Dict[str, AnovaDevice]:
        """Return discovered devices."""
        return self._devices
        
    def get_apc_state(self, device_id: str) -> Optional[AnovaPCState]:
        """Get the state of a Precision Cooker."""
        device = self._devices.get(device_id)
        if device and device.product == AnovaProduct.APC:
            return device.state
        return None

    def get_apo_state(self, device_id: str) -> Optional[AnovaPOState]:
        """Get the state of a Precision Oven."""
        device = self._devices.get(device_id)
        if device and device.product == AnovaProduct.APO:
            return device.state
        return None

    def register_callback(self, callback: Callable[[str], None]) -> Callable[[], None]:
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

    def get_current_cook(self, device_id: str) -> Optional[AnovaPOCook]:
        """Fetch the current universally represented active cook."""
        state = self.get_apo_state(device_id)
        if state and state.cook:
            return copy.deepcopy(state.cook)
        return None

    async def play_cook(self, device_id: str, cook: Union[AnovaPOCook, AnovaPCCook]):
        """Unified command wrapper to start or update a cook based on device product type."""
        device = self._devices.get(device_id)
        if not device:
            return

        if isinstance(cook, AnovaPOCook):
            if device.product != AnovaProduct.APO:
                return
            state = self.get_apo_state(device_id)
            if state and state.cook and state.is_running and state.cook.cook_id == cook.cook_id:
                cmd = apo.build_update_cook_command(device, cook)
            else:
                cmd = apo.build_start_command(device, cook)
                
        elif isinstance(cook, AnovaPCCook):
            if device.product != AnovaProduct.APC:
                return
            cmd = apc.build_start_command(
                device, 
                target=cook.target_temperature, 
                unit=cook.temperature_unit.value, 
                timer=cook.timer
            )
        else:
            return

        await self.send_command(cmd)
        
        # Optimistically update the local state to provide instant UI feedback
        if device.state:
            device.state.is_running = True
            if isinstance(cook, AnovaPOCook):
                device.state.cook = copy.deepcopy(cook)
            # Fire callbacks instantly so all dependent entities refresh
            for cb in self._callbacks:
                cb(device_id)

    async def update_cook(self, device_id: str, cook: AnovaPOCook):
        """Legacy helper matching update API; falls back to exact update implementation."""
        device = self._devices.get(device_id)
        if not device or device.product != AnovaProduct.APO:
            return
            
        cmd = apo.build_update_cook_command(device, cook)
        await self.send_command(cmd)

    async def stop_cook(self, device_id: str):
        """Unified command wrapper to gracefully halt any active operation."""
        device = self._devices.get(device_id)
        if not device:
            return
            
        if device.product == AnovaProduct.APO:
            cmd = apo.build_stop_command(device)
        elif device.product == AnovaProduct.APC:
            cmd = apc.build_stop_command(device)
        else:
            return
            
        await self.send_command(cmd)
        
        # Optimistically update the local state
        if device.state:
            device.state.is_running = False
            if hasattr(device.state, "nodes") and hasattr(device.state.nodes, "door_lamp_on"):
                device.state.nodes.door_lamp_on = False
            for cb in self._callbacks:
                cb(device_id)

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
            self._process_discovery(payload, AnovaProduct.APC)
        elif cmd == "EVENT_APO_WIFI_LIST":
            self._process_discovery(payload, AnovaProduct.APO)
            
        # State Updates
        elif "STATE" in cmd and isinstance(payload, dict):
            # Try to identify device by extracting id from payload
            dev_id = payload.get("id") or payload.get("cookerId")
            if dev_id:
                _LOGGER.debug("Received STATE broadcast for %s: %s", dev_id, payload)
                if "APC" in cmd:
                    self._update_apc_state(dev_id, payload)
                elif "APO" in cmd:
                    self._update_apo_state(dev_id, payload)
                
                # Notify callbacks
                for cb in self._callbacks:
                    cb(dev_id)
        
        # Command responses are typically RESPONSE
        elif cmd == "RESPONSE":
            _LOGGER.debug("Received command response: %s", payload)

    def _process_discovery(self, payload: list, product: AnovaProduct):
        """Process discovery payload list."""
        if not isinstance(payload, list):
            return
            
        for discovery in payload:
            device_id = discovery.get("cookerId")
            if device_id and device_id not in self._devices:
                # Initialize device using the new dataclass features
                self._devices[device_id] = AnovaDevice(
                    id=device_id,
                    product=product,
                    type=discovery.get("type", "Unknown"),
                    name=discovery.get("name", "")
                )
                
                device = self._devices[device_id]
                _LOGGER.info("Discovered %s: %s (%s)", product.value, device_id, device.model)

                if product == AnovaProduct.APC:
                    device.state = AnovaPCState()
                else:
                    device.state = AnovaPOState()

    def _update_apc_state(self, device_id: str, payload: Dict[str, Any]):
        """Update internal APC state based on raw payload."""
        device = self._devices.get(device_id)
        if not device: return
        try:
            device.state = apc.payload_to_state(payload, existing_state=device.state)
        except Exception as e:
            _LOGGER.error("Transpiler failed to unmarshal APC payload: %s", e)
        
    def _update_apo_state(self, device_id: str, payload: Dict[str, Any]):
        """Update internal APO state based on raw payload."""
        device = self._devices.get(device_id)
        if not device: return
        try:
            device.state = apo.payload_to_state(payload)
        except Exception as e:
            _LOGGER.error("Transpiler failed to unmarshal payload: %s", e)
