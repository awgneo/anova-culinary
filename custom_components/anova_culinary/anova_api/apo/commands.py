import uuid
from typing import Dict, Any

from .models import AnovaPOCook
from .transpiler import cook_to_payload
from ..device import AnovaDevice

def build_start_command(device: AnovaDevice, cook: AnovaPOCook) -> Dict[str, Any]:
    """Build the dictionary payload to start an APO cook."""
    return {
        "command": "CMD_APO_START",
        "requestId": str(uuid.uuid4()),
        "payload": {
            "id": device.id,
            "type": "CMD_APO_START",
            "payload": cook_to_payload(cook, device)
        }
    }

def build_update_cook_command(device: AnovaDevice, cook: AnovaPOCook) -> Dict[str, Any]:
    """Build the dictionary payload to natively update a running cook inline."""
    payload_dict = cook_to_payload(cook, device)
    return {
        "command": "CMD_APO_UPDATE_COOK_STAGES",
        "requestId": str(uuid.uuid4()),
        "payload": {
            "id": device.id,
            "type": "CMD_APO_UPDATE_COOK_STAGES",
            "payload": {
                "stages": payload_dict.get("stages", [])
            }
        }
    }

def build_stop_command(device: AnovaDevice) -> Dict[str, Any]:
    """Build the dictionary payload to stop an APO cook."""
    return {
        "command": "CMD_APO_STOP",
        "requestId": str(uuid.uuid4()),
        "payload": {
            "id": device.id,
            "type": "CMD_APO_STOP"
        }
    }
