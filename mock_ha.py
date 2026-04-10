import sys
import types
from unittest.mock import MagicMock

# Create dummy modules for homeassistant
for mod_name in [
    'homeassistant', 'homeassistant.components', 'homeassistant.components.water_heater',
    'homeassistant.config_entries', 'homeassistant.const', 'homeassistant.core',
    'homeassistant.helpers', 'homeassistant.helpers.aiohttp_client',
    'homeassistant.helpers.entity_platform', 'homeassistant.helpers.device_registry',
    'homeassistant.components.http', 'homeassistant.components.panel_custom'
]:
    sys.modules[mod_name] = MagicMock()

# Special mock attributes that are explicitly imported
sys.modules['homeassistant.components.water_heater'].WaterHeaterEntity = MagicMock()
sys.modules['homeassistant.components.water_heater'].WaterHeaterEntityFeature = MagicMock()
sys.modules['homeassistant.components.water_heater'].STATE_ECO = 'eco'
sys.modules['homeassistant.components.water_heater'].STATE_ELECTRIC = 'electric'
sys.modules['homeassistant.const'].UnitOfTemperature = MagicMock()

try:
    import custom_components.anova_culinary.water_heater
    print("SUCCESS")
except Exception as e:
    import traceback
    traceback.print_exc()
