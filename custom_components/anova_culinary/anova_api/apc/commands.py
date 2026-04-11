import uuid
from typing import Dict, Any

from ..device import AnovaDevice

def build_start_command(device: AnovaDevice, target: float, unit: str, timer: int = 3600) -> Dict[str, Any]:
    """Build the dictionary payload to start an APC cook."""
    return {
        "command": "CMD_APC_START",
        "requestId": str(uuid.uuid4()),
        "payload": {
            "cookerId": device.id,
            "type": device.type,
            "targetTemperature": target,
            "unit": unit,
            "timer": timer
        }
    }

def build_stop_command(device: AnovaDevice) -> Dict[str, Any]:
    """Build the dictionary payload to stop an APC cook."""
    return {
        "command": "CMD_APC_STOP",
        "requestId": str(uuid.uuid4()),
        "payload": {
            "cookerId": device.id,
            "type": device.type,
        }
    }
