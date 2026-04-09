"""Anova API Client."""

import asyncio
import copy
import json
import logging
import uuid
from typing import Dict, Callable, Any, Optional

import aiohttp
from .models import AnovaDevice, APCState, APOState, DeviceType
from .exceptions import AnovaConnectionError, AnovaAuthError, AnovaTimeoutError

_LOGGER = logging.getLogger(__name__)

ANOVA_WS_URL = "wss://devices.anovaculinary.io"


class AnovaClient:
    """Client for interacting with Anova WiFi devices."""

    def __init__(self, token: str, session: Optional[aiohttp.ClientSession] = None):
        """Initialize the Anova client."""
        self._token = token
        self._session = session or aiohttp.ClientSession()
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

    async def patch_active_stage(self, device_id: str, overrides: Dict[str, Any]) -> None:
        """Patch the active cooking stage without destroying the whole cook."""
        device = self._devices.get(device_id)
        if not device or device.type != DeviceType.APO:
            return

        state = self._apo_states.get(device_id)
        raw_state = state.raw_state.get("payload", {}) if state else {}
        stages = raw_state.get("stages", [])
        
        # Determine target to patch (active stage or stage 0)
        if stages:
            new_stages = copy.deepcopy(stages)
        else:
            if device.model == "oven_v2":
                new_stages = [{
                    "id": str(uuid.uuid4()),
                    "title": "",
                    "description": "",
                    "do": {
                        "type": "cook",
                        "fan": { "speed": 100 },
                        "heatingElements": { "top": {"on": False}, "bottom": {"on": False}, "rear": {"on": True} },
                        "exhaustVent": { "state": "closed" },
                        "temperatureBulbs": { "mode": "dry", "dry": { "setpoint": { "celsius": 175 } } },
                    },
                    "exit": { "conditions": { "and": {} } },
                    "entry": { "conditions": { "and": {} } },
                    "rackPosition": 3
                }]
            else:
                new_stages = [{
                    "id": str(uuid.uuid4()),
                    "stepType": "stage",
                    "type": "cook",
                    "title": "",
                    "description": "",
                    "userActionRequired": False,
                    "fan": { "speed": 100 },
                    "heatingElements": { "top": {"on": False}, "bottom": {"on": False}, "rear": {"on": True} },
                    "vent": { "open": False },
                    "temperatureBulbs": { "mode": "dry", "dry": { "setpoint": { "celsius": 175 } } },
                    "stageTransitionType": "automatic",
                    "rackPosition": 3
                }]

        # Patch the active stage (or index 0 if not found)
        # Because Anova v1 and v2 nest differently, we patch both the top-level stage AND the 'do' block if it exists
        target_stage = new_stages[0]
        active_id = raw_state.get("activeStageId")
        if active_id:
            for s in new_stages:
                if s.get("id") == active_id:
                    target_stage = s
                    break

        self._deep_update(target_stage, overrides)
        if "do" in target_stage:
            self._deep_update(target_stage["do"], overrides)

        inner_payload = {
            "cookId": raw_state.get("cookId") or str(uuid.uuid4()),
            "stages": new_stages
        }
        
        if device.model == "oven_v2":
            inner_payload.update({
                "cookerId": device_id,
                "type": device.model,
                "originSource": "api",
                "cookableType": "manual",
                "cookableId": "",
                "title": ""
            })

        cmd = {
            "command": "CMD_APO_START",
            "requestId": str(uuid.uuid4()),
            "payload": {
                "id": device_id,
                "type": "CMD_APO_START",
                "payload": inner_payload
            }
        }
        await self.send_command(cmd)

    async def _listen(self):
        """Listen to websocket messages."""
        if not self._ws:
            return
            
        try:
            async for msg in self._ws:
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
        if device_id not in self._apc_states:
            self._apc_states[device_id] = APCState()
        
        state = self._apc_states[device_id]
        state.state = payload.get("status", payload.get("state", state.state))
        state.current_temperature = payload.get("temperature", state.current_temperature)
        state.target_temperature = payload.get("targetTemperature", state.target_temperature)
        state.is_running = state.state in ["cooking", "preheating"]
        
    def _update_apo_state(self, device_id: str, payload: Dict[str, Any]):
        """Update internal APO state based on raw payload."""
        if device_id not in self._apo_states:
            self._apo_states[device_id] = APOState()
            
        state = self._apo_states[device_id]
        state.raw_state = payload
        
        # State mapping is highly speculative without full telemetry logs.
        # Store raw payload entirely and parse common fields.
        status = payload.get("status", payload.get("state"))
        if status is not None:
            state.state = status
            state.is_running = status.lower() not in ["idle", "stopped", "standby"]
        else:
            # If no explicit status string, we can infer running state if there's an active stage
            state.is_running = bool(payload.get("activeStageId"))
