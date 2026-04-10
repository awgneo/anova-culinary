"""Transpiler Engine for Anova Precision Cookers."""

from typing import Dict, Any, Optional

from .models import APCState

def payload_to_state(raw_payload: Dict[str, Any], existing_state: Optional[APCState] = None) -> APCState:
    """Parses raw websocket telemetry into a pristine APCState.
    
    If existing_state is provided, unmapped fields will seamlessly fall back
    to their existing state values rather than resetting to defaults.
    """
    state_proxy = existing_state or APCState()
    
    # Try fetching from status envelope first, fallback to state
    status_str = raw_payload.get("status", raw_payload.get("state", state_proxy.state))
    state_proxy.state = status_str
    
    state_proxy.current_temperature = raw_payload.get("temperature", state_proxy.current_temperature)
    state_proxy.target_temperature = raw_payload.get("targetTemperature", state_proxy.target_temperature)
    
    # Derive absolute logical truth flag from status payload string
    state_proxy.is_running = state_proxy.state in ["cooking", "preheating", "maintaining"]
    
    return state_proxy
