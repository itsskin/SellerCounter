const FIELD_LABELS = {
  client_id: "Client ID",
  campaign_id: "Campaign ID",
  api_key: "API-ключ",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function fmtMoney(v) {
  return Math.round(v).toLocaleString("ru-RU");
}

function renderConnStatus(state) {
  const badge = document.getElementById("conn-status");
  if (state.mode === "provisioning") {
    badge.textContent = "Режим настройки Wi-Fi";
    badge.className = "badge";
  } else if (state.wifi_connected) {
    badge.textContent = "Онлайн · " + state.ip;
    badge.className = "badge ok";
  } else {
    badge.textContent = "Нет Wi-Fi";
    badge.className = "badge bad";
  }
}

function renderStats(state) {
  const stats = state.stats || { orders: 0, revenue: 0 };
  document.getElementById("stat-orders").textContent = stats.orders;
  document.getElementById("stat-revenue").textContent = fmtMoney(stats.revenue);

  const errBox = document.getElementById("stats-errors");
  const errors = state.errors || {};
  const ids = Object.keys(errors);
  errBox.textContent = ids.length
    ? "Ошибки: " + ids.map((id) => id + " — " + errors[id]).join("; ")
    : "";
}

function renderMarketplaceStats(state) {
  const body = document.getElementById("mp-stats-body");
  const per = state.per_marketplace || {};
  const ids = Object.keys(per);
  if (!ids.length) {
    // Маркетплейсы настроены, просто опрос ещё не случился в этом процессе
    // (например сразу после перезагрузки — см. next_poll_in_sec в
    // web_server.py/stats_engine.py, персистентный троттлинг) — раньше тут
    // всегда писалось "настрой маркетплейсы", даже когда они уже настроены
    // и опрос просто ждёт своей очереди, что вводило в заблуждение.
    const configured = (state.marketplaces || []).length > 0;
    const wait = state.next_poll_in_sec || 0;
    let msg;
    if (!configured) {
      msg = 'Пока нет данных — настрой маркетплейсы ниже или нажми "Обновить сейчас".';
    } else if (wait > 0) {
      msg = `Маркетплейсы настроены, опрос по расписанию через ${wait} с — или нажми "Обновить сейчас".`;
    } else {
      msg = 'Опрашиваю маркетплейсы... — или нажми "Обновить сейчас".';
    }
    body.innerHTML = `<tr><td colspan="4" class="hint">${msg}</td></tr>`;
    return;
  }
  body.innerHTML = ids
    .map((id) => {
      const m = per[id];
      // При ошибке цифры всё равно реальные (последнее успешное значение
      // по каждому магазину площадки, см. stats_engine.py) — раньше тут
      // просто скрывались, теперь показываем и цифры, и что не так, чтобы
      // не выглядело, будто данных вообще нет.
      const rowClass = m.error ? ' class="mp-stats-error"' : "";
      const errorNote = m.error ? `<br><span class="mp-stats-error-note">⚠ ${m.error}</span>` : "";
      return `<tr${rowClass}><td>${m.name}${errorNote}</td><td>${m.orders}</td><td>${fmtMoney(m.revenue)}</td><td>${m.updated_at || ""}</td></tr>`;
    })
    .join("");
}

function renderSettings(state) {
  document.getElementById("set-poll").value = state.poll_interval_sec;
  document.getElementById("set-tz").value = state.timezone_offset_hours;
  document.getElementById("set-beep").checked = !!(state.display && state.display.beep_on_sale);
  document.getElementById("set-yesterday").checked = (state.debug_day_offset || 0) !== 0;
  document.getElementById("set-fbs-reminder").checked = !!(state.display && state.display.show_fbs_reminder);
  document.getElementById("set-fbs-test-label").checked = !!(state.display && state.display.show_fbs_test_label);
  document.getElementById("set-marketplace-breakdown").checked = !!(state.display && state.display.show_marketplace_breakdown);
  document.getElementById("set-mp-total-revenue").checked = !!(state.display && state.display.marketplace_breakdown_show_total_revenue);

  // Чекбокс "выключить звук" — инверсия buzzer.enabled (checked = звук
  // ВЫКЛЮЧЕН). Дефолт enabled=true (см. config.py), так что если поля нет
  // вообще — звук считается включённым, чекбокс не отмечен.
  document.getElementById("set-buzzer-disabled").checked = !!(state.buzzer && state.buzzer.enabled === false);
  // Не инверсия — checked значит "звук при загрузке ВКЛЮЧЁН" (дефолт true).
  document.getElementById("set-boot-sound").checked = !(state.buzzer && state.buzzer.boot_sound === false);
  document.getElementById("set-watchdog-sound").checked = !(state.buzzer && state.buzzer.watchdog_sound === false);

  const volume = (state.buzzer && state.buzzer.volume) || 100;
  document.getElementById("set-volume").value = volume;
  document.getElementById("volume-value").textContent = volume;
  document.getElementById("set-volume-curve").value = (state.buzzer && state.buzzer.volume_curve) || "linear";

  const night = (state.buzzer && state.buzzer.night_mode) || {};
  document.getElementById("set-night-enabled").checked = !!night.enabled;
  document.getElementById("set-night-start").value = night.start || "22:00";
  document.getElementById("set-night-end").value = night.end || "08:00";

  document.getElementById("set-display-driver").value =
    (state.display && state.display.driver) || "epd1in54";

  document.getElementById("set-full-refresh-every").value =
    (state.display && state.display.full_refresh_every) || 50;

  document.getElementById("set-layout-override").value =
    (state.display && state.display.layout_override) || "";

  document.getElementById("ota-current-version").textContent = state.ota_version ?? "?";
}

function collectMarketplaceTestValues() {
  const perMarketplace = {};
  document.querySelectorAll(".mp-test-revenue, .mp-test-orders").forEach((input) => {
    const mpId = input.dataset.mpId;
    if (!input.value) return;
    if (!perMarketplace[mpId]) perMarketplace[mpId] = {};
    const field = input.classList.contains("mp-test-revenue") ? "revenue" : "orders";
    perMarketplace[mpId][field] = Number(input.value);
  });
  return perMarketplace;
}

// Тестовые поля живут только в браузере (per_marketplace-override никогда
// не сохраняется в cfg платы) — без этого любая перерисовка списка
// маркетплейсов (смена порядка, видимости, обновление страницы) стирает
// введённые числа, и их приходится вписывать заново каждый раз.
function mpTestValueStorageKey(mpId, field) {
  return "sc_mp_test_" + mpId + "_" + field;
}

function getStoredMpTestValue(mpId, field) {
  try {
    return localStorage.getItem(mpTestValueStorageKey(mpId, field)) || "";
  } catch (err) {
    return "";
  }
}

function setStoredMpTestValue(mpId, field, value) {
  try {
    if (value) localStorage.setItem(mpTestValueStorageKey(mpId, field), value);
    else localStorage.removeItem(mpTestValueStorageKey(mpId, field));
  } catch (err) {
    // приватный режим/запрет на localStorage — просто не запоминаем между перезагрузками
  }
}

function shopCardHtml(available, shop) {
  const fields = available.required_fields
    .map((field) => {
      const type = field === "api_key" ? "password" : "text";
      const currentVal = shop[field] || (field === "api_key" && shop.api_key_set ? "********" : "");
      return `
        <label>${FIELD_LABELS[field] || field}
          <input type="${type}" name="${field}" placeholder="${currentVal ? "оставить как есть: " + currentVal : "не задано"}">
        </label>`;
    })
    .join("");

  return `
    <div class="mp-card" data-key="${shop.key}">
      <form data-key="${shop.key}">
        <div class="mp-card-head">
          <span class="status ${shop.configured ? "ok" : ""}">${shop.configured ? "активен" : "нет ключей"}</span>
          <button type="button" class="mp-remove-shop">Удалить магазин</button>
        </div>
        ${fields}
        <button type="submit">Сохранить</button>
        <p class="mp-msg msg"></p>
      </form>
    </div>`;
}

function marketplaceTypeHtml(available, shops, breakdownVisible, orderInfo) {
  const cards = shops.map((shop) => shopCardHtml(available, shop)).join("");
  return `
    <div class="mp-type" data-mp-id="${available.id}">
      <div class="mp-type-head">
        <h3>${available.name}</h3>
        <button type="button" class="mp-add-shop">+ Добавить магазин</button>
      </div>
      <div class="mp-breakdown-row">
        <label class="checkbox">
          <input type="checkbox" class="mp-breakdown-visible" data-mp-id="${available.id}" ${breakdownVisible ? "checked" : ""}>
          Отображать на экране детализации
        </label>
        <span class="mp-reorder">
          <button type="button" class="mp-move-up" data-mp-id="${available.id}" ${orderInfo.isFirst ? "disabled" : ""}>▲</button>
          <button type="button" class="mp-move-down" data-mp-id="${available.id}" ${orderInfo.isLast ? "disabled" : ""}>▼</button>
        </span>
      </div>
      <div class="override-row">
        <label>Тест: выручка
          <input type="number" class="mp-test-revenue" data-mp-id="${available.id}" min="0" placeholder="реальная"
            value="${getStoredMpTestValue(available.id, "revenue")}">
        </label>
        <label>Тест: заказы
          <input type="number" class="mp-test-orders" data-mp-id="${available.id}" min="0" placeholder="реальные"
            value="${getStoredMpTestValue(available.id, "orders")}">
        </label>
      </div>
      ${cards || '<p class="hint">Магазинов нет — нажми "+ Добавить магазин".</p>'}
    </div>`;
}

function renderMarketplaces(state) {
  const container = document.getElementById("marketplaces-list");
  container.innerHTML = "";
  const shopsById = {};
  (state.marketplaces || []).forEach((m) => {
    if (!shopsById[m.id]) shopsById[m.id] = [];
    shopsById[m.id].push(m);
  });
  const breakdownVisibleMap = (state.display && state.display.marketplace_breakdown_visible) || {};
  const available = state.marketplaces_available || [];
  const availableById = {};
  available.forEach((a) => (availableById[a.id] = a));

  // Порядок столбиков детализации: сохранённый cfg.display.marketplace_
  // breakdown_order — но только реально существующие id — плюс всё
  // остальное в естественном порядке (marketplaces_available) следом, на
  // случай если порядок настроен не полностью или появился новый маркетплейс.
  const savedOrder = (state.display && state.display.marketplace_breakdown_order) || [];
  const order = savedOrder.filter((id) => availableById[id]);
  available.forEach((a) => {
    if (!order.includes(a.id)) order.push(a.id);
  });

  order.forEach((mpId, i) => {
    const shops = shopsById[mpId] || [];
    const visible = breakdownVisibleMap[mpId] !== false; // нет записи = по умолчанию показан
    const orderInfo = { isFirst: i === 0, isLast: i === order.length - 1 };
    container.insertAdjacentHTML(
      "beforeend", marketplaceTypeHtml(availableById[mpId], shops, visible, orderInfo)
    );
  });

  container.querySelectorAll(".mp-breakdown-visible").forEach((checkbox) => {
    checkbox.addEventListener("change", async (ev) => {
      const mpId = ev.target.dataset.mpId;
      const updated = Object.assign({}, breakdownVisibleMap, { [mpId]: ev.target.checked });
      try {
        await api("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display: { marketplace_breakdown_visible: updated } }),
        });
        await api("/api/display/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ per_marketplace: collectMarketplaceTestValues() }),
        });
        refreshPreview();
      } catch (err) {
        ev.target.checked = !ev.target.checked;
        alert("Ошибка: " + err.message);
      }
    });
  });

  async function moveMarketplace(mpId, delta) {
    const idx = order.indexOf(mpId);
    const swapWith = idx + delta;
    if (swapWith < 0 || swapWith >= order.length) return;
    const newOrder = order.slice();
    [newOrder[idx], newOrder[swapWith]] = [newOrder[swapWith], newOrder[idx]];
    try {
      await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display: { marketplace_breakdown_order: newOrder } }),
      });
      // Сразу перерисовываем — иначе новый порядок виден на экране только
      // после следующего обычного опроса/изменения продаж. Подставляем те
      // же тестовые значения, что уже могли быть введены в полях выше —
      // иначе смена порядка молча сбросила бы тестовое превью на реальные
      // данные.
      await api("/api/display/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ per_marketplace: collectMarketplaceTestValues() }),
      });
      refreshPreview();
      loadState(true);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  container.querySelectorAll(".mp-move-up").forEach((btn) => {
    btn.addEventListener("click", () => moveMarketplace(btn.dataset.mpId, -1));
  });
  container.querySelectorAll(".mp-move-down").forEach((btn) => {
    btn.addEventListener("click", () => moveMarketplace(btn.dataset.mpId, 1));
  });

  container.querySelectorAll(".mp-test-revenue, .mp-test-orders").forEach((input) => {
    input.addEventListener("input", () => {
      const field = input.classList.contains("mp-test-revenue") ? "revenue" : "orders";
      setStoredMpTestValue(input.dataset.mpId, field, input.value);
    });
  });

  container.querySelectorAll("form[data-key]").forEach((form) => {
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const key = form.dataset.key;
      const msg = form.querySelector(".mp-msg");
      const fd = new FormData(form);
      const body = {};
      for (const [k, val] of fd.entries()) {
        if (val) body[k] = val;
      }
      try {
        await api("/api/shops/" + key, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        msg.textContent = "Сохранено";
        msg.classList.remove("error");
      } catch (err) {
        msg.textContent = "Ошибка сохранения: " + err.message;
        msg.classList.add("error");
      }
      loadState(true);
    });
  });

  container.querySelectorAll(".mp-remove-shop").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.closest("form").dataset.key;
      if (!confirm("Удалить этот магазин? Ключи не восстановить.")) return;
      try {
        await api("/api/shops/" + key + "/remove", { method: "POST" });
      } catch (err) {
        alert("Ошибка удаления: " + err.message);
      }
      loadState(true);
    });
  });

  container.querySelectorAll(".mp-add-shop").forEach((button) => {
    button.addEventListener("click", async () => {
      const mpId = button.closest(".mp-type").dataset.mpId;
      try {
        await api("/api/marketplaces/" + mpId + "/add", { method: "POST" });
      } catch (err) {
        alert("Ошибка добавления: " + err.message);
      }
      loadState(true);
    });
  });
}

