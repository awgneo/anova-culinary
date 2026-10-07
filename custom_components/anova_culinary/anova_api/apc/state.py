"""The third-generation Precision Cooker state (EVENT_APC_STATE), typed after the app's
SousVideState schema. PROTOCOL.md (part 3, §3.2–3.5) has the full tree.
"""

from dataclasses import dataclass, field

from ..models import AnovaCook, AnovaModel, AnovaSystemInfo, AnovaTemperature, AnovaTimerNode, wire

# Modes that are alarms rather than cooking states
ALARM_MODES = ("lowWater", "waterLeak", "highTemp", "motorStuck")


@dataclass
class AnovaPCWaterSensor(AnovaModel):
    """The water temperature and its target."""

    current: AnovaTemperature = field(default_factory=AnovaTemperature)
    setpoint: AnovaTemperature = field(default_factory=AnovaTemperature)
    enabled: bool = True


@dataclass
class AnovaPCLowWater(AnovaModel):
    """The water level sensor."""

    empty: bool = False
    warning: bool = False


@dataclass
class AnovaPCProbe(AnovaModel):
    """The food probe."""

    connected: bool = False
    current: AnovaTemperature | None = None
    setpoint: AnovaTemperature | None = None


@dataclass
class AnovaPCNodes(AnovaModel):
    """Everything the cooker measures."""

    water_temperature_sensor: AnovaPCWaterSensor = wire("waterTemperatureSensor", factory=AnovaPCWaterSensor)
    timer: AnovaTimerNode = field(default_factory=AnovaTimerNode)
    low_water: AnovaPCLowWater = wire("lowWater", factory=AnovaPCLowWater)
    probe: AnovaPCProbe | None = None


@dataclass
class AnovaPCStatus(AnovaModel):
    """The cooker's mode (idle, cook, or an alarm) and display unit."""

    mode: str = "idle"
    temperature_unit: str = wire("temperatureUnit", "C")
    processed_command_ids: list[str] = wire("processedCommandIds", factory=list)
    resume_after_power_interruption: bool | None = wire("resumeAfterPowerInterruption")


@dataclass
class AnovaPCCook(AnovaCook):
    """The cooker's running cook."""

    stage_transition_pending_user_action: bool = wire("stageTransitionPendingUserAction", False)


@dataclass
class AnovaPCState(AnovaModel):
    """A third-generation Precision Cooker's whole state, as EVENT_APC_STATE carries it."""

    version: int | None = None
    updated_timestamp: str | None = wire("updatedTimestamp")
    status: AnovaPCStatus = wire("state", factory=AnovaPCStatus)
    nodes: AnovaPCNodes = field(default_factory=AnovaPCNodes)
    cook: AnovaPCCook | None = None
    system_info: AnovaSystemInfo = wire("systemInfo", factory=AnovaSystemInfo)

    @property
    def is_cooking(self) -> bool:
        """Whether a cook is running."""
        return self.status.mode == "cook"

    @property
    def is_low_water(self) -> bool:
        """Whether the water is too low to cook (the app's own test)."""
        return self.nodes.low_water.empty or self.status.mode == "lowWater"
