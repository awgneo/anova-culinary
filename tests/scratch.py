import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from custom_components.anova_culinary.anova_api.apo.transpiler import cook_to_payload
from custom_components.anova_culinary.anova_api.apo.models import APOCook, APORecipe, APOStage
from custom_components.anova_culinary.anova_api.client import AnovaDevice

device = AnovaDevice(device_id="0123d1e411114d5401", type="oven", model="oven_v2")
cook = APOCook(recipe=APORecipe(title="Manual Cook", stages=[APOStage(temperature=54.44, sous_vide=True)]), active_stage_index=0)
payload = cook_to_payload(cook, device)
import json
print(json.dumps(payload, indent=2))
