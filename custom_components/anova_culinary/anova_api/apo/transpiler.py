"""Bidirectional Transpiler Engine for Anova Precision Ovens."""

import uuid
import copy
from typing import Dict, Any, List, Optional

from .models import (
    APOCook, APORecipe, APOStage, APOTimer, APOTimerTrigger,
    APOProbe, APOHeatingElement, APOFanSpeed, APONodes, APOState
)
from ..device import AnovaDevice

def _generate_uuid() -> str:
    """Generate a UUID string disguised as an android app structure."""
    return f"android-{uuid.uuid4()}"

def recipe_to_cook(recipe: APORecipe) -> APOCook:
    """Bootstraps a fresh APOCook runtime proxy from a static Recipe."""
    cloned = copy.deepcopy(recipe)
    for stage in cloned.stages:
        if not stage.id:
            stage.id = _generate_uuid()
            
    return APOCook(
        recipe=cloned,
        cook_id=_generate_uuid(),
        active_stage_index=0,
        active_stage_id=cloned.stages[0].id if cloned.stages else ""
    )

def cook_to_payload(cook: APOCook, device: AnovaDevice) -> dict:
    """Forward Transpiler. Converts APOCook to the CMD_APO_START payload."""
    stages = []
    
    for stage in cook.recipe.stages:
        if not stage.id:
            stage.id = _generate_uuid()
            
        # Clamp temperature constraints based on model and elements
        target_temp = stage.temperature
        if device.model in ("oven", "oven_v2") and stage.heating_elements == APOHeatingElement.BOTTOM and target_temp > 230.0:
            target_temp = 230.0 # 446F Limit
        elif device.model not in ("oven", "oven_v2") and stage.heating_elements == APOHeatingElement.BOTTOM and target_temp > 180.0:
            target_temp = 180.0 # 356F Limit
            
        top_on = "top" in stage.heating_elements.value
        bottom_on = "bottom" in stage.heating_elements.value
        rear_on = "rear" in stage.heating_elements.value
        
        fan_speeds = {APOFanSpeed.HIGH: 100, APOFanSpeed.MEDIUM: 50, APOFanSpeed.LOW: 25, APOFanSpeed.OFF: 0}
        speed_int = fan_speeds.get(stage.fan, 100)
        
        elements_dict = {
            "top": {"on": top_on},
            "bottom": {"on": bottom_on},
            "rear": {"on": rear_on}
        }
        
        mode = "wet" if stage.sous_vide else "dry"
        bulb_dict = {
            "mode": mode,
            mode: {"setpoint": {"celsius": target_temp}}
        }
        
        if device.model in ("oven", "oven_v2"):
            # v2 oven schema
            s_dict = {
                "id": stage.id,
                "title": "",
                "do": {
                    "type": "cook",
                    "fan": {"speed": speed_int},
                    "heatingElements": elements_dict,
                    "exhaustVent": {"state": "closed"},
                    "temperatureBulbs": bulb_dict,
                },
                "exit": {"conditions": {"and": {}}},
                "entry": {"conditions": {"and": {f"nodes.temperatureBulbs.{mode}.current.celsius": {">=": target_temp}}}}
            }
            
            if stage.steam > 0:
                s_dict["do"]["steamGenerators"] = {
                    "mode": "relative-humidity",
                    "relativeHumidity": {"setpoint": stage.steam}
                }
                
            if isinstance(stage.advance, APOTimer):
                trigger_cond = None
                if stage.advance.trigger == APOTimerTrigger.PREHEATED:
                    trigger_cond = {"and": {f"nodes.temperatureBulbs.{mode}.current.celsius": {">=": target_temp}}}
                elif stage.advance.trigger == APOTimerTrigger.MANUALLY:
                    trigger_cond = {"and": {"userAction": {"=": True}}}
                elif stage.advance.trigger == APOTimerTrigger.FOOD_DETECTED:
                    trigger_cond = {"or": {"userAction": {"=": True}, "nodes.cavityCamera.isEmpty": {"=": False}}}
                
                # If 'Immediately', the user intends to skip preheat and lock entirely. 
                # Pop the primary entry lock for the stage so it bypasses preheat gating.
                if stage.advance.trigger == APOTimerTrigger.IMMEDIATELY and "entry" in s_dict:
                    s_dict.pop("entry")
                
                s_dict["do"]["timer"] = {
                    "initial": stage.advance.duration
                }
                if trigger_cond is not None:
                    s_dict["do"]["timer"]["entry"] = {"conditions": trigger_cond}
                    
                s_dict["exit"]["conditions"]["and"] = {"nodes.timer.mode": {"=": "completed"}}
                
            elif isinstance(stage.advance, APOProbe):
                s_dict["do"]["temperatureProbe"] = {
                    "setpoint": {"celsius": stage.advance.target}
                }
                s_dict["exit"]["conditions"]["and"] = {"nodes.temperatureProbe.current.celsius": {">=": stage.advance.target}}
                s_dict["entry"]["conditions"]["and"]["nodes.temperatureProbe.connected"] = {"=": True}
            else:
                s_dict["exit"]["conditions"]["and"] = {}
                
            stages.append(s_dict)
            
        else:
            # v1 oven schema
            s_dict = {
                "id": stage.id,
                "stepType": "stage",
                "type": "cook",
                "title": "",
                "description": "",
                "userActionRequired": False,
                "fan": {"speed": speed_int},
                "heatingElements": elements_dict,
                "vent": {"open": False},
                "temperatureBulbs": bulb_dict,
                "stageTransitionType": "automatic",
                "rackPosition": 3
            }
            if stage.steam > 0:
                s_dict["steamGenerators"] = {
                    "mode": "relative-humidity",
                    "relativeHumidity": {"setpoint": stage.steam}
                }
            
            if isinstance(stage.advance, APOTimer):
                trigger_map = {
                    APOTimerTrigger.FOOD_DETECTED: "on-detection",
                    APOTimerTrigger.IMMEDIATELY: "immediately",
                    APOTimerTrigger.PREHEATED: "when-preheated",
                    APOTimerTrigger.MANUALLY: "manual"
                }
                s_dict["timer"] = {
                    "initial": stage.advance.duration,
                    "startType": trigger_map.get(stage.advance.trigger, "immediately")
                }
            elif isinstance(stage.advance, APOProbe):
                s_dict["probe"] = {
                    "setpoint": {"celsius": stage.advance.target}
                }
                
            stages.append(s_dict)
            
    # Wrap in payload
    inner_payload = {
        "cookId": cook.cook_id or _generate_uuid(),
        "cookerId": device.device_id,
        "stages": stages
    }
    
    if device.model in ("oven", "oven_v2"):
        inner_payload.update({
            "type": device.model,
            "originSource": "android",
            "cookableType": "manual",
            "cookableId": "",
            "title": cook.recipe.title,
            "rackPosition": 3
        })
        
    return inner_payload

