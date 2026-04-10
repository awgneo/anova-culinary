# Anova API Engine Architecture

The core of the Anova API (`anova_api`) is driven by a powerful bidirectional Transpiler engine. Because Anova's internal API changes drastically across generations (e.g., `oven_v1` uses flat arrays while `oven_v2` uses deeply nested AST logical condition trees), the Transpiler decouples Home Assistant from the chaos of raw JSON payloads. 

The integration components (`climate.py`, `switch.py`, etc.) execute simple reads/writes against a pristine, statically-typed python object model (found in `models.py`). The Transpiler sits in between, catching raw web socket JSON from Anova, interpreting it into our python models, and subsequently transforming our python objects back into native Anova websocket strings.

## The Transpiler Lifecycle

The engine operates on four critical lifecycle boundaries located in `transpiler.py`:

### 1. `recipe_to_cook`
**Role:** Intent Creation
**Signature:** `(recipe: APORecipe) -> APOCook`

Converts a static multi-stage recipe sequence (`APORecipe`) into a live, executing intent representation (`APOCook`). It securely clones the schema, generates unique UUIDs for untracked stages, and establishes an active stage pointer (index) to monitor where in the sequence the user currently is. This is typically invoked when starting a fresh cooking routine.

---

### 2. `cook_to_payload`
**Role:** Command Transmission (Forward Transpiler)
**Signature:** `(cook: APOCook, device_model: str) -> dict`

Translates our pristine `APOCook` intent back into Anova's hyper-specific native JSON instruction block (`CMD_APO_START`).
- **Critical Logic:** This only constructs the *recipe intent* (temperatures, fans, timers). We never transmit `nodes` values back to the oven because we cannot remotely instruct physical hardware limitations (like forcing the water tank to be "full"). 
- It actively intercepts temperature constraint rules based on physical hardware model limitations (clamping high temps when the bottom element is forced). 

---

### 3. `payload_to_state`
**Role:** Telemetry Master (Reverse Transpiler)
**Signature:** `(raw_payload: dict) -> APOState`

The heavy lifter. Whenever the oven blasts a websocket update ping, this captures it and constructs the singular `APOState` object that serves as Home Assistant's unified truth. 
- It maps wildly disparate hardware telemetry variables into a beautiful, fully flattened `APONodes` representation (capturing current probe temps, boiler watts, water tank flags, and even hidden camera telemetry).
- After mapping physical hardware truth, it triggers `payload_cook_to_cook` internally to determine what the logic intent currently is.
- It unites both models into one cohesive `APOState` proxy object.

---

### 4. `payload_cook_to_cook`
**Role:** Logic Parser 
**Signature:** `(raw_payload: dict) -> APOCook`

An internal helper dispatched natively by `payload_to_state`. It parses the messy, nested JSON recipe representations found in the telemetry stream and translates those logical boundaries back into our strict `APOCook` schema. It normalizes triggers, clamps sous-vide thresholds, and untangles condition chains back into typed Enums.
