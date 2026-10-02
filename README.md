# Anova API Integration for Home Assistant

A Platinum-tier Home Assistant custom component to control Anova Precision Cookers (APC) and Anova Precision Ovens (APO) locally over WebSockets.

## Features
- **Complete Oven Control:** Includes custom modes for multi-stage cooking.
- **Granular Exposure:** Exposes native HA entities for switches (heating elements, vents), numbers (fan speed, humidity), and climate control.
- **Sous Vide Support:** Seamless integration for Precision cookers mapped to Water Heaters.
- **Family Friendly UI:** Injectable custom panel to generate and execute recipes via an interactive GUI.

## Installation

### HACS (Recommended)
1. Go to HACS -> Integrations -> 3 dots (upper right) -> Custom repositories.
2. Add the URL of this repository and select 'Integration'.
3. Click Download.
4. Restart Home Assistant and navigate to **Settings -> Devices & Services -> Add Integration -> Anova**.

### Authentication
You will need your Personal Access Token. Open the **Anova Oven App** -> **More** -> **Developer** -> **Generate Personal Access Token**. (Sous vide cooker users will need to temporarily download the oven app just to retrieve this token).

---
*Developed purely in asynchronous Python to map exactly with Home Assistant standards.*

## Architecture: APO Transpiler

To seamlessly support both the Anova Precision Oven v1 (flat parameter schemas) and the Anova Precision Oven v2 (complex, AST-driven stage conditions) without polluting the Home Assistant UI, this integration utilizes an internal **APO Representation Proxy**.

### The Universal Schema
The HA UI and internal entity state machine exclusively operate on this clean intermediate representation representation:

**Supported Properties (Per Stage):**
* `sous_vide` (boolean): `true` (wet bulb) or `false` (dry bulb)
* `temperature` (float): Target celsius setting
* `steam` (integer): 0-100% relative humidity
* `heating_elements` (string enum): `top`, `rear`, `bottom`, `top+rear`, `bottom+rear`, `top+bottom`
* `fan` (string enum): `high`, `medium`, `low`, `off`
* `advance` (Optional Object): The condition required to transition to the next stage. Extracted as either:
  * **Timer Object**:
    * `duration` (integer): Length in seconds
    * `trigger` (string enum): `food_detected`, `immediately`, `preheated`, `manually`
  * **Probe Object**:
    * `target` (float): Target internal meat probe temperature (celsius)

### Bidirectional Transpiler
The protocol library acts as a two-way transpiler between HTTP Websockets and Home Assistant.
1. **Forward Translation (HA -> Oven):** When a user interacts with the HA dashboard (e.g., sliding a temperature target), the transpiler converts the representation delta into generational payloads. For v2 ovens, it constructs the AST arrays and enforces generation-specific hardware heat limits (e.g., maximum 446°F limit vs 356°F for bottom-only elements). For v1 ovens, it strips camera-optical conditionals ("When food is detected" downgrades to "Manually") and uses flat payloads.
2. **Reverse Translation (Oven -> HA):** The Anova Cloud broadcasts active multi-stage cook payloads constantly via push telemetry. The module completely intercepts this JSON, extracts the physical sensors natively into an `APONodes` dataclass, reverse-engineers the AST logic trees, and drops it into Home Assistant strictly as an `APOCook` object. This natively allows you to build a complex multi-stage recipe on your official smartphone app, beam it to the oven, and use Home Assistant to intercept and save the active broadcast locally forever!

*(Note: Anova Precision Cookers (sous vide sticks) are simple single-state heaters and bypass this translation engine entirely).*
