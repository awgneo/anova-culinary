"""The Precision Oven 2.0 state (EVENT_APO_STATE), typed after the apps' OvenStateV2 schema.

Nodes the schema splits by mode (temperature bulbs, steam generators, the probe) are one
class each holding every mode's fields. PROTOCOL.md (part 2, §2.1 and appendix) has the
full tree.
"""

from dataclasses import dataclass, field

from ..models import AnovaCook, AnovaModel, AnovaSystemInfo, AnovaTemperature, AnovaTimerNode, wire


@dataclass
class AnovaPOBulb(AnovaModel):
    """One temperature bulb (dry, wet, dryTop, dryBottom)."""

    current: AnovaTemperature = field(default_factory=AnovaTemperature)
    setpoint: AnovaTemperature | None = None
    ntc_connected: bool | None = wire("ntcConnected")
    dosed: bool | None = None
    overcurrents: int | None = wire("numberOfOverCurrent")
    dc12v_inlet_status: str | None = wire("dc12VInletStatus")


@dataclass
class AnovaPOBulbs(AnovaModel):
    """The cavity temperature bulbs; `mode` is the one the oven regulates (dry or wet)."""

    mode: str = "dry"
    dry: AnovaPOBulb = field(default_factory=AnovaPOBulb)
    wet: AnovaPOBulb = field(default_factory=AnovaPOBulb)
    dry_top: AnovaPOBulb = wire("dryTop", factory=AnovaPOBulb)
    dry_bottom: AnovaPOBulb = wire("dryBottom", factory=AnovaPOBulb)

    @property
    def active(self) -> AnovaPOBulb:
        """The bulb the oven regulates."""
        return self.wet if self.mode == "wet" else self.dry


@dataclass
class AnovaPOHumidity(AnovaModel):
    """A steam generator reading and its target (relative humidity or steam percentage)."""

    current: float | None = None
    setpoint: float | None = None


@dataclass
class AnovaPOBoiler(AnovaModel):
    """The steam boiler."""

    celsius: float | None = None
    watts: int | None = None
    failed: bool | None = None
    dosed: bool | None = None
    descale_required: bool = wire("descaleRequired", False)
    usage_hours: float | None = wire("usageHours")
    ntc_connected: bool | None = wire("ntcConnected")


@dataclass
class AnovaPOEvaporator(AnovaModel):
    """The steam evaporator."""

    celsius: float | None = None
    watts: int | None = None
    failed: bool | None = None
    usage_hours: float | None = wire("usageHours")
    ntc_connected: bool | None = wire("ntcConnected")


@dataclass
class AnovaPOSteamGenerators(AnovaModel):
    """Steam: `mode` is idle, relative-humidity or steam-percentage."""

    mode: str = "idle"
    relative_humidity: AnovaPOHumidity | None = wire("relativeHumidity")
    steam_percentage: AnovaPOHumidity | None = wire("steamPercentage")
    boiler: AnovaPOBoiler = field(default_factory=AnovaPOBoiler)
    evaporator: AnovaPOEvaporator = field(default_factory=AnovaPOEvaporator)

    @property
    def active(self) -> AnovaPOHumidity | None:
        """The reading for the current mode (none while idle)."""
        if self.mode == "relative-humidity":
            return self.relative_humidity
        if self.mode == "steam-percentage":
            return self.steam_percentage
        return None


@dataclass
class AnovaPOProbeNode(AnovaModel):
    """The food probe; `current` only while connected."""

    connected: bool = False
    current: AnovaTemperature | None = None
    setpoint: AnovaTemperature | None = None


@dataclass
class AnovaPOHeatingElementNode(AnovaModel):
    """One heating element."""

    on: bool = False
    failed: bool = False
    watts: int | None = None
    usage_hours: float | None = wire("usageHours")


@dataclass
class AnovaPOHeatingElementsNode(AnovaModel):
    """The top, bottom and rear elements."""

    top: AnovaPOHeatingElementNode = field(default_factory=AnovaPOHeatingElementNode)
    bottom: AnovaPOHeatingElementNode = field(default_factory=AnovaPOHeatingElementNode)
    rear: AnovaPOHeatingElementNode = field(default_factory=AnovaPOHeatingElementNode)


@dataclass
class AnovaPOFanNode(AnovaModel):
    """A fan; `speed` is a word (off, min, mid, max) in state, unlike the numbers stages carry."""

    speed: str | None = None
    on: bool | None = None
    failed: bool | None = None
    dc12v_status: str | None = wire("dc12VStatus")
    overcurrents: int | None = wire("numberOfOverCurrent")


