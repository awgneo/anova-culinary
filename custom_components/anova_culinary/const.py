"""Constants for the Anova API integration."""

DOMAIN = "anova_culinary"
MANUFACTURER = "Anova"

CONF_TOKEN = "token"

# Polling isn't used because we're cloud_push websockets, but HA expects this for coordinator init
UPDATE_INTERVAL = 30  # seconds

# Recipe Storage
RECIPE_STORAGE_KEY = f"{DOMAIN}.recipes"
RECIPE_STORAGE_VERSION = 1
