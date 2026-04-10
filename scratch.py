import json
from custom_components.anova_culinary.anova_api.apo.transpiler import payload_cook_to_cook
from custom_components.anova_culinary.anova_api.apo.models import APOTimer

log_payload = {
    "cook": {
        "activeStageStartedTimestamp": "2026-04-10T10:40:38Z", 
        "stages": [{
            "do": {
                "exhaustVent": {"state": "closed"}, 
                "type": "cook", 
                "temperatureBulbs": {"dry": {"setpoint": {"celsius": 146.66667}}, "mode": "dry"}, 
                "heatingElements": {"rear": {"on": True}, "top": {"on": False}, "bottom": {"on": False}}, 
                "fan": {"speed": 100}, 
                "timer": {
                    "entry": {"conditions": {"or": {"nodes.cavityCamera.isEmpty": {"=": False}}}}, 
                    "initial": 300
                }
            }, 
            "title": "", 
            "id": "android-42c63d0c-ca65-492a-9f81-d9fa2fe95b91", 
            "exit": {"conditions": {"and": {"nodes.timer.mode": {"=": "completed"}}}}, 
            "entry": {"conditions": {"and": {"nodes.temperatureBulbs.dry.current.celsius": {">=": 146.66667}}}}
        }], 
        "startedTimestamp": "2026-04-10T10:40:38Z", 
        "activeStageMode": "entering", 
        "originSource": "android", 
        "cookId": "android-21a789bd-7639-4e90-a97e-02d8361e5f05", 
        "cookableId": "", 
        "activeStageIndex": 0, 
        "cookableType": "manual", 
        "cookTitle": "Manual Cook", 
        "activeStageId": "android-42c63d0c-ca65-492a-9f81-d9fa2fe95b91"
    }
}

cook = payload_cook_to_cook(log_payload)
stg = cook.current_stage
print("Timer trigger:", stg.advance.trigger if isinstance(stg.advance, APOTimer) else "None")
