import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

class AnovaCulinary extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      route: { type: Object },
      panel: { type: Object },
      recipes: { type: Array },
      searchQuery: { type: String },
      editingRecipe: { type: Object },
      activeCook: { type: Object },
    };
  }

  constructor() {
    super();
    this.recipes = [];
    this.searchQuery = "";
    this.editingRecipe = null;
    this.activeCook = null;
  }

  async firstUpdated() {
    await this._fetchRecipes();
    await this._fetchActiveCook();
  }

  async _fetchRecipes() {
    if (!this.hass) return;
    try {
      const data = await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/recipes/list`
      });
      this.recipes = data;
    } catch (e) {
      console.error("Failed fetching WS collection", e);
    }
  }

  _getGlobalUnit() {
    return (this.hass && this.hass.config && this.hass.config.unit_system && this.hass.config.unit_system.temperature && this.hass.config.unit_system.temperature.includes('F')) ? 'F' : 'C';
  }

  _normalizeUnits(recipe) {
    const targetUnit = this._getGlobalUnit();
    const cloned = JSON.parse(JSON.stringify(recipe));
    if (cloned.stages) {
      cloned.stages.forEach(stage => {
        if (!stage.temperature_unit) stage.temperature_unit = 'C';
        if (targetUnit === 'F' && stage.temperature_unit === 'C') {
          stage.temperature = Math.round(((stage.temperature * 9 / 5) + 32) * 10) / 10;
          if (stage.advance && stage.advance.target !== undefined) {
            stage.advance.target = Math.round(((stage.advance.target * 9 / 5) + 32) * 10) / 10;
          }
        } else if (targetUnit === 'C' && stage.temperature_unit === 'F') {
          stage.temperature = Math.round(((stage.temperature - 32) * 5 / 9) * 10) / 10;
          if (stage.advance && stage.advance.target !== undefined) {
            stage.advance.target = Math.round(((stage.advance.target - 32) * 5 / 9) * 10) / 10;
          }
        }
        stage.temperature_unit = targetUnit;
      });
    }
    return cloned;
  }

  async _fetchActiveCook() {
    if (!this.hass) return;
    try {
      const active = await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/cook`
      });
      if (active) {
        // Only show if it doesn't match an existing local recipe ID
        const isKnown = this.recipes.some(r => r.id === active.id);
        if (!isKnown) {
          this.activeCook = active;
        }
      }
    } catch (e) {
      console.error("Failed fetching active cook from websocket", e);
    }
  }

  _handleSearch(e) {
    this.searchQuery = e.target.value.toLowerCase();
  }

  _triggerFileImport() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = e => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = event => {
        try {
          const parsed = JSON.parse(event.target.result);
          parsed.id = null; // Strip internal ID so it becomes a new recipe
          this.editingRecipe = this._normalizeUnits(parsed);
          this.requestUpdate();
        } catch (err) {
          console.error("Failed to parse recipe JSON", err);
          alert("Invalid recipe file.");
        }
      };
      reader.readAsText(file);
    };
    input.click();
  }

  _exportRecipe(recipe) {
    if (!recipe) return;
    const exportData = { 
      name: recipe.name || "Untitled Recipe", 
      stages: recipe.stages || []
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safeName = exportData.name.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    a.download = `apo_recipe_${safeName}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  _startCreate() {
    this.editingRecipe = { name: "", stages: [] };
  }

  _startEdit(recipe) {
    this.editingRecipe = this._normalizeUnits(recipe);
  }

  _importCook() {
    if (!this.activeCook) return;
    const importedRecipe = { ...this.activeCook, id: null };
    if (!importedRecipe.name) importedRecipe.name = "Imported Cook";
    this.editingRecipe = this._normalizeUnits(importedRecipe);
    this.activeCook = null;
    this.requestUpdate();
  }

  _addStage() {
    if (!this.editingRecipe) return;
    this.editingRecipe.stages = [...this.editingRecipe.stages, {
      id: crypto.randomUUID ? crypto.randomUUID() : "uuid-1234",
      sous_vide: false,
      temperature: this._getGlobalUnit() === 'F' ? 140.0 : 60.0,
      temperature_unit: this._getGlobalUnit(),
      steam: 0,
      heating_elements: "rear",
      fan: "high",
      advance: null
    }];
    this.requestUpdate();
  }

  _updateStage(index, field, value) {
    if (!this.editingRecipe) return;
    const stage = this.editingRecipe.stages[index];

    // Type casting logic
    if (field === "sous_vide") value = (value === "true" || value === true);
    if (field === "temperature") value = parseFloat(value) || 0.0;
    if (field === "steam") value = parseInt(value) || 0;

    stage[field] = value;
    this.requestUpdate();
  }

  _updateAdvance(index, field, value) {
    if (!this.editingRecipe) return;
    const stage = this.editingRecipe.stages[index];

    if (field === 'type') {
      if (value === 'none') stage.advance = null;
      else if (value === 'timer') stage.advance = { duration: 3600, trigger: "manually" };
      else if (value === 'probe') stage.advance = { target: this._getGlobalUnit() === 'F' ? 120.0 : 50.0 };
    } else if (stage.advance) {
      if (field === 'duration_mins') stage.advance.duration = (parseInt(value) || 0) * 60;
      if (field === 'trigger') stage.advance.trigger = value;
      if (field === 'target') stage.advance.target = parseFloat(value) || 0.0;
    }
    this.requestUpdate();
  }

  _removeStage(index) {
    if (!this.editingRecipe) return;
    this.editingRecipe.stages.splice(index, 1);
    this.requestUpdate();
  }

  async _saveRecipe() {
    if (!this.editingRecipe) return;

    try {
      const type = this.editingRecipe.id ? `${this.panel.config.domain}/recipes/update` : `${this.panel.config.domain}/recipes/create`;

      const payload = {
        type: type,
        name: this.editingRecipe.name,
        stages: this.editingRecipe.stages
      };
      if (this.editingRecipe.id) payload.recipe_id = this.editingRecipe.id;

      await this.hass.connection.sendMessagePromise(payload);
    } catch (e) {
      console.error("Failed executing HA WS call", e);
    }

    this.editingRecipe = null;
    this._fetchRecipes();
  }

  async _deleteRecipe(id, name) {
    try {
      await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/recipes/delete`,
        recipe_id: id
      });
    } catch (e) {
      console.error("Failed executing HA WS call", e);
    }
    this._fetchRecipes();
  }

  render() {
    if (this.editingRecipe) {
      return this.renderEditor();
    }

    const filtered = this.recipes.filter(r => r.name.toLowerCase().includes(this.searchQuery));

    return html`
      <div class="app-background">
          <div class="glass-container">
            <div class="header">
              <h1>Recipes</h1>
              <div class="action-group">
                <button class="btn-secondary" @click=${this._triggerFileImport}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  Import Recipe
                </button>
                <button class="btn-primary glow" @click=${this._startCreate}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
                  New Recipe
                </button>
              </div>
            </div>
            
            <div class="search-bar">
              <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
              <input type="text" placeholder="Search recipes..." @input=${this._handleSearch} .value=${this.searchQuery} />
            </div>

            ${this.activeCook ? html`
              <div class="active-cook-banner slide-in">
                <div class="banner-icon">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                </div>
                <div class="banner-text">
                  <h3>Active Cook Detected</h3>
                  <p>Your oven is currently running a multi-stage cook. Extract and save it to your recipes library?</p>
                </div>
                <button class="btn-primary glow" style="margin-left:auto;" @click=${this._importCook}>
                  Import Recipe
                </button>
              </div>
            ` : ''}

            <ul class="recipe-list">
              ${filtered.length === 0 ? html`<div class="empty-state">No recipes found. Create one to begin.</div>` : ''}
              ${filtered.map(r => html`
                <li class="recipe-item slide-in">
                  <div class="recipe-info">
                      <div class="recipe-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM12 16v-4M12 8h.01"/></svg>
                      </div>
                      <span class="recipe-name">${r.name}</span>
                  </div>
                  <div class="action-group">
                    <button class="btn-ghost" @click=${() => this._startEdit(r)}>Edit</button>
                    <button class="btn-ghost" style="padding:6px;" @click=${() => this._exportRecipe(r)} title="Export JSON">
                      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    </button>
                    <button class="btn-danger" @click=${() => this._deleteRecipe(r.id, r.name)}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    </button>
                  </div>
                </li>
              `)}
            </ul>
          </div>
      </div>
    `;
  }

  renderEditor() {
    return html`
      <div class="app-background">
          <div class="glass-container">
            <div class="header">
              <h1>${!this.editingRecipe.id ? "Create Recipe" : "Edit Recipe"}</h1>
              <div class="action-group">
                <button class="btn-ghost" @click=${() => { this.editingRecipe = null; }}>Discard</button>
                <button class="btn-primary glow" @click=${this._saveRecipe}>Save Recipe</button>
              </div>
            </div>
            
            <div class="form-group hero-input">
                <label>NAME</label>
                <input type="text" .value=${this.editingRecipe.name} @input=${e => this.editingRecipe.name = e.target.value} placeholder="e.g. Perfect Medium Rare Ribeye" />
            </div>
            
            <div class="stages-header">
                <h3>Stages</h3>
                <button class="btn-secondary" @click=${this._addStage}>+ Add Stage</button>
            </div>
            
            <div class="stages-grid">
                ${this.editingRecipe.stages.map((stage, i) => html`
                <div class="stage-card pop-in">
                    <div class="stage-card-header">
                        <span class="stage-badge">Stage ${i + 1}</span>
                        <button class="btn-icon-danger" @click=${() => this._removeStage(i)} title="Remove Stage">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                        </button>
                    </div>
                    
                    <div class="stage-grid-inner">
                        <div class="form-group">
                            <label>MODE</label>
                            <select .value=${stage.sous_vide ? "true" : "false"} @change=${e => this._updateStage(i, 'sous_vide', e.target.value)}>
                                <option value="false">Dry Roasting</option>
                                <option value="true">Sous Vide</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label>TEMPERATURE</label>
                            <div style="position:relative; display:flex;">
                              <input type="number" step="0.1" .value=${stage.temperature} @input=${e => this._updateStage(i, 'temperature', e.target.value)} style="width:100%; padding-right:45px;" />
                              <span style="position:absolute; right:12px; top:50%; transform:translateY(-50%); color:var(--text-muted); font-weight:600; pointer-events:none;">°${this._getGlobalUnit()}</span>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>STEAM (%)</label>
                            <input type="number" min="0" max="100" .value=${stage.steam} @input=${e => this._updateStage(i, 'steam', e.target.value)} .disabled=${stage.sous_vide} />
                        </div>

                        <div class="form-group">
                            <label>HEATING ELEMENTS</label>
                            <select .value=${stage.heating_elements} @change=${e => this._updateStage(i, 'heating_elements', e.target.value)}>
                                <option value="top">Top</option>
                                <option value="rear">Rear</option>
                                <option value="bottom">Bottom</option>
                                <option value="top+rear">Top + Rear</option>
                                <option value="bottom+rear">Bottom + Rear</option>
                                <option value="top+bottom">Top + Bottom</option>
                            </select>
                        </div>
                        
                        <div class="form-group">
                            <label>FAN SPEED</label>
                            <select .value=${stage.fan} @change=${e => this._updateStage(i, 'fan', e.target.value)}>
                                <option value="off">Off</option>
                                <option value="low">Low</option>
                                <option value="medium">Medium</option>
                                <option value="high">High</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label>TRANSITION (TIMER/PROBE)</label>
                            <select .value=${stage.advance === null ? "none" : (stage.advance.target !== undefined ? "probe" : "timer")} @change=${e => this._updateAdvance(i, 'type', e.target.value)}>
                                <option value="none">Manual Transition</option>
                                <option value="timer">Timer</option>
                                <option value="probe">Food Probe</option>
                            </select>
                        </div>

                        ${stage.advance && stage.advance.duration !== undefined ? html`
                        <div class="form-group slide-in">
                            <label>TIMER DURATION (MIN)</label>
                            <input type="number" step="1" .value=${Math.floor(stage.advance.duration / 60)} @input=${e => this._updateAdvance(i, 'duration_mins', e.target.value)} />
                        </div>
                        <div class="form-group slide-in">
                            <label>TIMER TRIGGER</label>
                            <select .value=${stage.advance.trigger} @change=${e => this._updateAdvance(i, 'trigger', e.target.value)}>
                                <option value="immediately">Immediately</option>
                                <option value="manually">Manually</option>
                                <option value="preheated">When Preheated</option>
                                <option value="food_detected">On Food Detected</option>
                            </select>
                        </div>
                        ` : ''}

                        ${stage.advance && stage.advance.target !== undefined ? html`
                        <div class="form-group slide-in">
                            <label>PROBE TARGET</label>
                            <div style="position:relative; display:flex;">
                              <input type="number" step="0.1" .value=${stage.advance.target} @input=${e => this._updateAdvance(i, 'target', e.target.value)} style="width:100%; padding-right:45px;" />
                              <span style="position:absolute; right:12px; top:50%; transform:translateY(-50%); color:var(--text-muted); font-weight:600; pointer-events:none;">°${this._getGlobalUnit()}</span>
                            </div>
                        </div>
                        ` : ''}

                    </div>
                </div>
                `)}
            </div>
            
            ${this.editingRecipe.stages.length === 0 ? html`<div class="empty-state">No stages defined. Your oven won't know what to do!</div>` : ''}
            
          </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&family=Inter:wght@400;500&display=swap');

      * {
          box-sizing: border-box;
      }

      :host {
        display: block;
        min-height: 100vh;
        --bg-color: #0f1115;
        --glass-bg: rgba(26, 29, 36, 0.75);
        --glass-border: rgba(255, 255, 255, 0.08);
        --text-main: #f8fafc;
        --text-muted: #94a3b8;
        --accent: #3b82f6;
        --accent-hover: #60a5fa;
        --accent-glow: rgba(59, 130, 246, 0.4);
        --danger: #ef4444;
        --danger-hover: #f87171;
        --card-bg: rgba(255, 255, 255, 0.03);
        --input-bg: rgba(0, 0, 0, 0.2);
      }

      .app-background {
        background: radial-gradient(circle at top right, #1e293b 0%, var(--bg-color) 40%);
        min-height: 100vh;
        padding: 40px 20px;
        color: var(--text-main);
        font-family: 'Inter', sans-serif;
      }

      .glass-container {
        max-width: 900px;
        margin: 0 auto;
        background: var(--glass-bg);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid var(--glass-border);
        padding: 40px;
        border-radius: 20px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
      }

      h1 {
        font-family: 'Outfit', sans-serif;
        font-size: 2.5rem;
        font-weight: 600;
        margin: 0;
        background: linear-gradient(to right, #fff, #94a3b8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
      }

      h3 {
        font-family: 'Outfit', sans-serif;
        font-size: 1.5rem;
        font-weight: 500;
        margin: 0;
      }

      .header, .stages-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 32px;
      }
      
      .stages-header {
          margin-top: 40px;
          margin-bottom: 24px;
          border-bottom: 1px solid var(--glass-border);
          padding-bottom: 12px;
      }

      /* Buttons */
      button {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 20px;
        font-family: 'Inter', sans-serif;
        font-weight: 500;
        font-size: 0.95rem;
        border: none;
        border-radius: 10px;
        cursor: pointer;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      }
      
      button svg {
          width: 18px;
          height: 18px;
      }

      .btn-primary {
        background: linear-gradient(135deg, var(--accent), #2563eb);
        color: white;
      }

      .btn-primary:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px -10px var(--accent-glow);
      }

      .btn-secondary {
        background: var(--card-bg);
        color: var(--text-main);
        border: 1px solid var(--glass-border);
      }

      .btn-secondary:hover {
        background: rgba(255, 255, 255, 0.08);
      }

      .btn-ghost {
        background: transparent;
        color: var(--text-muted);
      }

      .btn-ghost:hover {
        color: var(--text-main);
        background: rgba(255, 255, 255, 0.05);
      }

      .btn-danger {
        background: rgba(239, 68, 68, 0.1);
        color: var(--danger);
        padding: 10px;
      }

      .btn-danger:hover {
        background: var(--danger);
        color: white;
      }
      
      .btn-icon-danger {
          background: transparent;
          color: var(--text-muted);
          padding: 6px;
      }
      .btn-icon-danger:hover {
          color: var(--danger);
          background: rgba(239, 68, 68, 0.1);
      }

      .action-group {
        display: flex;
        gap: 12px;
      }

      /* Search */
      .search-bar {
        position: relative;
        margin-bottom: 32px;
      }

      .search-icon {
        position: absolute;
        left: 16px;
        top: 50%;
        transform: translateY(-50%);
        width: 20px;
        height: 20px;
        stroke: var(--text-muted);
      }

      .search-bar input {
        width: 100%;
        padding: 16px 16px 16px 48px;
        font-size: 1.1rem;
        font-family: 'Inter', sans-serif;
        background: var(--input-bg);
        border: 1px solid var(--glass-border);
        border-radius: 12px;
        color: var(--text-main);
        transition: border-color 0.2s;
      }

      .search-bar input:focus {
        outline: none;
        border-color: var(--accent);
      }

      /* Lists */
      .recipe-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .recipe-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 20px;
        background: var(--card-bg);
        border: 1px solid var(--glass-border);
        border-radius: 14px;
        transition: transform 0.2s, background 0.2s;
      }

      .recipe-item:hover {
        transform: translateX(4px);
        background: rgba(255, 255, 255, 0.05);
      }

      .recipe-info {
        display: flex;
        align-items: center;
        gap: 16px;
      }

      .recipe-icon {
        background: rgba(59, 130, 246, 0.1);
        color: var(--accent);
        padding: 10px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .recipe-name {
        font-size: 1.1rem;
        font-weight: 500;
      }

      /* Editor Form */
      .form-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 20px;
      }

      .form-group label {
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--text-muted);
        font-weight: 600;
      }

      .hero-input input {
        font-size: 1.5rem;
        padding: 16px;
        background: var(--input-bg);
        border: 1px solid var(--glass-border);
        border-radius: 12px;
        color: var(--text-main);
        width: 100%;
        transition: border-color 0.2s;
      }
      
      .hero-input input:focus {
          outline: none;
          border-color: var(--accent);
      }

      /* Stages Grid */
      .stages-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 24px;
        margin-bottom: 32px;
      }

      .stage-card {
        background: var(--card-bg);
        border: 1px dashed var(--glass-border);
        border-radius: 16px;
        padding: 24px;
        transition: border-color 0.2s;
      }

      .stage-card:hover {
        border-color: rgba(255, 255, 255, 0.2);
      }

      .stage-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
      }

      .stage-badge {
          background: var(--accent);
          color: white;
          padding: 4px 12px;
          border-radius: 20px;
          font-size: 0.8rem;
          font-weight: 600;
          letter-spacing: 0.5px;
          text-transform: uppercase;
      }

      .stage-grid-inner {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
      }
      
      .stage-grid-inner .form-group {
          margin-bottom: 0;
      }

      .stage-grid-inner input, .stage-grid-inner select {
        padding: 12px;
        background: var(--input-bg);
        border: 1px solid var(--glass-border);
        border-radius: 8px;
        color: var(--text-main);
        font-family: 'Inter', sans-serif;
        font-size: 1rem;
        width: 100%;
      }
      
      .stage-grid-inner input:focus, .stage-grid-inner select:focus {
          outline: none;
          border-color: var(--accent);
      }
      
      .stage-grid-inner input:disabled {
          opacity: 0.5;
          cursor: not-allowed;
      }

      /* Empty States */
      .empty-state {
        text-align: center;
        padding: 40px;
        color: var(--text-muted);
        font-style: italic;
        background: var(--card-bg);
        border-radius: 14px;
        border: 1px dashed var(--glass-border);
      }

      /* Banner */
      .active-cook-banner {
        display: flex;
        align-items: center;
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(37, 99, 235, 0.15));
        border: 1px solid rgba(59, 130, 246, 0.3);
        border-radius: 14px;
        padding: 16px 20px;
        margin-bottom: 24px;
        gap: 16px;
      }
      .banner-icon {
        background: rgba(59, 130, 246, 0.2);
        color: var(--accent);
        border-radius: 50%;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .banner-text h3 {
        font-size: 1.1rem;
        color: var(--accent-hover);
        margin: 0 0 4px 0;
        font-family: 'Outfit', sans-serif;
      }
      .banner-text p {
        margin: 0;
        color: var(--text-muted);
        font-size: 0.9rem;
      }

      /* Animations */
      @keyframes slideIn {
        from { opacity: 0; transform: translateX(-10px); }
        to { opacity: 1; transform: translateX(0); }
      }
      @keyframes popIn {
        from { opacity: 0; transform: scale(0.98); }
        to { opacity: 1; transform: scale(1); }
      }
      .slide-in {
        animation: slideIn 0.3s ease-out forwards;
      }
      .pop-in {
        animation: popIn 0.3s ease-out forwards;
      }
    `;
  }
}
customElements.define("anova-culinary", AnovaCulinary);