@dataclass
class AnovaPOVent(AnovaModel):
    """The exhaust vent: closed, open-mid or open-max."""

    state: str = "closed"
    dc12v_status: str | None = wire("dc12VStatus")
    overcurrents: int | None = wire("numberOfOverCurrent")


@dataclass
class AnovaPOWaterTank(AnovaModel):
    """The water tank."""

    empty: bool = False
    low: bool = False
    removed: bool = False


@dataclass
class AnovaPOWasteWaterTank(AnovaModel):
    """The waste water tank."""

    full: bool = False
    removed: bool = False


@dataclass
class AnovaPOLamp(AnovaModel):
    """A lamp; the door lamp also carries its on-during-cook preference."""

    on: bool = False
    failed: bool | None = None
    preferences: str | None = None


@dataclass
class AnovaPODoor(AnovaModel):
    """The door."""

    closed: bool = True


@dataclass
class AnovaPOCameraDetection(AnovaModel):
    """One thing the cavity camera recognised."""

    type: str | None = None
    category_id: str | None = wire("categoryId")
    confidence: float | None = None


@dataclass
class AnovaPOCamera(AnovaModel):
    """The cavity camera."""

    enabled: bool = False
    is_empty: bool = wire("isEmpty", True)
    streaming: bool = False
    detection: list[AnovaPOCameraDetection] = field(default_factory=list)


@dataclass
class AnovaPODisplayBoard(AnovaModel):
    """The display board."""

    celsius: float | None = None


@dataclass
class AnovaPONodes(AnovaModel):
    """Everything the oven measures and drives."""

    temperature_bulbs: AnovaPOBulbs = wire("temperatureBulbs", factory=AnovaPOBulbs)
    temperature_probe: AnovaPOProbeNode = wire("temperatureProbe", factory=AnovaPOProbeNode)
    steam_generators: AnovaPOSteamGenerators = wire("steamGenerators", factory=AnovaPOSteamGenerators)
    heating_elements: AnovaPOHeatingElementsNode = wire("heatingElements", factory=AnovaPOHeatingElementsNode)
    fan: AnovaPOFanNode = field(default_factory=AnovaPOFanNode)
    exhaust_fan: AnovaPOFanNode = wire("exhaustFan", factory=AnovaPOFanNode)
    display_fan: AnovaPOFanNode = wire("displayFan", factory=AnovaPOFanNode)
    led_fan: AnovaPOFanNode = wire("ledFan", factory=AnovaPOFanNode)
    power_board_fan: AnovaPOFanNode = wire("powerBoardFan", factory=AnovaPOFanNode)
    exhaust_vent: AnovaPOVent = wire("exhaustVent", factory=AnovaPOVent)
    timer: AnovaTimerNode = field(default_factory=AnovaTimerNode)
    water_tank: AnovaPOWaterTank = wire("waterTank", factory=AnovaPOWaterTank)
    waste_water_tank: AnovaPOWasteWaterTank = wire("wasteWaterTank", factory=AnovaPOWasteWaterTank)
    door: AnovaPODoor = field(default_factory=AnovaPODoor)
    door_lamp: AnovaPOLamp = wire("doorLamp", factory=AnovaPOLamp)
    cavity_lamp: AnovaPOLamp = wire("cavityLamp", factory=AnovaPOLamp)
    cavity_camera: AnovaPOCamera = wire("cavityCamera", factory=AnovaPOCamera)
    display_board: AnovaPODisplayBoard = wire("displayBoard", factory=AnovaPODisplayBoard)


@dataclass
class AnovaPOStatus(AnovaModel):
    """The oven's mode (idle, cook, descale) and display unit."""

    mode: str = "idle"
    temperature_unit: str = wire("temperatureUnit", "C")
    cavity_overheated: bool = wire("cavityOverheated", False)
    processed_command_ids: list[str] = wire("processedCommandIds", factory=list)


@dataclass
class AnovaPOCook(AnovaCook):
    """The oven's running cook."""

    cook_title: str | None = wire("cookTitle")
    title: str | None = None


@dataclass
class AnovaPOState(AnovaModel):
    """A Precision Oven 2.0's whole state, as EVENT_APO_STATE carries it."""

    version: int | None = None
    updated_timestamp: str | None = wire("updatedTimestamp")
    status: AnovaPOStatus = wire("state", factory=AnovaPOStatus)
    nodes: AnovaPONodes = field(default_factory=AnovaPONodes)
    cook: AnovaPOCook | None = None
    system_info: AnovaSystemInfo = wire("systemInfo", factory=AnovaSystemInfo)

    @property
    def is_cooking(self) -> bool:
        """Whether a cook is running."""
        return self.status.mode == "cook" and self.cook is not None