function fmtSize(bytes) {
  return bytes < 1024 ? bytes + " Б" : (bytes / 1024).toFixed(1) + " КБ";
}

function notificationRowHtml(file, selected) {
  const disabled = !file.playable;
  return `
    <div class="notif-row ${disabled ? "disabled" : ""}" data-filename="${file.filename}">
      <label>
        <span>
          <input type="radio" name="notification_sound" value="${file.filename}"
            ${file.filename === selected ? "checked" : ""} ${disabled ? "disabled" : ""}>
          ${file.filename}
        </span>
        <span class="notif-meta">${fmtSize(file.size)}${disabled ? " — нужна конвертация в .wav (см. подсказку выше)" : ""}</span>
      </label>
      <button type="button" class="notif-test" ${disabled ? "disabled" : ""}>▶ Тест</button>
    </div>`;
}

// Кэш последнего /api/notifications и списка маркетплейсов (из /api/state)
// — оба нужны вместе, чтобы построить #mp-sounds-list (имя маркетплейса +
// файлы), а приходят из двух разных периодических запросов.
let notificationsCache = null;
let marketplacesAvailableCache = null;

async function loadNotifications() {
  const data = await api("/api/notifications");
  notificationsCache = data;
  const container = document.getElementById("notifications-list");
  container.innerHTML = "";
  if (!data.files.length) {
    container.innerHTML = '<p class="hint">В /notifications/ пока нет файлов.</p>';
  } else {
    data.files.forEach((file) => {
      container.insertAdjacentHTML("beforeend", notificationRowHtml(file, data.selected));
    });

    const msg = document.getElementById("notifications-msg");

    container.querySelectorAll('input[name="notification_sound"]').forEach((radio) => {
      radio.addEventListener("change", async () => {
        try {
          await api("/api/notifications/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: radio.value }),
          });
          msg.textContent = "Выбрано: " + radio.value;
          msg.classList.remove("error");
        } catch (err) {
          msg.textContent = "Ошибка: " + err.message;
          msg.classList.add("error");
        }
        setTimeout(() => (msg.textContent = ""), 3000);
      });
    });

    container.querySelectorAll(".notif-test").forEach((button) => {
      button.addEventListener("click", async () => {
        const filename = button.closest(".notif-row").dataset.filename;
        button.disabled = true;
        msg.textContent = "Играю " + filename + "...";
        try {
          await api("/api/notifications/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename }),
          });
        } catch (err) {
          msg.textContent = "Ошибка: " + err.message;
        } finally {
          button.disabled = false;
        }
        setTimeout(() => (msg.textContent = ""), 3000);
      });
    });
  }

  renderMpSounds();
}

