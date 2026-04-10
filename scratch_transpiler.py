import uuid
import json

class APONodes:
    def __init__(self):
        self.temperature_bulbs_mode = "dry"
        self.setpoint_dry_temp = 182.22223
        self.setpoint_wet_temp = 54.44
        self.top_heater_on = False
        self.bottom_heater_on = False
        self.rear_heater_on = True

class APOStage:
    def __init__(self, id):
        self.id = id
        self.sous_vide = False
        self.temperature = 182.22223
        self.steam = 0
        self.heating_elements = "rear"  # Will be mapped below
        self.fan = 100
        self.advance = "MANUALLY"

class APORecipe:
    def __init__(self, title, stages):
        self.title = title
        self.stages = stages

class APOCook:
    def __init__(self, cook_id, recipe, active_stage_index):
        self.cook_id = cook_id
        self.recipe = recipe
        self.active_stage_index = active_stage_index

def _generate_uuid():
    return str(uuid.uuid4())

def cook_to_payload(cook):
    stages = []
    
    for idx, stage in enumerate(cook.recipe.stages):
        if not stage.id:
            stage.id = _generate_uuid()
            
        target_temp = stage.temperature
            
        top_on = "top" in stage.heating_elements
        bottom_on = "bottom" in stage.heating_elements
        rear_on = "rear" in stage.heating_elements
        
        speed_int = stage.fan
        
        elements_dict = {
            "top": {"on": top_on},
            "bottom": {"on": bottom_on},
            "rear": {"on": rear_on}
        }
        
        mode = "wet" if stage.sous_vide else "dry"
        bulb_dict = {
            "mode": mode,
            mode: {
                "setpoint": {"celsius": target_temp}
            }
        }
        
        # We only care about V2 output for this test
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
            "entry": {"conditions": {"and": {}}}
        }
        
        if stage.steam > 0:
            s_dict["do"]["steamGenerators"] = {
                "mode": "relative-humidity",
                "relativeHumidity": {"setpoint": stage.steam}
            }
            
        if stage.advance != "MANUALLY" and hasattr(stage.advance, 'duration'):
            s_dict["do"]["timer"] = {
                "initial": getattr(stage.advance, 'duration', 0),
                "entry": {"conditions": {"and": {}}}
            }
            s_dict["exit"]["conditions"]["and"] = {"nodes.timer.mode": {"=": "completed"}}
            
        elif hasattr(stage.advance, 'target'):
            s_dict["do"]["probe"] = {
                "setpoint": {"celsius": getattr(stage.advance, 'target', 0)}
            }
            s_dict["exit"]["conditions"]["and"] = {"nodes.temperatureProbe.current.celsius": {">=": getattr(stage.advance, 'target', 0)}}
        else:
            s_dict["exit"]["conditions"]["and"] = {}
            
        if stage.sous_vide:
            stage_entry_cond = {"nodes.temperatureBulbs.wet.current.celsius": {">=": stage.temperature}}
        else:
            stage_entry_cond = {"nodes.temperatureBulbs.dry.current.celsius": {">=": stage.temperature}}
        s_dict["entry"]["conditions"]["and"] = stage_entry_cond
            
        stages.append(s_dict)
            
    inner_payload = {
        "cookId": cook.cook_id or _generate_uuid(),
        "cookerId": "Oven123",
        "stages": stages
    }
    
    inner_payload.update({
        "type": "oven",
        "originSource": "api",
        "cookableType": "manual",
        "cookableId": "",
        "title": cook.recipe.title,
        "rackPosition": 3
    })
        
    payload_dict = {
        "cookId": inner_payload["cookId"],
        "cookerId": "Oven123",
        "type": "oven",
        "originSource": "api",
        "cookableType": "manual",
        "stages": stages
    }
    
    return payload_dict

stage1 = APOStage(_generate_uuid())
recipe = APORecipe("Recovery", [stage1])
cook_obj = APOCook(_generate_uuid(), recipe, 0)
payload = cook_to_payload(cook_obj)

print("PAYLOAD DICT:")
print(json.dumps(payload, indent=2))
