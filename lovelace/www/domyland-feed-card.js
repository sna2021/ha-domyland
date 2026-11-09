class DomylandFeedCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("domyland-feed-card: укажите entity");
    this._config = { title: "Лента уведомлений ЖКХ", page_size: 5, ...config };
    this._source = config.source === "news" ? "news" : "notifications";
    this._page = 0;
    this._selected = null;
    this._detail = null;
    this._detailLoading = false;
    this._detailError = false;
  }

  set hass(hass) {
    this._hass = hass;
    const sig = JSON.stringify([
      this._entity ? this._entity.state : null,
      this._items,
      this._selected,
      this._detail,
      this._detailLoading,
      this._page,
    ]);
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
  }

  getCardSize() {
    return 4;
  }

  get _entity() {
    return this._hass.states[this._config.entity];
  }

  get _items() {
    return (this._entity && this._entity.attributes[this._source]) || [];
  }

  _esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  _escAttr(text) {
    return this._esc(text).replace(/"/g, "&quot;");
  }

  async _openDetail(item) {
    this._selected = item;
    this._detail = null;
    this._detailError = false;
    this._detailLoading = true;
    this._render();
    try {
      this._detail = await this._hass.callWS({
        type:
          this._source === "news"
            ? "domyland/news_detail"
            : "domyland/notification_detail",
        [this._source === "news" ? "news_id" : "notification_id"]: item.id,
      });
    } catch (err) {
      this._detailError = true;
    } finally {
      this._detailLoading = false;
      this._render();
    }
  }

  _closeDetail() {
    this._selected = null;
    this._detail = null;
    this._render();
  }

  _turnPage(delta) {
    const pages = Math.max(1, Math.ceil(this._items.length / this._config.page_size));
    this._page = Math.min(Math.max(0, this._page + delta), pages - 1);
    this._render();
  }

  _renderList() {
    const items = this._items;
    const size = this._config.page_size;
    const pages = Math.max(1, Math.ceil(items.length / size));
    this._page = Math.min(this._page, pages - 1);
    const visible = items.slice(this._page * size, this._page * size + size);
    if (!items.length) {
      return `<div class="empty">Лента пуста</div>`;
    }
    return `
      <div class="list">
        ${visible.map((n, i) => `
          <div class="item" data-index="${this._page * size + i}" role="button" tabindex="0">
            <div class="item-head">
              <span class="item-title">${this._esc(n.title)}</span>
              ${n.is_viewed ? "" : '<span class="dot" title="Новое"></span>'}
            </div>
            <div class="item-date">${this._esc(n.date || "")}</div>
            <div class="item-preview">${this._esc(n.preview || "")}</div>
          </div>`).join("")}
      </div>
      <div class="pager">
        <button class="pg-btn" data-delta="-1" ${this._page === 0 ? "disabled" : ""}>‹ Назад</button>
        <span class="pg-info">${this._page + 1} / ${pages}</span>
        <button class="pg-btn" data-delta="1" ${this._page >= pages - 1 ? "disabled" : ""}>Вперёд ›</button>
      </div>`;
  }

  _renderModal() {
    if (!this._selected) return "";
    const n = this._selected;
    const d = this._detail || {};
    const html = d.body || d.text || d.content;
    let body;
    if (this._detailLoading) {
      body = '<div class="note">Загрузка…</div>';
    } else if (html) {
      body = `<iframe class="doc" sandbox="" srcdoc="${this._escAttr(html)}"></iframe>`;
    } else {
      body = `<div class="detail-text">${this._esc(n.preview || "")}</div>
        ${this._detailError ? '<div class="note">Полный текст не загрузился, показано превью.</div>' : ""}`;
    }
    if (!this._detailLoading) {
      const images = d.images || [];
      if (images.length) {
        body += `<div class="attachments">${images
          .map((img) => {
            const url = img.url || img.image || img.src || img;
            return `<a href="${this._escAttr(url)}" target="_blank" rel="noopener">
              <img class="attachment-img" src="${this._escAttr(url)}" loading="lazy">
            </a>`;
          })
          .join("")}</div>`;
      }
      const files = d.files || [];
      if (files.length) {
        body += `<div class="attachments">${files
          .map(
            (f) => `<a class="attachment-file" href="${this._escAttr(f.url)}" target="_blank" rel="noopener">
              <span class="file-icon">📄</span>
              <span class="file-name">${this._esc(f.originalName || f.name)}</span>
              <span class="file-sub">${this._esc(f.subtitle || "")}</span>
            </a>`
          )
          .join("")}</div>`;
      }
    }
    return `
      <div class="overlay">
        <div class="modal" role="dialog" aria-modal="true">
          <div class="modal-head">
            <span class="item-title">${this._esc(d.title || n.title)}</span>
            <button class="close" title="Закрыть">✕</button>
          </div>
          <div class="item-date">${this._esc(n.date || "")}</div>
          <div class="modal-body">${body}</div>
        </div>
      </div>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const unread = this._entity ? this._entity.state : "?";
    this.innerHTML = `
      <ha-card>
        <style>
          ha-card { padding: 16px; }
          .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
          .head .title { font-size: 1.1em; font-weight: 600; }
          .badge { background: var(--primary-color); color: var(--text-primary-color); border-radius: 12px; padding: 1px 10px; font-size: 0.85em; }
          .item { padding: 10px 4px; border-bottom: 1px solid var(--divider-color); cursor: pointer; }
          .item:last-child { border-bottom: none; }
          .item:hover { background: var(--secondary-background-color); }
          .item-head { display: flex; align-items: center; gap: 8px; }
          .item-title { font-weight: 600; }
          .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary-color); flex: none; }
          .item-date { color: var(--secondary-text-color); font-size: 0.85em; margin: 2px 0 4px; }
          .item-preview { color: var(--secondary-text-color); font-size: 0.95em; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
          .pager { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
          .pg-btn, .close { background: none; border: none; color: var(--primary-color); cursor: pointer; font: inherit; padding: 6px 8px; }
          .pg-btn:disabled { color: var(--disabled-text-color); cursor: default; }
          .pg-info { color: var(--secondary-text-color); font-size: 0.9em; }
          .empty, .note { color: var(--secondary-text-color); }
          .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 1000; display: flex; align-items: center; justify-content: center; }
          .modal { background: var(--card-background-color); color: var(--primary-text-color); border-radius: 12px; width: 92vw; max-width: 760px; max-height: 88vh; display: flex; flex-direction: column; padding: 16px 20px; box-shadow: 0 8px 32px rgba(0,0,0,.35); }
          .modal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
          .close { font-size: 1.1em; }
          .modal-body { overflow: auto; margin-top: 10px; }
          .doc { width: 100%; height: 62vh; border: none; background: #fff; border-radius: 6px; }
          .detail-text { white-space: pre-wrap; line-height: 1.5; }
          .attachments { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
          .attachment-img { max-width: 100%; border-radius: 6px; display: block; }
          .attachment-file { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--divider-color); border-radius: 8px; text-decoration: none; color: var(--primary-text-color); }
          .attachment-file:hover { background: var(--secondary-background-color); }
          .file-icon { font-size: 1.3em; }
          .file-name { flex: 1; overflow-wrap: anywhere; }
          .file-sub { color: var(--secondary-text-color); font-size: 0.85em; white-space: nowrap; }
        </style>
        <div class="head">
          <span class="title">${this._esc(this._config.title)}</span>
          <span class="badge" title="Непрочитанных">${this._esc(unread)}</span>
        </div>
        ${this._renderList()}
        ${this._renderModal()}
      </ha-card>`;

    this.querySelectorAll(".item").forEach((el) => {
      el.addEventListener("click", () => {
        this._openDetail(this._items[Number(el.dataset.index)]);
      });
    });
    this.querySelectorAll(".pg-btn").forEach((el) => {
      el.addEventListener("click", () => this._turnPage(Number(el.dataset.delta)));
    });
    const overlay = this.querySelector(".overlay");
    if (overlay) {
      overlay.addEventListener("click", (ev) => {
        if (ev.target === overlay) this._closeDetail();
      });
      this.querySelector(".close").addEventListener("click", () => this._closeDetail());
      if (!this._escHandler) {
        this._escHandler = (ev) => {
          if (ev.key === "Escape") this._closeDetail();
        };
        document.addEventListener("keydown", this._escHandler);
      }
    } else if (this._escHandler) {
      document.removeEventListener("keydown", this._escHandler);
      this._escHandler = null;
    }
  }
}

customElements.define("domyland-feed-card", DomylandFeedCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "domyland-feed-card",
  name: "Domyland: лента уведомлений",
  description: "Лента уведомлений ЖКХ: список с пагинацией и модальный детальный вид.",
});
