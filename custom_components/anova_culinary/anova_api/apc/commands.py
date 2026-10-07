"""CMD_APC_* commands, built as the Anova app builds them (PROTOCOL.md, part 3, §2).

The envelope is {command, payload: {cookerId, type: <cooker type>, ...parameters,
requestId}}: the app adds a second requestId inside the payload, unlike the oven's. The
connection adds the outer one.
"""

import uuid
from typing import Any


def build_command(device_id: str, device_type: str, command: str, **payload: Any) -> dict[str, Any]:
    """The envelope around one cooker command."""
    return {
        "command": command,
        "payload": {"cookerId": device_id, "type": device_type, **payload, "requestId": str(uuid.uuid4())},
    }


def build_start_command(device_id: str, device_type: str, target: float, unit: str, timer: int = 0) -> dict[str, Any]:
    """Starts a cook at `target` in `unit` (C or F); `timer` in seconds, 0 for none."""
    return build_command(device_id, device_type, "CMD_APC_START", targetTemperature=target, unit=unit, timer=timer)


def build_stop_command(device_id: str, device_type: str) -> dict[str, Any]:
    """Stops the cook."""
    return build_command(device_id, device_type, "CMD_APC_STOP")


def build_set_target_temperature_command(device_id: str, device_type: str, target: float, unit: str) -> dict[str, Any]:
    """Changes the running cook's target (sent as CMD_APC_SET_TARGET_TEMP, as the app does)."""
    return build_command(device_id, device_type, "CMD_APC_SET_TARGET_TEMP", targetTemperature=target, unit=unit)


def build_set_timer_command(device_id: str, device_type: str, timer: int) -> dict[str, Any]:
    """Changes or adds the running cook's timer, in seconds."""
    return build_command(device_id, device_type, "CMD_APC_SET_TIMER", timer=timer)