function renderMpSounds() {
  const container = document.getElementById("mp-sounds-list");
  if (!notificationsCache || !marketplacesAvailableCache) return;

  const playable = notificationsCache.files.filter((f) => f.playable);
  const selectedByMp = notificationsCache.selected_by_marketplace || {};

  if (!playable.length) {
    container.innerHTML = '<p class="hint">Нет доступных для игры файлов (см. список выше).</p>';
    return;
  }

  container.innerHTML = marketplacesAvailableCache
    .map((mp) => {
      const current = selectedByMp[mp.id] || "";
      const options =
        '<option value="">— по умолчанию —</option>' +
        playable
          .map(
            (f) =>
              `<option value="${f.filename}" ${f.filename === current ? "selected" : ""}>${f.filename}</option>`
          )
          .join("");
      return `
        <div class="notif-row" data-mp-id="${mp.id}">
          <label>
            <span>${mp.name}</span>
            <select class="mp-sound-select">${options}</select>
          </label>
          <button type="button" class="mp-sound-test">▶ Тест</button>
        </div>`;
    })
    .join("");

  const msg = document.getElementById("notifications-msg");

  container.querySelectorAll(".notif-row[data-mp-id]").forEach((row) => {
    const select = row.querySelector(".mp-sound-select");

    const testButton = row.querySelector(".mp-sound-test");
    testButton.addEventListener("click", async () => {
      const filename = select.value || notificationsCache.selected;
      if (!filename) return;
      // Сервер и так сериализует воспроизведение (см. buzzer.py
      // _playback_lock) — это просто чтобы не копилась очередь из кликов,
      // пока играет текущая мелодия.
      testButton.disabled = true;
      msg.textContent = "Играю " + filename + "...";
      try {
        await api("/api/notifications/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename }),
        });
      } catch (err) {
        msg.textContent = "Ошибка: " + err.message;
        msg.classList.add("error");
      } finally {
        testButton.disabled = false;
      }
      setTimeout(() => (msg.textContent = ""), 3000);
    });
  });
}

