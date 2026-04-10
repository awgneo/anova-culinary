import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import importlib
import sys
from unittest.mock import MagicMock
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()

from custom_components.anova_api.anova_lib.apo.transpiler import synthesize_cook_from_nodes, cook_to_payload
from custom_components.anova_api.anova_lib.apo.models import APONodes
from custom_components.anova_api.anova_lib.client import AnovaDevice
import json

nodes = APONodes()
nodes.temperature_bulbs_mode = "dry"
nodes.setpoint_dry_temp = 160.55
nodes.current_dry_temp = 100.0
nodes.rear_heater_on = True

cook = synthesize_cook_from_nodes(nodes)
device = AnovaDevice("0123", "oven", "oven_v2")
payload = cook_to_payload(cook, device)
print(json.dumps(payload, indent=2))
