"""Binary Sensor platform for physical Anova states."""

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_api.client import AnovaClient
from .anova_api.device import DeviceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.extend([
                AnovaDoorSensor(client, device_id, device.name, device.model),
                AnovaDoorLampSensor(client, device_id, device.name, device.model),
                AnovaCavityLampSensor(client, device_id, device.name, device.model),
                AnovaCameraEmptySensor(client, device_id, device.name, device.model),
            ])
    async_add_entities(entities)


class AnovaAPOBinarySensor(BinarySensorEntity):
    """Base class for Anova Binary Sensors."""
    
    _attr_has_entity_name = True

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id: return
        state = self._client.get_apo_state(self._device_id)
        if not state: return
        self._update_from_state(state)
        self.async_write_ha_state()

    def _update_from_state(self, state) -> None:
        pass


class AnovaDoorSensor(AnovaAPOBinarySensor):
    _attr_name = "Oven Door"
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_unique_id = f"anova_apo_{device_id}_door"

    def _update_from_state(self, state) -> None:
        # For Home Assistant Door class: False = Closed, True = Open
        self._attr_is_on = not state.nodes.door_closed


class AnovaDoorLampSensor(AnovaAPOBinarySensor):
    _attr_name = "Door Lamp"
    _attr_device_class = BinarySensorDeviceClass.LIGHT

    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_unique_id = f"anova_apo_{device_id}_door_lamp"

    def _update_from_state(self, state) -> None:
        self._attr_is_on = state.nodes.door_lamp_on


class AnovaCavityLampSensor(AnovaAPOBinarySensor):
    _attr_name = "Cavity Lamp"
    _attr_device_class = BinarySensorDeviceClass.LIGHT

    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_unique_id = f"anova_apo_{device_id}_cavity_lamp"

    def _update_from_state(self, state) -> None:
        self._attr_is_on = state.nodes.cavity_lamp_on


class AnovaCameraEmptySensor(AnovaAPOBinarySensor):
    _attr_name = "Camera Status"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    
    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_unique_id = f"anova_apo_{device_id}_camera"

    def _update_from_state(self, state) -> None:
        # Occupancy class: True means occupied (food detected), False means clear (empty)
        self._attr_is_on = not state.nodes.cavity_camera_is_empty
