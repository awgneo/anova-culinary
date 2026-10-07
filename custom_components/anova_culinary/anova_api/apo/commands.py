"""CMD_APO_* commands, built as the Anova Oven app builds them (PROTOCOL.md, part 2, §1.2 and §3).

The envelope is {command, payload: {id: <oven id>, type: <command>, payload?}}; the
connection adds the requestId. Every temperature is Celsius.
"""

import uuid
from typing import Any

OVEN_TYPE = "oven_v2"


def generate_id() -> str:
    """A cook or stage id, made like the Android app's."""
    return f"android-{uuid.uuid4()}"


def temperature_bulbs_payload(mode: str, celsius: float) -> dict[str, Any]:
    """A target on the dry or wet (sous vide) bulb."""
    return {"mode": mode, mode: {"setpoint": {"celsius": celsius}}}


def heating_elements_payload(top: bool, bottom: bool, rear: bool) -> dict[str, Any]:
    """Which heating elements are on."""
    return {"top": {"on": top}, "bottom": {"on": bottom}, "rear": {"on": rear}}


def steam_generators_payload(mode: str, setpoint: int) -> dict[str, Any]:
    """Steam as relative-humidity or steam-percentage."""
    key = "relativeHumidity" if mode == "relative-humidity" else "steamPercentage"
    return {"mode": mode, key: {"setpoint": setpoint}}


def probe_payload(celsius: float) -> dict[str, Any]:
    """A probe target."""
    return {"setpoint": {"celsius": celsius}}


def build_command(device_id: str, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """The envelope around one oven command; commands without parameters carry no payload."""
    inner: dict[str, Any] = {"id": device_id, "type": command}
    if payload is not None:
        inner["payload"] = payload
    return {"command": command, "payload": inner}


def build_start_command(
    device_id: str,
    stages: list[dict[str, Any]],
    title: str = "",
    cookable_type: str = "manual",
    cookable_id: str = "",
) -> dict[str, Any]:
    """Starts a cook from its stages (StageV2, see recipe.py)."""
    return build_command(
        device_id,
        "CMD_APO_START",
        {
            "cookId": generate_id(),
            "cookerId": device_id,
            "type": OVEN_TYPE,
            "originSource": "android",
            "cookableType": cookable_type,
            "cookableId": cookable_id,
            "title": title,
            "stages": stages,
        },
    )


def build_stop_command(device_id: str) -> dict[str, Any]:
    """Stops the cook."""
    return build_command(device_id, "CMD_APO_STOP")


def build_update_cook_stages_command(device_id: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Replaces the running cook's stages; the app's path for any stage edit beyond the six live settings."""
    return build_command(device_id, "CMD_APO_UPDATE_COOK_STAGES", {"stages": stages})


def build_set_temperature_bulbs_command(device_id: str, mode: str, celsius: float) -> dict[str, Any]:
    """Sets the active stage's target on the dry or wet (sous vide) bulb."""
    return build_command(device_id, "CMD_APO_SET_TEMPERATURE_BULBS", temperature_bulbs_payload(mode, celsius))


def build_set_fan_command(device_id: str, speed: int) -> dict[str, Any]:
    """Sets the active stage's fan speed (0–100; the app uses 0, 33, 67 and 100)."""
    return build_command(device_id, "CMD_APO_SET_FAN", {"speed": speed})


def build_set_heating_elements_command(device_id: str, top: bool, bottom: bool, rear: bool) -> dict[str, Any]:
    """Sets the active stage's heating elements."""
    return build_command(device_id, "CMD_APO_SET_HEATING_ELEMENTS", heating_elements_payload(top, bottom, rear))


def build_set_steam_generators_command(device_id: str, mode: str, setpoint: int) -> dict[str, Any]:
    """Sets the active stage's steam: relative-humidity or steam-percentage; 0 turns it off."""
    return build_command(device_id, "CMD_APO_SET_STEAM_GENERATORS", steam_generators_payload(mode, setpoint))


def build_set_timer_command(device_id: str, initial: int) -> dict[str, Any]:
    """Sets the active stage's timer length in seconds, leaving when it starts alone."""
    return build_command(device_id, "CMD_APO_SET_TIMER", {"initial": initial})


def build_set_probe_command(device_id: str, celsius: float) -> dict[str, Any]:
    """Sets the active stage's probe target; 0 clears it."""
    return build_command(device_id, "CMD_APO_SET_PROBE", probe_payload(celsius))


def build_set_lamp_command(device_id: str, on: bool) -> dict[str, Any]:
    """Turns the oven light on or off."""
    return build_command(device_id, "CMD_APO_SET_LAMP", {"on": on})


def build_start_descale_command(device_id: str) -> dict[str, Any]:
    """Starts descaling the steam boiler."""
    return build_command(device_id, "CMD_APO_START_DESCALE")


def build_start_live_stream_command(device_id: str) -> dict[str, Any]:
    """Starts (or keeps alive) the cavity camera's stream; the response carries its WebRTC URL."""
    return build_command(device_id, "CMD_APO_START_LIVE_STREAM")


def build_stop_live_stream_command(device_id: str) -> dict[str, Any]:
    """Stops the cavity camera's stream."""
    return build_command(device_id, "CMD_APO_STOP_LIVE_STREAM")
