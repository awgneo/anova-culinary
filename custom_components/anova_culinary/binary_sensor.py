"""Binary Sensor platform for physical Anova states."""

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .anova_api.client import AnovaClient
from .anova_api.device import AnovaDevice
from .anova_api.product import AnovaProduct


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.extend([
                AnovaDoorSensor(client, device),
                AnovaCavityLampSensor(client, device),
                AnovaCameraEmptySensor(client, device),
            ])
    async_add_entities(entities)


class AnovaBinarySensor(BinarySensorEntity):
    """Base class for Anova Binary Sensors."""
    
    _attr_has_entity_name = True

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id: return
        state = self._client.get_apo_state(self._device.id)
        if not state: return
        self._update_from_state(state)
        self.async_write_ha_state()

    def _update_from_state(self, state) -> None:
        pass


class AnovaDoorSensor(AnovaBinarySensor):
    _attr_name = "Door Status"
    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_icon = "mdi:door"

    def __init__(self, client: AnovaClient, device: AnovaDevice):
        super().__init__(client, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_door"

    def _update_from_state(self, state) -> None:
        # For Home Assistant Door class: False = Closed, True = Open
        self._attr_is_on = not state.nodes.door_closed


class AnovaCavityLampSensor(AnovaBinarySensor):
    _attr_name = "Cavity Light"
    _attr_device_class = BinarySensorDeviceClass.LIGHT
    _attr_icon = "mdi:lightbulb"

    def __init__(self, client: AnovaClient, device: AnovaDevice):
        super().__init__(client, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_cavity_lamp"

    def _update_from_state(self, state) -> None:
        self._attr_is_on = state.nodes.cavity_lamp_on


class AnovaCameraEmptySensor(AnovaBinarySensor):
    _attr_name = "Camera Status"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:cctv"
    
    def __init__(self, client: AnovaClient, device: AnovaDevice):
        super().__init__(client, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_camera"

    def _update_from_state(self, state) -> None:
        # Occupancy class: True means occupied (food detected), False means clear (empty)
        self._attr_is_on = not state.nodes.cavity_camera_is_empty