// Формы (Wi-Fi SSID, настройки, маркетплейсы) перестраиваются из ответа
// сервера только один раз при загрузке страницы и сразу после явного
// сохранения — а не на каждом периодическом опросе (иначе перезаписывание
// поля во время ввода стирает то, что печатает пользователь).
let formsReady = false;

function fmtClock(date) {
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function loadState(forceFormRefresh) {
  const state = await api("/api/state");
  renderConnStatus(state);
  renderStats(state);
  renderMarketplaceStats(state);
  document.getElementById("page-updated").textContent =
    "Страница обновляется сама · последний раз в " + fmtClock(new Date());

  if (state.display_width && state.display_height) {
    document.getElementById("bg-size").textContent = state.display_width + "x" + state.display_height;
  }

  if (!formsReady || forceFormRefresh) {
    renderSettings(state);
    renderMarketplaces(state);
    document.getElementById("wifi-ssid").value = state.wifi_ssid || "";
    marketplacesAvailableCache = state.marketplaces_available || marketplacesAvailableCache;
    renderMpSounds();
    formsReady = true;
  }
}

function refreshPreview() {
  const img = document.getElementById("preview-img");
  img.src = "/api/display/preview.bmp?t=" + Date.now();
}

document.getElementById("wifi-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  await api("/api/wifi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ssid: fd.get("ssid"), password: fd.get("password") }),
  });
  document.getElementById("wifi-msg").textContent = "Сохранено, плата перезагружается...";
});

