class DomylandMetersCard extends HTMLElement {
  setConfig(config) {
    if (!config.meters) throw new Error("domyland-meters-card: укажите meters");
    this._config = { title: "Счётчики: УК и ручной ввод", ...config };
    this._readings = null;
    this._saving = {};
  }

  set hass(hass) {
    this._hass = hass;
    if (this._readings === null) {
      this._load();
      return;
    }
    if (!this.querySelector(":focus")) this._render();
  }

  getCardSize() {
    return (this._config.meters.length || 1) + 2;
  }

  async _load() {
    try {
      this._readings = await this._hass.callWS({
        type: "domyland/manual_readings/list",
      });
    } catch (err) {
      this._readings = {};
    }
    this._render();
  }

  async _save(key, value) {
    this._saving[key] = true;
    try {
      this._readings = await this._hass.callWS({
        type: "domyland/manual_readings/set",
        key,
        value,
      });
    } finally {
      this._saving[key] = false;
      this._render();
    }
  }

  _esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const rows = this._config.meters.map((m) => {
      const st = this._hass.states[m.entity];
      const ukValue = st ? `${st.state} ${st.attributes.unit_of_measurement || ""}` : "—";
      const saved = this._readings && this._readings[m.key];
      const manual = saved ? saved.value : "";
      const savedAt = saved && saved.updated_at
        ? new Date(saved.updated_at * 1000).toLocaleDateString("ru-RU")
        : "";
      return `
        <div class="row">
          <div class="m-name">${this._esc(m.name)}</div>
          <div class="m-uk" title="Данные УК / UJIN">${this._esc(ukValue)}</div>
          <div class="m-manual">
            <input type="number" min="0" step="0.01" data-key="${this._esc(m.key)}"
              value="${manual}" placeholder="—">
            <span class="m-saved">${this._saving[m.key] ? "…" : this._esc(savedAt)}</span>
          </div>
        </div>`;
    }).join("");

    this.innerHTML = `
      <ha-card>
        <style>
          ha-card { padding: 16px; }
          .title { font-size: 1.1em; font-weight: 600; margin-bottom: 8px; }
          .row { display: grid; grid-template-columns: 1.4fr 1fr 1.2fr; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
          .row:last-child { border-bottom: none; }
          .m-uk { color: var(--primary-text-color); white-space: nowrap; }
          .m-manual { display: flex; align-items: center; gap: 8px; }
          .m-manual input { width: 100%; min-width: 70px; padding: 6px 8px; border: 1px solid var(--divider-color); border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
          .m-saved { color: var(--secondary-text-color); font-size: 0.75em; white-space: nowrap; min-width: 62px; }
          .legend { display: grid; grid-template-columns: 1.4fr 1fr 1.2fr; gap: 10px; color: var(--secondary-text-color); font-size: 0.8em; margin-bottom: 4px; }
        </style>
        <div class="title">${this._esc(this._config.title)}</div>
        <div class="legend"><span></span><span>УК / UJIN</span><span>Вручную</span></div>
        ${rows}
      </ha-card>`;

    this.querySelectorAll("input[data-key]").forEach((el) => {
      el.addEventListener("change", () => {
        const value = parseFloat(el.value);
        if (!isNaN(value) && value >= 0) this._save(el.dataset.key, value);
      });
    });
  }
}

customElements.define("domyland-meters-card", DomylandMetersCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "domyland-meters-card",
  name: "Domyland: счётчики УК + ручной ввод",
  description: "Показания счётчиков: данные УК и ручной ввод без отдельных сущностей.",
});
