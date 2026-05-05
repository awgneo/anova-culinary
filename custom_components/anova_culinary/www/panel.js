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
      ovens: { type: Array },
      isKiosk: { type: Boolean },
      showDeleteModal: { type: Boolean },
      recipeToDelete: { type: Object },
      showPlayModal: { type: Boolean },
      recipeToPlay: { type: Object },
      selectedOvens: { type: Array },
      recipeSortDirection: { type: Number }
    };
  }

  constructor() {
    super();
    this.recipes = [];
    this.searchQuery = "";
    this.editingRecipe = null;
    this.activeCook = null;
    this.ovens = [];
    this.isKiosk = window.location.search.includes("kiosk");
    this.showDeleteModal = false;
    this.recipeToDelete = null;
    this.showPlayModal = false;
    this.recipeToPlay = null;
    this.selectedOvens = [];
    this.recipeSortDirection = 1;
  }

  async firstUpdated() {
    await this._fetchRecipes();
    await this._subscribeCook();
  }

  async _fetchRecipes() {
    if (!this.hass) return;
    try {
      const data = await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/recipes/list`
      });
      this.recipes = data;

      const ovens = await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/ovens`
      });
      this.ovens = (ovens || []).sort((a, b) => a.name.localeCompare(b.name));
      this.selectedOvens = [];
    } catch (e) {
      console.error("Failed fetching WS collection data", e);
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

  async _subscribeCook() {
    if (!this.hass) return;
    try {
      this._unsubCook = await this.hass.connection.subscribeMessage(
        (active) => {
          if (active) {
            // Only show if it doesn't match an existing local recipe ID or Name precisely
            const isKnown = this.recipes.some(r => r.id === active.id || r.name === active.name);
            if (!isKnown) {
              this.activeCook = active;
            } else {
              this.activeCook = null;
            }
          } else {
            this.activeCook = null;
          }
        },
        { type: `${this.panel.config.domain}/cook` }
      );
    } catch (e) {
      console.error("Failed subscribing to active cook websocket", e);
    }
  }

  _handleSearch(e) {
    this.searchQuery = e.target.value;
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
    a.download = `${safeName}.json`;
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

    // The python backend will sometimes send `title` instead of `name` depending on the mashumaro alias settings!
    const validName = importedRecipe.name || importedRecipe.title || importedRecipe.cookTitle;
    if (validName) {
      importedRecipe.name = validName;
    } else {
      importedRecipe.name = "Imported Cook";
    }

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

  _moveStage(index, direction) {
    if (!this.editingRecipe) return;
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= this.editingRecipe.stages.length) return;
    const stages = this.editingRecipe.stages;
    const temp = stages[index];
    stages[index] = stages[newIndex];
    stages[newIndex] = temp;
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

  _promptDelete(recipe) {
    this.recipeToDelete = recipe;
    this.showDeleteModal = true;
  }

  async _confirmDelete() {
    if (!this.recipeToDelete) return;
    try {
      await this.hass.connection.sendMessagePromise({
        type: `${this.panel.config.domain}/recipes/delete`,
        recipe_id: this.recipeToDelete.id
      });
    } catch (e) {
      console.error("Failed executing HA WS call", e);
    }
    this.showDeleteModal = false;
    this.recipeToDelete = null;
    this._fetchRecipes();
  }

  _cancelDelete() {
    this.showDeleteModal = false;
    this.recipeToDelete = null;
  }

  async _promptPlay(recipe) {
    if (this.ovens.length === 1) {
      // Just play immediately if there's only 1 oven
      this.selectedOvens = [this.ovens[0].id];
      this.recipeToPlay = recipe;
      await this._playRecipe();
    } else if (this.ovens.length > 1) {
      // Show modal to pick oven
      this.recipeToPlay = recipe;
      this.selectedOvens = [];
      this.showPlayModal = true;
    } else {
      alert("No Anova Precision Ovens found on your network.");
    }
  }

  _toggleOvenSelection(id) {
    if (this.selectedOvens.includes(id)) {
      this.selectedOvens = this.selectedOvens.filter(o => o !== id);
    } else {
      this.selectedOvens = [...this.selectedOvens, id];
    }
  }

  async _playRecipe() {
    if (!this.recipeToPlay || this.selectedOvens.length === 0) return;
    try {
      await this.hass.callService(
        this.panel.config.domain,
        "play_recipe",
        {
          device_id: this.selectedOvens,
          recipe_id: this.recipeToPlay.id
        }
      );
    } catch (e) {
      console.error("Failed to start recipe", e);
      alert("Failed to start recipe on ovens.");
    }
    this.showPlayModal = false;
    this.recipeToPlay = null;
    if (this.isKiosk) window.history.back();
  }

  _cancelPlay() {
    this.showPlayModal = false;
    this.recipeToPlay = null;
  }

  render() {
    if (this.editingRecipe) {
      return this.renderEditor();
    }

    const searchLower = this.searchQuery.toLowerCase();
    const filtered = this.recipes
      .filter(r => r.name.toLowerCase().includes(searchLower))
      .sort((a, b) => this.recipeSortDirection * a.name.localeCompare(b.name));

    return html`
      <div class="page">
        <div class="toolbar">
          <div class="toolbar-title" style="display: flex; align-items: center;">
            ${this.isKiosk ? html`
              <button class="icon-btn" @click=${() => window.history.back()} style="margin-right: 16px; width: 44px; height: 44px; background: rgba(255, 255, 255, 0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center;" title="Back">
                <svg viewBox="0 0 24 24" fill="currentColor" stroke="none" style="width: 24px; height: 24px;"><path d="M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z"/></svg>
              </button>
            ` : ''}
          </div>
          <div class="search-bar">
            <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
            <input type="text" placeholder="Search recipes..." @input=${this._handleSearch} .value=${this.searchQuery} />
          </div>
          <div class="action-group">
            ${!this.isKiosk ? html`
            <button class="mwc-button" @click=${this._triggerFileImport}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              Import
            </button>
            ` : ''}
            <button class="mwc-button primary" @click=${this._startCreate}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
              New
            </button>
          </div>
        </div>

        <div class="content">
          ${this.activeCook ? html`
            <div class="active-cook-banner slide-in">
              <div class="banner-icon">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
              </div>
              <div class="banner-text">
                <h3>Active Cook Detected</h3>
                <p>Your oven is currently running a multi-stage cook. Extract and save it to your recipes library?</p>
              </div>
              <button class="mwc-button primary" style="margin-left: auto;" @click=${this._importCook}>
                Import
              </button>
            </div>
          ` : ''}

          <div class="data-table">
            <div class="table-header">
              <div class="col" style="flex:2; padding-left:16px; cursor:pointer; display:flex; align-items:center; gap:4px; user-select:none;" @click=${() => { this.recipeSortDirection *= -1; this.requestUpdate(); }}>
                Recipe
                ${this.recipeSortDirection === 1
        ? html`<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>`
        : html`<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`}
              </div>
              <div class="col" style="width:160px; text-align:right; padding-right:16px;"></div>
            </div>
            
            ${filtered.length === 0 ? html`<div class="empty-state">No recipes found.</div>` : ''}
            ${filtered.map(r => html`
              <div class="table-row slide-in">
                <div class="col" style="flex:2; padding-left:16px; font-weight:500; display:flex; align-items:center;">
                  ${r.name}
                </div>

                <div class="col" style="width:160px; text-align:right; padding-right:16px;">
                  <div class="row-actions">
                    <button class="icon-btn play" @click=${() => this._promptPlay(r)} title="Play">
                      <svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="8 5 19 12 8 19 8 5"/></svg>
                    </button>
                    <button class="icon-btn" @click=${() => this._startEdit(r)} title="Edit">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    ${!this.isKiosk ? html`
                    <button class="icon-btn" @click=${() => this._exportRecipe(r)} title="Export JSON">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    </button>
                    ` : ''}
                    <button class="icon-btn danger" @click=${() => this._promptDelete(r)} title="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    </button>
                  </div>
                </div>
              </div>
            `)}
          </div>
        </div>

        ${this.showDeleteModal ? html`
          <div class="modal-overlay">
            <div class="ha-card form-card pop-in" style="margin: 0; max-width: 400px; width: 100%;">
              <div class="card-header" style="border-bottom: 1px solid var(--divider-color); padding-bottom: 16px;">
                <h3>Delete ${this.recipeToDelete ? this.recipeToDelete.name : "this recipe"}?</h3>
              </div>
              <div class="card-content">
                <p>This action cannot be undone.</p>
                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px;">
                  <button class="mwc-button outline" @click=${this._cancelDelete}>Cancel</button>
                  <button class="mwc-button primary" style="background: var(--error-color, #f44336);" @click=${this._confirmDelete}>Delete</button>
                </div>
              </div>
            </div>
          </div>
        ` : ''}

        ${this.showPlayModal ? html`
          <div class="modal-overlay">
            <div class="ha-card form-card pop-in" style="margin: 0; max-width: 400px; width: 100%;">
              <div class="card-header" style="border-bottom: 1px solid var(--divider-color); padding-bottom: 16px;">
                <h3>Play ${this.recipeToPlay ? this.recipeToPlay.name : "this recipe"}?</h3>
              </div>
              <div class="card-content">
                
                <div style="display: flex; flex-direction: column; gap: 8px;">
                  ${this.ovens.map(o => html`
                    <div 
                      @click=${() => this._toggleOvenSelection(o.id)} 
                      style="display: flex; align-items: center; gap: 12px; padding: 16px; min-height: 56px; background-color: ${this.selectedOvens.includes(o.id) ? 'rgba(3, 169, 244, 0.1)' : 'var(--card-background-color, rgba(255, 255, 255, 0.05))'}; border: 1px solid ${this.selectedOvens.includes(o.id) ? 'var(--primary-color, #03a9f4)' : 'var(--divider-color, rgba(255, 255, 255, 0.12))'}; border-radius: 8px; cursor: pointer; transition: all 0.2s; user-select: none;">
                      <div style="display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; border: 2px solid ${this.selectedOvens.includes(o.id) ? 'var(--primary-color, #03a9f4)' : 'var(--secondary-text-color, #9e9e9e)'}; background-color: ${this.selectedOvens.includes(o.id) ? 'var(--primary-color, #03a9f4)' : 'transparent'}; box-sizing: border-box;">
                        ${this.selectedOvens.includes(o.id) ? html`<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="var(--text-primary-color, #ffffff)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>` : ''}
                      </div>
                      <div style="font-size: 16px; font-weight: 500; color: ${this.selectedOvens.includes(o.id) ? 'var(--primary-color, #03a9f4)' : 'var(--primary-text-color)'};">
                        ${o.name}
                      </div>
                    </div>
                  `)}
                </div>

                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px;">
                  <button class="mwc-button outline" @click=${this._cancelPlay}>Cancel</button>
                  ${this.selectedOvens.length > 0 ? html`<button class="mwc-button primary" @click=${this._playRecipe}>Play</button>` : ''}
                </div>
              </div>
            </div>
          </div>
        ` : ''}

      </div>
    `;
  }

  renderEditor() {
    return html`
      <div class="page">
        <div class="toolbar">
           <div class="toolbar-title">
             <div class="type-icon" style="margin-right:16px;">
                 <ha-icon icon="mdi:text-box-outline"></ha-icon>
             </div>
             ${!this.editingRecipe.id ? "Create Recipe" : "Edit Recipe"}
           </div>
           <div class="action-group">
             <button class="mwc-button" @click=${() => { this.editingRecipe = null; }}>Cancel</button>
             <button class="mwc-button primary" @click=${this._saveRecipe}>Save</button>
           </div>
        </div>

        <div class="content" style="max-width:1040px; width:100%; margin: 0 auto; padding-top: 24px;">
            <div class="ha-card form-card">
              <div class="card-content">
                  <div class="form-group hero-input">
                      <label>NAME</label>
                      <input type="text" .value=${this.editingRecipe.name} @input=${e => this.editingRecipe.name = e.target.value} placeholder="e.g. Perfect Medium Rare Ribeye" />
                  </div>
              </div>
            </div>
            
            <div class="stages-header">
                <h3>Stages</h3>
                <button class="mwc-button outline" @click=${this._addStage}>+ Add Stage</button>
            </div>
            
            ${this.editingRecipe.stages.map((stage, i) => html`
            <div class="ha-card form-card pop-in">
                <div class="card-header">
                    <div class="stage-badge">Stage ${i + 1}</div>
                    <div style="display:flex; gap:8px;">
                      <button class="icon-btn" @click=${() => this._moveStage(i, -1)} ?disabled=${i === 0} title="Move Up">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 15l-6-6-6 6"/></svg>
                      </button>
                      <button class="icon-btn" @click=${() => this._moveStage(i, 1)} ?disabled=${i === this.editingRecipe.stages.length - 1} title="Move Down">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                      </button>
                      <button class="icon-btn danger" @click=${() => this._removeStage(i)} title="Remove Stage">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                      </button>
                    </div>
                </div>
                
                <div class="card-content stage-grid-inner">
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
                          <span class="unit">°${this._getGlobalUnit()}</span>
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
                          <span class="unit">°${this._getGlobalUnit()}</span>
                        </div>
                    </div>
                    ` : ''}

                </div>
            </div>
            `)}
            
            ${this.editingRecipe.stages.length === 0 ? html`<div class="empty-state">No stages defined.</div>` : ''}
        </div>
      </div>
    `;
  }


  static get styles() {
    return css`
      /* Switch to Home Assistant Native Theming approach */
      * { box-sizing: border-box; }

      :host {
        display: block;
        min-height: 100vh;
        background-color: var(--primary-background-color, #111111);
        color: var(--primary-text-color, #e1e1e1);
        font-family: var(--paper-font-body1_-_font-family, 'Roboto', 'Noto', sans-serif);
        font-size: 14px;
        line-height: var(--paper-font-body1_-_line-height, 20px);
      }

      .page {
        display: flex;
        flex-direction: column;
        min-height: 100%;
        background-color: var(--primary-background-color);
      }

      .modal-overlay {
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
        backdrop-filter: blur(4px);
      }

      /* Toolbar mimicking HA app-header / Data Table toolbar */
      .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-sizing: border-box;
        padding: 0 16px;
        height: max(var(--header-height), 56px);
        background-color: var(--app-header-background-color, var(--card-background-color, #1e1e1e));
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        color: var(--app-header-text-color, var(--primary-text-color));
      }

      .toolbar-title {
        font-size: 20px;
        font-weight: 400;
        display: flex;
        align-items: center;
      }

      .search-bar {
        position: relative;
        flex: 1;
        display: flex;
        align-items: center;
      }

      .search-icon {
        position: absolute;
        left: 16px;
        width: 20px;
        height: 20px;
        stroke: var(--secondary-text-color, #9e9e9e);
      }

      .search-bar input {
        width: 100%;
        padding: 10px 16px 10px 48px;
        font-size: 14px;
        font-family: inherit;
        background: var(--card-background-color, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 20px;
        color: var(--primary-text-color);
        transition: border-color 0.2s;
      }

      .search-bar input:focus {
        outline: none;
        border-color: var(--primary-color, #03a9f4);
      }

      .action-group {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      /* Buttons (HA Material Style) */
      .mwc-button {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 0 16px;
        height: 36px;
        font-family: inherit;
        font-weight: 500;
        font-size: 14px;
        letter-spacing: 0.0125em;
        text-transform: uppercase;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        background: transparent;
        color: var(--primary-color, #03a9f4);
        transition: background-color 0.2s, box-shadow 0.2s;
      }

      .mwc-button:hover {
        background-color: rgba(3, 169, 244, 0.08); /* Primary color low opacity */
      }

      .mwc-button.primary {
        background-color: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, #ffffff);
        box-shadow: 0 2px 2px 0 rgba(0, 0, 0, 0.14), 0 3px 1px -2px rgba(0, 0, 0, 0.12), 0 1px 5px 0 rgba(0, 0, 0, 0.2);
      }

      .mwc-button.primary:hover {
        background-color: var(--dark-primary-color, #0288d1);
      }
      
      .mwc-button.outline {
          border: 1px solid var(--primary-color, #03a9f4);
      }

      .mwc-button svg {
        width: 18px;
        height: 18px;
      }

      .icon-btn {
        background: transparent;
        border: none;
        color: var(--secondary-text-color, #9e9e9e);
        cursor: pointer;
        padding: 8px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s, color 0.2s;
      }

      .icon-btn svg {
        width: 20px;
        height: 20px;
      }

      .icon-btn:hover {
        background: rgba(255, 255, 255, 0.05);
        color: var(--primary-text-color);
      }

      .icon-btn.danger:hover {
        background: rgba(244, 67, 54, 0.1);
        color: var(--error-color, #f44336);
      }

      .icon-btn.play {
        color: var(--primary-color, #03a9f4);
        background: rgba(3, 169, 244, 0.1);
      }

      .icon-btn.play:hover {
        background: rgba(3, 169, 244, 0.2);
        color: var(--primary-color, #03a9f4);
      }

      .row-actions {
        display: flex;
        justify-content: flex-end;
        gap: 4px;
      }

      /* Data Table */
      .content {
        padding: 0;
      }

      .data-table {
        display: flex;
        flex-direction: column;
        width: 100%;
        background: var(--card-background-color, #1e1e1e);
      }

      .table-header {
        display: flex;
        font-size: 12px;
        font-weight: 500;
        color: var(--secondary-text-color, #9e9e9e);
        padding: 16px 0;
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
      }

      .table-row {
        display: flex;
        align-items: center;
        min-height: 48px;
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        padding: 4px 0;
        transition: background-color 0.2s;
      }

      .table-row:hover {
        background-color: var(--secondary-background-color, rgba(255, 255, 255, 0.03));
      }

      .type-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        background-color: rgba(120, 120, 120, 0.1);
        border-radius: 50%;
        color: var(--secondary-text-color);
      }
      
      .type-icon svg {
          width: 20px;
          height: 20px;
      }

      /* Forms (ha-card mimicking) */
      .ha-card {
        background: var(--card-background-color, #1e1e1e);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0px 2px 1px -1px rgba(0, 0, 0, 0.2), 0px 1px 1px 0px rgba(0, 0, 0, 0.14), 0px 1px 3px 0px rgba(0, 0, 0, 0.12));
        color: var(--primary-text-color);
        margin: 16px;
        display: block;
      }

      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 16px 0 16px;
      }

      .card-content {
        padding: 16px;
      }

      .stages-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        margin: 16px 16px 0 16px;
        border-bottom: 1px solid var(--divider-color);
      }
      
      .stages-header h3 {
          margin: 0;
          font-weight: 500;
      }

      .stage-badge {
        font-weight: 500;
        font-size: 16px;
        color: var(--primary-color);
      }

      .stage-grid-inner {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
      }

      .form-group {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-bottom: 12px;
      }

      .form-group label {
        font-size: 12px;
        color: var(--secondary-text-color, #9e9e9e);
        font-weight: 500;
      }

      input, select {
        padding: 10px 12px;
        background: var(--secondary-background-color, #2b2b2b);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 14px;
        width: 100%;
        box-sizing: border-box;
      }
      
      .hero-input input {
          font-size: 18px;
          padding: 14px 16px;
      }

      input:focus, select:focus {
        outline: none;
        border-color: var(--primary-color);
      }

      input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .unit {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        color: var(--secondary-text-color);
        pointer-events: none;
      }

      .empty-state {
        text-align: center;
        padding: 48px;
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .active-cook-banner {
        display: flex;
        align-items: center;
        background-color: rgba(3, 169, 244, 0.1);
        border-bottom: 1px solid rgba(3, 169, 244, 0.3);
        padding: 16px 24px;
        gap: 16px;
      }
      .banner-icon {
        color: var(--primary-color);
      }
      .banner-text h3 {
        margin: 0 0 4px 0;
        font-size: 16px;
        font-weight: 500;
      }
      .banner-text p {
        margin: 0;
        color: var(--secondary-text-color);
      }

      /* Animations */
      @keyframes slideIn {
        from { opacity: 0; transform: translateY(-4px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes popIn {
        from { opacity: 0; transform: scale(0.98); }
        to { opacity: 1; transform: scale(1); }
      }
      .slide-in {
        animation: slideIn 0.2s ease-out forwards;
      }
      .pop-in {
        animation: popIn 0.2s ease-out forwards;
      }
    `;
  }
}

if (!customElements.get("anova-culinary")) {
  customElements.define("anova-culinary", AnovaCulinary);
}
