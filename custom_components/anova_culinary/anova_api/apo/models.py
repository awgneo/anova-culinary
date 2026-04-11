"""APO detailed data models for the Anova API."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from mashumaro.mixins.dict import DataClassDictMixin
from mashumaro import field_options

class AnovaPOHeatingElement(str, Enum):
    """Enumeration of valid heating element combinations."""
    TOP = "top"
    REAR = "rear"
    BOTTOM = "bottom"
    TOP_REAR = "top+rear"
    BOTTOM_REAR = "bottom+rear"
    TOP_BOTTOM = "top+bottom"

class AnovaPOFanSpeed(str, Enum):
    """Enumeration of valid fan speeds."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    OFF = "off"

class AnovaPOTimerTrigger(str, Enum):
    """Enumeration of valid timer starts."""
    FOOD_DETECTED = "food_detected"
    IMMEDIATELY = "immediately"
    PREHEATED = "preheated"
    MANUALLY = "manually"

@dataclass
class AnovaPOProbe:
    """Universal schema for a stage's probe transition constraint."""
    target: float

@dataclass
class AnovaPOTimer:
    """Universal schema for a stage's timer transition constraint."""
    duration: int
    trigger: AnovaPOTimerTrigger

@dataclass
class AnovaPOStage(DataClassDictMixin):
    """Universal schema representing a single state of cooking intent."""
    id: str = ""
    sous_vide: bool = False
    temperature: float = 0.0
    temperature_unit: str = "C"
    steam: int = 0
    heating_elements: AnovaPOHeatingElement = AnovaPOHeatingElement.REAR
    fan: AnovaPOFanSpeed = AnovaPOFanSpeed.HIGH
    advance: Optional[Union[AnovaPOTimer, AnovaPOProbe]] = None

@dataclass
class AnovaPORecipe(DataClassDictMixin):
    """Static storage entity representing an array of intended stages."""
    id: str = ""
    title: str = field(default="", metadata=field_options(alias="name"))
    stages: List[AnovaPOStage] = field(default_factory=list)
    class Config:
        serialize_by_alias = True

@dataclass
class AnovaPOCook:
    """Live runtime state packaging a currently executing APORecipe."""
    recipe: AnovaPORecipe = field(default_factory=AnovaPORecipe)
    cook_id: str = ""
    active_stage_index: int = 0
    active_stage_id: str = ""

    @property
    def current_stage(self) -> Optional[AnovaPOStage]:
        """Convenience property to fetch the active stage using the index."""
        if 0 <= self.active_stage_index < len(self.recipe.stages):
            return self.recipe.stages[self.active_stage_index]
        return None

@dataclass
class AnovaPONodes:
    """The physical reality of the oven hardware right now."""
    # Temperatures
    current_dry_temp: float = 0.0
    current_wet_temp: float = 0.0
    current_probe_temp: float = 0.0
    setpoint_wet_temp: float = 0.0
    setpoint_dry_temp: float = 0.0
    current_dry_bottom_temp: float = 0.0
    current_dry_top_temp: float = 0.0
    display_board_celsius: float = 0.0
    temperature_bulbs_mode: str = "dry"
    
    # Internal Thermistor Connections & Faults
    wet_bulb_overcurrents: int = 0
    wet_bulb_dc12v: str = "no-error"
    wet_bulb_ntc_connected: bool = True
    wet_bulb_dosed: bool = False
    dry_bottom_overcurrents: int = 0
    dry_bottom_ntc_connected: bool = True
    dry_top_overcurrents: int = 0
    dry_top_ntc_connected: bool = True
    dry_bulb_overcurrents: int = 0
    
    # Probe
    probe_connected: bool = False
    probe_ntc_connected: bool = True
    
    # Steam
    boiler_celsius: float = 0.0
    boiler_watts: int = 0
    boiler_descale_required: bool = False
    boiler_outlet_valve_overcurrents: int = 0
    boiler_inlet_pump_overcurrents: int = 0
    boiler_ntc_connected: bool = True
    boiler_dc12v_inlet_pump: str = "no-error"
    boiler_failed: bool = False
    boiler_dosed: bool = False
    boiler_dc12v_outlet_valve: str = "no-error"
    boiler_usage_hours: float = 0.0
    evaporator_celsius: float = 0.0
    evaporator_watts: int = 0
    evaporator_failed: bool = False
    evaporator_usage_hours: float = 0.0
    evaporator_ntc_connected: bool = True
    relative_humidity_current: float = 0.0
    relative_humidity_setpoint: float = 0.0
    steam_generators_mode: str = "relative-humidity"
    
    # Hardware Tanks
    water_tank_removed: bool = False
    water_tank_empty: bool = False
    water_tank_low: bool = False
    waste_water_tank_full: bool = False
    waste_water_tank_removed: bool = False
    
    # Heaters
    rear_heater_watts: int = 0
    rear_heater_on: bool = False
    rear_heater_failed: bool = False
    rear_heater_usage_hours: float = 0.0
    bottom_heater_watts: int = 0
    bottom_heater_on: bool = False
    bottom_heater_failed: bool = False
    bottom_heater_usage_hours: float = 0.0
    top_heater_watts: int = 0
    top_heater_on: bool = False
    top_heater_failed: bool = False
    top_heater_usage_hours: float = 0.0
    
    # Fans
    exhaust_fan_speed: str = "off"
    exhaust_fan_dc12v: str = "no-error"
    exhaust_fan_overcurrents: int = 0
    display_fan_speed: str = "off"
    display_fan_dc12v: str = "no-error"
    display_fan_overcurrents: int = 0
    convection_fan_speed: str = "off"
    convection_fan_failed: bool = False
    led_fan_speed: str = "off"
    led_fan_dc12v: str = "no-error"
    led_fan_overcurrents: int = 0
    power_board_fan_on: bool = False
    power_board_fan_dc12v: str = "no-error"
    power_board_fan_overcurrents: int = 0
    
    # System Telemetry
    dc12v_faults: int = 0
    dc12v_rejections: int = 0
    exhaust_vent_state: str = "closed"
    exhaust_vent_dc12v: str = "no-error"
    exhaust_vent_overcurrents: int = 0
    
    # Logic & State
    timer_initial: int = 0
    timer_mode: str = "idle"
    door_closed: bool = True
    door_lamp_on: bool = False
    door_lamp_preferences: str = "on"
    cavity_lamp_on: bool = False
    
    # Optional Camera
    cavity_camera_is_empty: bool = True
    cavity_camera_streaming: bool = False
    cavity_camera_detection: str = ""
    cavity_camera_last_detection_millis: int = 0
    cavity_camera_enabled: bool = True

@dataclass
class AnovaPOState:
    """Current state of a Precision Oven."""
    is_running: bool = False
    state: str = "idle"
    nodes: AnovaPONodes = field(default_factory=AnovaPONodes)
    cook: Optional[AnovaPOCook] = None
    
    # Track the raw telemetry payload only for pure debugging if necessary.
    raw_state: Dict[str, Any] = field(default_factory=dict)