document.getElementById("settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      poll_interval_sec: Number(fd.get("poll_interval_sec")),
      timezone_offset_hours: Number(fd.get("timezone_offset_hours")),
      debug_day_offset: fd.get("show_yesterday") === "on" ? -1 : 0,
      display: {
        beep_on_sale: fd.get("beep_on_sale") === "on",
      },
    }),
  });
  document.getElementById("settings-msg").textContent = "Сохранено";
  setTimeout(() => (document.getElementById("settings-msg").textContent = ""), 2000);
  loadState(true);
});

document.getElementById("display-driver-save").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("display-driver-msg");
  const driver = document.getElementById("set-display-driver").value;
  button.disabled = true;
  msg.classList.remove("error");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { driver } }),
    });
    await api("/api/reboot", { method: "POST" });
    msg.textContent = "Сохранено, плата перезагружается...";
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
    button.disabled = false;
  }
});

document.getElementById("set-full-refresh-every").addEventListener("change", async (ev) => {
  const msg = document.getElementById("full-refresh-every-msg");
  const value = Number(ev.target.value) || 50;
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { full_refresh_every: value } }),
    });
    msg.textContent = "Сохранено";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("preview-refresh").addEventListener("click", refreshPreview);

document.getElementById("override-apply").addEventListener("click", async () => {
  const orders = Number(document.getElementById("override-orders").value) || 0;
  const revenue = Number(document.getElementById("override-revenue").value) || 0;
  const msg = document.getElementById("override-msg");

  msg.textContent = "Рисую на экране (это медленно, ~20с — реальное обновление e-paper)...";
  msg.classList.remove("error");
  try {
    // Сырой fetch, не api() — при ошибке (не 2xx) нужен текст из тела
    // ответа ({ok:false, error}), а api() на не-2xx просто бросает без
    // разбора тела.
    const res = await fetch("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orders, revenue }),
    });
    const data = await res.json();
    if (data.ok) {
      msg.textContent = "Готово";
      refreshPreview();
    } else {
      msg.textContent = "Ошибка: " + (data.error || "");
      msg.classList.add("error");
    }
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 4000);
});