def payload_to_state(raw_payload: dict) -> APOState:
    """Parses raw websocket telemetry into a pristine APOState."""
    inner = raw_payload
    if "nodes" not in inner:
        if isinstance(inner.get("state"), dict) and "nodes" in inner["state"]:
            inner = inner["state"]
        elif isinstance(inner.get("payload"), dict) and "nodes" in inner["payload"]:
            inner = inner["payload"]
            
    nodes = APONodes()
    if "nodes" in inner:
        n = inner["nodes"]
        bulbs = n.get("temperatureBulbs", {})
        nodes.current_dry_temp = bulbs.get("dry", {}).get("current", {}).get("celsius", 0.0)
        nodes.current_wet_temp = bulbs.get("wet", {}).get("current", {}).get("celsius", 0.0)
        nodes.setpoint_wet_temp = bulbs.get("wet", {}).get("setpoint", {}).get("celsius", 0.0)
        nodes.setpoint_dry_temp = bulbs.get("dry", {}).get("setpoint", {}).get("celsius", 0.0)
        nodes.current_dry_bottom_temp = bulbs.get("dryBottom", {}).get("current", {}).get("celsius", 0.0)
        nodes.current_dry_top_temp = bulbs.get("dryTop", {}).get("current", {}).get("celsius", 0.0)
        
        nodes.temperature_bulbs_mode = bulbs.get("mode", "dry")
        nodes.wet_bulb_overcurrents = bulbs.get("wet", {}).get("numberOfOverCurrent", 0)
        nodes.wet_bulb_dc12v = bulbs.get("wet", {}).get("dc12VInletStatus", "no-error")
        nodes.wet_bulb_ntc_connected = bulbs.get("wet", {}).get("ntcConnected", True)
        nodes.wet_bulb_dosed = bulbs.get("wet", {}).get("dosed", False)
        nodes.dry_bottom_overcurrents = bulbs.get("dryBottom", {}).get("numberOfOverCurrent", 0)
        nodes.dry_bottom_ntc_connected = bulbs.get("dryBottom", {}).get("ntcConnected", True)
        nodes.dry_top_overcurrents = bulbs.get("dryTop", {}).get("numberOfOverCurrent", 0)
        nodes.dry_top_ntc_connected = bulbs.get("dryTop", {}).get("ntcConnected", True)
        nodes.dry_bulb_overcurrents = bulbs.get("dry", {}).get("numberOfOverCurrent", 0)
        
        probe = n.get("temperatureProbe", {})
        nodes.probe_connected = probe.get("connected", False)
        nodes.probe_ntc_connected = probe.get("ntcConnected", True)
        nodes.current_probe_temp = probe.get("current", {}).get("celsius", 0.0)
        if nodes.current_probe_temp == 0.0:
            # Fallback for some weird v1/v2 combinations where it passes via probe root
            nodes.current_probe_temp = n.get("probe", {}).get("current", {}).get("celsius", 0.0)
            
        steam = n.get("steamGenerators", {})
        boiler = steam.get("boiler", {})
        evap = steam.get("evaporator", {})
        nodes.boiler_celsius = boiler.get("celsius", 0.0)
        nodes.boiler_watts = boiler.get("watts", 0)
        nodes.boiler_descale_required = boiler.get("descaleRequired", False)
        nodes.boiler_outlet_valve_overcurrents = boiler.get("numberOfOverCurrentOutletValveDescale", 0)
        nodes.boiler_inlet_pump_overcurrents = boiler.get("numberOfOverCurrentInletPump", 0)
        nodes.boiler_ntc_connected = boiler.get("ntcConnected", True)
        nodes.boiler_dc12v_inlet_pump = boiler.get("dc12VInletPumpStatus", "no-error")
        nodes.boiler_failed = boiler.get("failed", False)
        nodes.boiler_dosed = boiler.get("dosed", False)
        nodes.boiler_dc12v_outlet_valve = boiler.get("dc12VOutletValveDescaleStatus", "no-error")
        nodes.boiler_usage_hours = boiler.get("usageHours", 0.0)
        
        nodes.evaporator_celsius = evap.get("celsius", 0.0)
        nodes.evaporator_watts = evap.get("watts", 0)
        nodes.evaporator_failed = evap.get("failed", False)
        nodes.evaporator_usage_hours = evap.get("usageHours", 0.0)
        nodes.evaporator_ntc_connected = evap.get("ntcConnected", True)
        
        nodes.relative_humidity_current = steam.get("relativeHumidity", {}).get("current", 0.0)
        nodes.relative_humidity_setpoint = steam.get("relativeHumidity", {}).get("setpoint", 0.0)
        nodes.steam_generators_mode = steam.get("mode", "relative-humidity")

        tanks = n.get("wasteWaterTank", {})
        nodes.waste_water_tank_full = tanks.get("full", False)
        nodes.waste_water_tank_removed = tanks.get("removed", False)
        water = n.get("waterTank", {})
        nodes.water_tank_removed = water.get("removed", False)
        nodes.water_tank_empty = water.get("empty", False)
        nodes.water_tank_low = water.get("low", False)
        
        heaters = n.get("heatingElements", {})
        nodes.rear_heater_watts = heaters.get("rear", {}).get("watts", 0)
        nodes.rear_heater_on = heaters.get("rear", {}).get("on", False)
        nodes.rear_heater_failed = heaters.get("rear", {}).get("failed", False)
        nodes.rear_heater_usage_hours = heaters.get("rear", {}).get("usageHours", 0.0)
        nodes.bottom_heater_watts = heaters.get("bottom", {}).get("watts", 0)
        nodes.bottom_heater_on = heaters.get("bottom", {}).get("on", False)
        nodes.bottom_heater_failed = heaters.get("bottom", {}).get("failed", False)
        nodes.bottom_heater_usage_hours = heaters.get("bottom", {}).get("usageHours", 0.0)
        nodes.top_heater_watts = heaters.get("top", {}).get("watts", 0)
        nodes.top_heater_on = heaters.get("top", {}).get("on", False)
        nodes.top_heater_failed = heaters.get("top", {}).get("failed", False)
        nodes.top_heater_usage_hours = heaters.get("top", {}).get("usageHours", 0.0)
        
        nodes.exhaust_fan_speed = n.get("exhaustFan", {}).get("speed", "off")
        nodes.exhaust_fan_dc12v = n.get("exhaustFan", {}).get("dc12VStatus", "no-error")
        nodes.exhaust_fan_overcurrents = n.get("exhaustFan", {}).get("numberOfOverCurrent", 0)
        
        nodes.display_fan_speed = n.get("displayFan", {}).get("speed", "off")
        nodes.display_fan_dc12v = n.get("displayFan", {}).get("dc12VStatus", "no-error")
        nodes.display_fan_overcurrents = n.get("displayFan", {}).get("numberOfOverCurrent", 0)
        
        nodes.convection_fan_speed = n.get("fan", {}).get("speed", "off")
        nodes.convection_fan_failed = n.get("fan", {}).get("failed", False)
        
        nodes.led_fan_speed = n.get("ledFan", {}).get("speed", "off")
        nodes.led_fan_dc12v = n.get("ledFan", {}).get("dc12VStatus", "no-error")
        nodes.led_fan_overcurrents = n.get("ledFan", {}).get("numberOfOverCurrent", 0)
        
        nodes.power_board_fan_on = n.get("powerBoardFan", {}).get("on", False)
        nodes.power_board_fan_dc12v = n.get("powerBoardFan", {}).get("dc12VStatus", "no-error")
        nodes.power_board_fan_overcurrents = n.get("powerBoardFan", {}).get("numberOfOverCurrent", 0)
        
        nodes.dc12v_faults = n.get("dc12VLine", {}).get("numberOfFaults", 0)
        nodes.dc12v_rejections = n.get("dc12VLine", {}).get("numberOfRejections", 0)
        
        nodes.exhaust_vent_state = n.get("exhaustVent", {}).get("state", "closed")
        nodes.exhaust_vent_dc12v = n.get("exhaustVent", {}).get("dc12VStatus", "no-error")
        nodes.exhaust_vent_overcurrents = n.get("exhaustVent", {}).get("numberOfOverCurrent", 0)
        
        timer = n.get("timer", {})
        nodes.timer_initial = timer.get("initial", 0)
        nodes.timer_mode = timer.get("mode", "idle")
        
        display_board = n.get("displayBoard", {})
        nodes.display_board_celsius = display_board.get("celsius", 0.0)
        
        nodes.door_closed = n.get("door", {}).get("closed", True)
        nodes.door_lamp_on = n.get("doorLamp", {}).get("on", False)
        nodes.door_lamp_preferences = n.get("doorLamp", {}).get("preferences", "on")
        nodes.cavity_lamp_on = n.get("cavityLamp", {}).get("on", False)
        
        cam = n.get("cavityCamera", {})
        nodes.cavity_camera_is_empty = cam.get("isEmpty", True)
        nodes.cavity_camera_streaming = cam.get("streaming", False)
        nodes.cavity_camera_detection = cam.get("detection", "")
        nodes.cavity_camera_last_detection_millis = cam.get("lastDetectionMillis", 0)
        nodes.cavity_camera_enabled = cam.get("enabled", True)
        
        nodes.display_board_celsius = n.get("displayBoard", {}).get("celsius", 0.0)
    else:
        # v1 fallback
        bulbs = raw_payload.get("temperatureBulbs", {})
        if not bulbs and "payload" in raw_payload:
            bulbs = raw_payload["payload"].get("temperatureBulbs", {})
            
        nodes.current_dry_temp = bulbs.get("dry", {}).get("current", {}).get("celsius", 0.0)
        nodes.current_wet_temp = bulbs.get("wet", {}).get("current", {}).get("celsius", 0.0)

    cook = None
    try:
        cook = payload_cook_to_cook(inner)
    except Exception:
        pass
        
    status = inner.get("status")
    if status is None:
        state_block = inner.get("state")
        if isinstance(state_block, dict):
            status = state_block.get("mode")
        else:
            status = state_block

    is_running = False
    if status is not None:
        state_str = str(status)
        is_running = state_str.lower() not in ["idle", "stopped", "standby"]
    else:
        state_str = "idle"
        is_running = bool(inner.get("activeStageId"))
        
    return APOState(
        is_running=is_running,
        state=state_str,
        nodes=nodes,
        cook=cook,
        raw_state=raw_payload
    )

