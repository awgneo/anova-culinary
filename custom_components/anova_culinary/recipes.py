"""The recipe collection: recipes kept in Home Assistant, edited from the panel."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import storage
from homeassistant.helpers.collection import DictStorageCollection, DictStorageCollectionWebsocket
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, RECIPE_STORAGE_KEY, RECIPE_STORAGE_VERSION

DATA_RECIPES: HassKey[APORecipeCollection] = HassKey(f"{DOMAIN}_recipes")
RECIPE_FIELDS = {"name": str, "stages": list}


class APORecipeCollection(DictStorageCollection):
    """Recipes by id, stored in the recipe format (anova_api/apo/models.py)."""

    async def _process_create_data(self, data: dict[str, Any]) -> dict[str, Any]:
        return data

    @callback
    def _get_suggested_id(self, info: dict[str, Any]) -> str:
        return info.get("name", "recipe")

    async def _update_data(self, item: dict[str, Any], update_data: dict[str, Any]) -> dict[str, Any]:
        return {**item, **update_data}

    def find(self, name: str) -> dict[str, Any] | None:
        """The recipe with this name."""
        return next((item for item in self.data.values() if item.get("name") == name), None)


async def async_setup_recipes(hass: HomeAssistant) -> None:
    """Loads the recipes, and serves them to the panel (anova_culinary/recipes/*)."""
    collection = APORecipeCollection(storage.Store(hass, RECIPE_STORAGE_VERSION, RECIPE_STORAGE_KEY))
    await collection.async_load()
    hass.data[DATA_RECIPES] = collection
    DictStorageCollectionWebsocket(collection, f"{DOMAIN}/recipes", "recipe", RECIPE_FIELDS, RECIPE_FIELDS).async_setup(hass)