document.getElementById("bg-upload").addEventListener("click", async () => {
  const fileInput = document.getElementById("bg-file");
  const msg = document.getElementById("bg-msg");
  const file = fileInput.files[0];
  if (!file) {
    msg.textContent = "Сначала выбери файл";
    msg.classList.add("error");
    return;
  }

  msg.textContent = "Загружаю и конвертирую...";
  msg.classList.remove("error");
  try {
    // Тело запроса — сырые байты файла (не FormData/multipart) — так
    // проще на плате, см. web_server.py /api/background.
    const res = await fetch("/api/background", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    const data = await res.json();
    if (data.ok) {
      msg.textContent = "Фон обновлён";
      fileInput.value = "";
      refreshPreview();
    } else {
      msg.textContent = "Ошибка: " + (data.error || res.status);
      msg.classList.add("error");
    }
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
});

document.getElementById("stats-refresh").addEventListener("click", async () => {
  const msg = document.getElementById("stats-msg");
  msg.textContent = "Опрашиваю маркетплейсы...";
  try {
    await api("/api/refresh", { method: "POST" });
    await loadState(false);
    refreshPreview();
    msg.textContent = "Обновлено";
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
  }
  setTimeout(() => (msg.textContent = ""), 4000);
});

const volumeSlider = document.getElementById("set-volume");
const volumeValue = document.getElementById("volume-value");
volumeSlider.addEventListener("input", () => {
  volumeValue.textContent = volumeSlider.value;
});
volumeSlider.addEventListener("change", async () => {
  const msg = document.getElementById("notifications-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { volume: Number(volumeSlider.value) } }),
    });
    msg.textContent = "Громкость сохранена: " + volumeSlider.value + "%";
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-volume-curve").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { volume_curve: ev.target.value } }),
    });
    msg.textContent = "Кривая громкости сохранена";
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

async function saveNightMode() {
  const msg = document.getElementById("notifications-msg");
  const night = {
    enabled: document.getElementById("set-night-enabled").checked,
    start: document.getElementById("set-night-start").value || "22:00",
    end: document.getElementById("set-night-end").value || "08:00",
  };
  try {
    // night_mode целиком заменяется на сервере (buzzer.update — не deep
    // merge), поэтому шлём все три поля разом, а не только то, что
    // поменялось.
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { night_mode: night } }),
    });
    msg.textContent = "Ночной режим сохранён";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
}