def payload_cook_to_cook(raw_payload: dict) -> APOCook:
    """Reverse Transpiler. Converts payload telemetry to APOCook."""
    cook_dict = raw_payload.get("cook", raw_payload)
    if "stages" not in cook_dict and "payload" in raw_payload:
        cook_dict = raw_payload["payload"]
        
    stages_raw = cook_dict.get("stages", [])
    cook_id = cook_dict.get("cookId", "")
    active_stage_id = cook_dict.get("activeStageId", "")
    
    universal_stages = []
    
    for raw_stage in stages_raw:
        s = APOStage()
        s.id = raw_stage.get("id", _generate_uuid())
        
        # Try extracting from v2 'do' envelope first
        block = raw_stage.get("do", raw_stage)
        
        # Sous Vide
        sv_mode = block.get("temperatureBulbs", {}).get("mode", "dry")
        s.sous_vide = (sv_mode == "wet")
        
        # Temperature
        temp_dict = block.get("temperatureBulbs", {}).get(sv_mode, {})
        s.temperature = temp_dict.get("setpoint", {}).get("celsius", 0.0)
        
        # Steam
        if s.sous_vide:
            s.steam = 100
        else:
            s.steam = block.get("steamGenerators", {}).get("relativeHumidity", {}).get("setpoint", 0)
            
        # Heating Elements
        els = block.get("heatingElements", {})
        top = els.get("top", {}).get("on", False)
        bottom = els.get("bottom", {}).get("on", False)
        rear = els.get("rear", {}).get("on", False)
        
        if top and bottom:
            s.heating_elements = APOHeatingElement.TOP_BOTTOM
        elif top and rear:
            s.heating_elements = APOHeatingElement.TOP_REAR
        elif bottom and rear:
            s.heating_elements = APOHeatingElement.BOTTOM_REAR
        elif top:
            s.heating_elements = APOHeatingElement.TOP
        elif bottom:
            s.heating_elements = APOHeatingElement.BOTTOM
        else:
            s.heating_elements = APOHeatingElement.REAR
            
        # Fan
        fan_speed = block.get("fan", {}).get("speed", 100)
        if str(fan_speed).isdigit():
            fan_speed = int(fan_speed)
        else:
            # Sometime payload uses strings like 'max' for telemetry, but stages uses ints usually
            fan_speed = 100

        if fan_speed >= 100:
            s.fan = APOFanSpeed.HIGH
        elif fan_speed >= 50:
            s.fan = APOFanSpeed.MEDIUM
        elif fan_speed > 0:
            s.fan = APOFanSpeed.LOW
        else:
            s.fan = APOFanSpeed.OFF
            
        # Advance (Timer or Probe)
        timer = block.get("timer", {})
        probe = block.get("temperatureProbe", block.get("probe", {}))
        
        if probe and "setpoint" in probe:
            targ = probe.get("setpoint", {}).get("celsius", 55.0)
            s.advance = APOProbe(target=targ)
        elif timer:
            # Check v2 triggers
            conds = timer.get("entry", {}).get("conditions", {})
            dur = timer.get("initial", 0)
            
            if "startType" in timer:
                # v1 trigger map
                t_str = timer["startType"]
                if t_str == "on-detection": trigger = APOTimerTrigger.FOOD_DETECTED
                elif t_str == "when-preheated": trigger = APOTimerTrigger.PREHEATED
                elif t_str == "manual": trigger = APOTimerTrigger.MANUALLY
                else: trigger = APOTimerTrigger.IMMEDIATELY
            elif not conds or conds == {"and": {}}:
                trigger = APOTimerTrigger.IMMEDIATELY
            elif "or" in conds and "nodes.cavityCamera.isEmpty" in conds["or"]:
                trigger = APOTimerTrigger.FOOD_DETECTED
            elif "and" in conds and any("nodes.temperatureBulbs" in k for k in conds["and"]):
                trigger = APOTimerTrigger.PREHEATED
            else:
                trigger = APOTimerTrigger.MANUALLY
                
            s.advance = APOTimer(duration=dur, trigger=trigger)

        universal_stages.append(s)

    # Determine active index
    idx = 0
    for i, stg in enumerate(universal_stages):
        if stg.id == active_stage_id:
            idx = i
            break

    recipe = APORecipe(
        title=cook_dict.get("cookTitle", cook_dict.get("title", "")),
        stages=universal_stages
    )
    return APOCook(
        recipe=recipe,
        cook_id=cook_id,
        active_stage_index=idx,
        active_stage_id=active_stage_id
    )