document.getElementById("set-night-enabled").addEventListener("change", saveNightMode);
document.getElementById("set-night-start").addEventListener("change", saveNightMode);
document.getElementById("set-night-end").addEventListener("change", saveNightMode);

document.getElementById("set-buzzer-disabled").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    // Инверсия: чекбокс "выключить" checked=true -> buzzer.enabled=false.
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { enabled: !ev.target.checked } }),
    });
    msg.textContent = ev.target.checked ? "Звук выключен" : "Звук включён";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-boot-sound").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    // Не инверсия — checked=true значит boot_sound=true.
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { boot_sound: ev.target.checked } }),
    });
    msg.textContent = "Сохранено — применится со следующей загрузки";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-watchdog-sound").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    // Не инверсия — checked=true значит watchdog_sound=true.
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buzzer: { watchdog_sound: ev.target.checked } }),
    });
    msg.textContent = "Сохранено — применится со следующего watchdog-сброса";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-marketplace-breakdown").addEventListener("change", async (ev) => {
  const msg = document.getElementById("marketplace-breakdown-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { show_marketplace_breakdown: ev.target.checked } }),
    });
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ per_marketplace: collectMarketplaceTestValues() }),
    });
    msg.textContent = "Сохранено и перерисовано";
    msg.classList.remove("error");
    refreshPreview();
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-mp-total-revenue").addEventListener("change", async (ev) => {
  const msg = document.getElementById("mp-total-revenue-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { marketplace_breakdown_show_total_revenue: ev.target.checked } }),
    });
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ per_marketplace: collectMarketplaceTestValues() }),
    });
    msg.textContent = "Сохранено и перерисовано";
    msg.classList.remove("error");
    refreshPreview();
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("mp-breakdown-test-apply").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("mp-breakdown-test-msg");
  const perMarketplace = collectMarketplaceTestValues();
  button.disabled = true;
  msg.classList.remove("error");
  try {
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ per_marketplace: perMarketplace }),
    });
    msg.textContent = "Показано на экране";
    refreshPreview();
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  button.disabled = false;
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-fbs-reminder").addEventListener("change", async (ev) => {
  const msg = document.getElementById("fbs-reminder-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { show_fbs_reminder: ev.target.checked } }),
    });
    msg.textContent = "Сохранено";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-fbs-test-label").addEventListener("change", async (ev) => {
  const msg = document.getElementById("fbs-test-label-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { show_fbs_test_label: ev.target.checked } }),
    });
    // Сразу перерисовываем — иначе эффект отладочного чекбокса виден
    // только после следующего опроса/изменения продаж.
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    msg.textContent = "Сохранено и перерисовано";
    msg.classList.remove("error");
    refreshPreview();
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-layout-override").addEventListener("change", async (ev) => {
  const msg = document.getElementById("layout-override-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { layout_override: ev.target.value } }),
    });
    // Сразу перерисовываем экран текущими данными — без этого пришлось бы
    // ждать следующего изменения заказов/выручки, чтобы увидеть эффект.
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    msg.textContent = "Сохранено и перерисовано";
    msg.classList.remove("error");
    refreshPreview();
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

async function loadLayoutText() {
  const textarea = document.getElementById("layout-text");
  const msg = document.getElementById("layout-text-msg");
  try {
    const res = await api("/api/layout/text");
    textarea.value = res.text;
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка загрузки: " + err.message;
    msg.classList.add("error");
  }

  const fontsEl = document.getElementById("layout-fonts-list");
  try {
    const res = await api("/api/layout/fonts");
    fontsEl.textContent = res.fonts.join(", ");
  } catch (err) {
    fontsEl.textContent = "не удалось получить список: " + err.message;
  }
}

document.getElementById("layout-text-reload").addEventListener("click", loadLayoutText);

document.getElementById("layout-text-apply").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("layout-text-msg");
  const text = document.getElementById("layout-text").value;
  button.disabled = true;
  msg.classList.remove("error");
  try {
    const res = await api("/api/layout/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.redraw_error) {
      msg.textContent = "Сохранено, но перерисовать не вышло: " + res.redraw_error;
      msg.classList.add("error");
    } else {
      msg.textContent = "Сохранено и перерисовано";
      refreshPreview();
      setTimeout(() => (msg.textContent = ""), 3000);
    }
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  button.disabled = false;
});

document.getElementById("mp-sounds-save").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("notifications-msg");
  const rows = document.querySelectorAll("#mp-sounds-list .notif-row[data-mp-id]");
  button.disabled = true;
  msg.classList.remove("error");
  msg.textContent = "Сохраняю...";
  notificationsCache.selected_by_marketplace = notificationsCache.selected_by_marketplace || {};
  try {
    // По одному по очереди, не Promise.all — на плате один HTTP-воркер,
    // параллельные запросы просто встанут в очередь сами, но так виднее
    // порядок в случае ошибки на каком-то конкретном маркетплейсе.
    for (const row of rows) {
      const mpId = row.dataset.mpId;
      const filename = row.querySelector(".mp-sound-select").value;
      await api("/api/notifications/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, marketplace_id: mpId }),
      });
      if (filename) {
        notificationsCache.selected_by_marketplace[mpId] = filename;
      } else {
        delete notificationsCache.selected_by_marketplace[mpId];
      }
    }
    msg.textContent = "Сохранено";
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  } finally {
    button.disabled = false;
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("ota-check").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("ota-msg");
  const applyButton = document.getElementById("ota-apply");
  button.disabled = true;
  applyButton.hidden = true;
  msg.classList.remove("error");
  msg.textContent = "Проверяю обновления...";
  try {
    const res = await fetch("/api/ota/check", { method: "POST" });
    const data = await res.json();
    if (!data.ok) {
      msg.textContent = "Ошибка: " + (data.error || res.status);
      msg.classList.add("error");
    } else if (data.update_available) {
      msg.textContent = "Доступно обновление: версия " + data.available_version +
        " (сейчас " + data.current_version + "), источник: " + data.source;
      applyButton.hidden = false;
    } else {
      msg.textContent = "Обновлений нет — установлена последняя версия (" + data.current_version + ")";
    }
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  } finally {
    button.disabled = false;
  }
});

document.getElementById("ota-apply").addEventListener("click", async (ev) => {
  const button = ev.target;
  const checkButton = document.getElementById("ota-check");
  const msg = document.getElementById("ota-msg");
  button.disabled = true;
  checkButton.disabled = true;
  msg.classList.remove("error");
  msg.textContent = "Скачиваю и проверяю файлы обновления — это может занять минуту, не выключай плату...";
  try {
    const res = await fetch("/api/ota/apply", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      msg.textContent = "Обновлено до версии " + data.new_version + " — плата перезагружается...";
      button.hidden = true;
      setTimeout(() => location.reload(), 8000);
    } else {
      msg.textContent = "Ошибка: " + (data.error || res.status);
      msg.classList.add("error");
      button.disabled = false;
      checkButton.disabled = false;
    }
  } catch (err) {
    // Само соединение может оборваться при перезагрузке платы уже ПОСЛЕ
    // того как файлы применились — это не обязательно ошибка обновления.
    msg.textContent = "Соединение прервано (возможно, плата уже перезагружается) — обнови страницу через полминуты.";
    checkButton.disabled = false;
  }
});

loadState(true);
loadNotifications();
loadLayoutText();
refreshPreview();
setInterval(() => loadState(false), 30000);
setInterval(refreshPreview, 30000);
