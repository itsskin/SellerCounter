// Упрощённая версия www/app.js для www/main.html (открывается по /) — те же
// /api/* эндпоинты и то же состояние на плате, что и основной интерфейс,
// поэтому оба работают параллельно без конфликтов. Урезаны только разделы
// "Фон экрана" и "Настройки" (техническая настройка экрана/раскладки/сети
// опроса — не для повседневного использования) и тестовые поля
// маркетплейсов (Тест: выручка/заказы/FBS) — их тут просто нет в разметке.

const FIELD_LABELS = {
  client_id: "Client ID",
  campaign_id: "Campaign ID",
  api_key: "API-ключ",
};

// Ссылки «как получить ключи» по маркетплейсам.
// Якоря ведут в раздел «Подключение маркетплейсов» инструкции (/start/), сразу к нужному
// маркетплейсу. Страница /start/ и её якоря (#ozon, #wildberries, #yandex-market) менять нельзя.
const TUTORIAL_URLS = {
  ozon: "https://monik.u-bix.ru/start/#ozon",
  wb: "https://monik.u-bix.ru/start/#wildberries",
  yandex: "https://monik.u-bix.ru/start/#yandex-market",
};

// Ссылка на полный туториал «Как настроить?» (верхнее меню). Тот же адрес зашит в
// QR «ИНСТРУКЦИЯ» на заставке (display/start_screen_400x300.bin) — менять нельзя.
const HELP_URL = "https://monik.u-bix.ru/start/";

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function fmtMoney(v) {
  return Math.round(v).toLocaleString("ru-RU");
}

function fmtClock(date) {
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderConnStatus(state) {
  const badge = document.getElementById("conn-status");
  if (state.mode === "provisioning") {
    badge.textContent = "Режим настройки Wi-Fi";
    badge.className = "badge";
    delete badge.dataset.ip;
    badge.title = "";
  } else if (state.wifi_connected) {
    badge.textContent = "Онлайн · " + state.ip;
    badge.className = "badge ok";
    badge.dataset.ip = state.ip;
    badge.title = "Нажмите, чтобы скопировать адрес";
  } else {
    badge.textContent = "Нет Wi-Fi";
    badge.className = "badge bad";
    delete badge.dataset.ip;
    badge.title = "";
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
      const rowClass = m.error ? ' class="mp-stats-error"' : "";
      const errorNote = m.error ? `<br><span class="mp-stats-error-note">⚠ ${m.error}</span>` : "";
      return `<tr${rowClass}><td>${m.name}${errorNote}</td><td>${m.orders}</td><td>${fmtMoney(m.revenue)}</td><td>${m.updated_at || ""}</td></tr>`;
    })
    .join("");
}

function renderSettings(state) {
  document.getElementById("set-beep").checked = !!(state.display && state.display.beep_on_sale);
  document.getElementById("set-visual-alert").checked = !!(state.display && state.display.visual_alert);
  document.getElementById("set-fbs-reminder").checked = !!(state.display && state.display.show_fbs_reminder);
  const breakdownOn = !!(state.display && state.display.show_marketplace_breakdown);
  document.getElementById("mode-breakdown").checked = breakdownOn;
  document.getElementById("mode-total").checked = !breakdownOn;

  document.getElementById("set-buzzer-disabled").checked = !!(state.buzzer && state.buzzer.enabled === false);
  document.getElementById("set-boot-sound").checked = !(state.buzzer && state.buzzer.boot_sound === false);

  const volume = (state.buzzer && state.buzzer.volume) ?? 100;
  document.getElementById("set-volume").value = volume;
  document.getElementById("volume-value").textContent = volume;

  const night = (state.buzzer && state.buzzer.night_mode) || {};
  document.getElementById("set-night-enabled").checked = !!night.enabled;
  document.getElementById("set-night-start").value = night.start || "22:00";
  document.getElementById("set-night-end").value = night.end || "08:00";

  document.getElementById("ota-current-version").textContent = state.ota_version ?? "?";
  const autoUpdate = state.auto_update || { enabled: true, hour: 4 };
  document.getElementById("set-auto-update").checked = !!autoUpdate.enabled;
  document.getElementById("set-auto-update-hour").value = autoUpdate.hour ?? 4;
}

let shopVisibleFromState = {};

function shopCardHtml(available, shop, showVisibilityToggle) {
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

  // У «пустого» магазина (ключа ещё нет, он заводится при первом
  // сохранении) нет смысла в кнопке удаления.
  const removeButton = shop.key
    ? '<button type="button" class="mp-remove-shop">Удалить магазин</button>'
    : "";

  return `
    <div class="mp-card" data-key="${shop.key}">
      <form data-key="${shop.key}">
        <div class="mp-card-head">
          <span class="status ${shop.configured ? "ok" : ""}">${shop.configured ? "подключён" : "ключи не введены"}</span>
          ${removeButton}
        </div>
        ${fields}
        <button type="submit">Сохранить</button>
        <p class="mp-msg msg"></p>
      </form>
    </div>`;
}

// После сохранения/удаления магазина сразу обновляем экран устройства — иначе
// заставка первого запуска (или обычный экран) сменится только на следующем цикле
// опроса, до 5 минут. Ошибку опроса (например, неверный ключ) не показываем здесь:
// она видна в блоке статистики.
function refreshAfterShopChange() {
  api("/api/refresh", { method: "POST" })
    .then(() => loadState(false))
    .catch(() => {});
}

function tutorialLinkHtml(mpId) {
  const url = TUTORIAL_URLS[mpId] || "#";
  // Пока адреса нет ("#") — клик ничего не делает, чтобы страница не прыгала наверх.
  const attrs = url === "#" ? 'onclick="return false"' : 'target="_blank" rel="noopener"';
  return `<a class="pill-link" href="${url}" ${attrs}>Как получить ключи ›</a>`;
}

// Маркетплейс — раскрывающаяся вкладка (<details>). Первый магазин вводится
// сразу, без кнопки «Добавить»: пока магазинов нет, показываем пустую форму
// (key пустой — запись заводится при первом сохранении, см. обработчик submit).
function marketplaceTypeHtml(available, shops, breakdownVisible, orderInfo, isOpen) {
  const configuredCount = shops.filter((s) => s.configured).length;
  const badge = configuredCount
    ? `<span class="acc-badge ok">подключён${configuredCount > 1 ? " · " + configuredCount : ""}</span>`
    : '<span class="acc-badge">не подключён</span>';
  const list = shops.length ? shops : [{ key: "", configured: false, api_key_set: false }];
  const cards = list.map((shop) => shopCardHtml(available, shop, shops.length > 1)).join("");
  const addButton = shops.length
    ? '<button type="button" class="mp-add-shop">+ Добавить ещё один магазин</button>'
    : "";
  return `
    <details class="mp-type acc" data-mp-id="${available.id}" ${isOpen ? "open" : ""}>
      <summary>${available.name} ${badge}</summary>
      <div class="acc-body">
        ${tutorialLinkHtml(available.id)}
        <div class="mp-breakdown-row">
          <span class="mp-order-label">Порядок столбиков на экране</span>
          <span class="mp-reorder">
            <button type="button" class="mp-move-up" data-mp-id="${available.id}" ${orderInfo.isFirst ? "disabled" : ""}>▲</button>
            <button type="button" class="mp-move-down" data-mp-id="${available.id}" ${orderInfo.isLast ? "disabled" : ""}>▼</button>
          </span>
        </div>
        ${cards}
        ${addButton}
      </div>
    </details>`;
}

function renderMarketplaces(state) {
  const container = document.getElementById("marketplaces-list");
  // Запоминаем, какие вкладки были раскрыты, — иначе после сохранения
  // перерисовка свернёт то, с чем пользователь только что работал.
  const openIds = new Set(
    Array.from(container.querySelectorAll("details.mp-type[open]")).map((d) => d.dataset.mpId)
  );
  container.innerHTML = "";
  shopVisibleFromState = (state.display && state.display.marketplace_shop_visible) || {};
  const shopsById = {};
  (state.marketplaces || []).forEach((m) => {
    if (!shopsById[m.id]) shopsById[m.id] = [];
    shopsById[m.id].push(m);
  });
  const breakdownVisibleMap = (state.display && state.display.marketplace_breakdown_visible) || {};
  const available = state.marketplaces_available || [];
  const availableById = {};
  available.forEach((a) => (availableById[a.id] = a));

  const savedOrder = (state.display && state.display.marketplace_breakdown_order) || [];
  const order = savedOrder.filter((id) => availableById[id]);
  available.forEach((a) => {
    if (!order.includes(a.id)) order.push(a.id);
  });

  order.forEach((mpId, i) => {
    const shops = shopsById[mpId] || [];
    const visible = breakdownVisibleMap[mpId] !== false;
    const orderInfo = { isFirst: i === 0, isLast: i === order.length - 1 };
    container.insertAdjacentHTML(
      "beforeend", marketplaceTypeHtml(availableById[mpId], shops, visible, orderInfo, openIds.has(mpId))
    );
  });

  // Перерисовка экрана без тестового оверрайда — {} БЕЗ ключа per_marketplace
  // (не {per_marketplace: {}}) специально: на этой странице нет тестовых
  // полей, и такой запрос НЕ трогает "липкий" оверрайд, выставленный,
  // возможно, с основной страницы прямо сейчас (см. web_server.py
  // /api/display/test — per_marketplace_override остаётся None, пока
  // ключ per_marketplace вообще не передан в теле).
  async function redrawWithoutTouchingTestOverride() {
    await api("/api/display/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    refreshPreview();
  }

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
      await redrawWithoutTouchingTestOverride();
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

  container.querySelectorAll("form[data-key]").forEach((form) => {
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      let key = form.dataset.key;
      const msg = form.querySelector(".mp-msg");
      const fd = new FormData(form);
      const body = {};
      for (const [k, val] of fd.entries()) {
        if (val) body[k] = val;
      }
      try {
        if (!key) {
          // Первый магазин площадки: пустую запись не создаём, пока
          // пользователь ничего не ввёл.
          if (!Object.keys(body).length) {
            msg.textContent = "Заполните поля и нажмите «Сохранить»";
            msg.classList.add("error");
            return;
          }
          const mpId = form.closest(".mp-type").dataset.mpId;
          key = (await api("/api/marketplaces/" + mpId + "/add", { method: "POST" })).key;
        }
        await api("/api/shops/" + key, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        msg.textContent = "Сохранено";
        msg.classList.remove("error");
        refreshAfterShopChange();
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
        refreshAfterShopChange();
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

let formsReady = false;

async function loadState(forceFormRefresh) {
  const state = await api("/api/state");
  renderConnStatus(state);
  renderStats(state);
  renderMarketplaceStats(state);
  document.getElementById("page-updated").textContent =
    "Страница обновляется сама · последний раз в " + fmtClock(new Date());

  // Экран «Маркеты» рисуется только на 400x300 — на 200x200 переключатель
  // просто нечего было бы переключать.
  const is400x300 = state.display_width === 400 && state.display_height === 300;
  document.getElementById("marketplace-breakdown-toggle").hidden = !is400x300;
  setBreakdownClass(is400x300 && !!(state.display && state.display.show_marketplace_breakdown));

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

// Поиск Wi-Fi сетей: клик по сети подставляет её название в поле SSID.
function signalBars(rssi) {
  // RSSI в дБм: чем ближе к 0, тем сильнее сигнал.
  const level = rssi >= -55 ? 4 : rssi >= -65 ? 3 : rssi >= -75 ? 2 : 1;
  return "▂▄▆█".slice(0, level) + "░".repeat(4 - level);
}

document.getElementById("wifi-scan").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  const list = document.getElementById("wifi-networks");
  const box = document.getElementById("wifi-networks-box");
  const msg = document.getElementById("wifi-scan-msg");
  button.disabled = true;
  box.hidden = true;
  msg.textContent = "Ищу сети… это займёт несколько секунд";
  try {
    const data = await api("/api/wifi/scan");
    if (!data.ok) throw new Error(data.error || "ошибка");
    list.innerHTML = "";
    data.networks.forEach((net) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "wifi-net";
      const name = document.createElement("span");
      name.className = "wifi-net-name";
      name.textContent = net.ssid;
      const meta = document.createElement("span");
      meta.className = "wifi-net-meta";
      meta.textContent = (net.secure ? "🔒 " : "") + signalBars(net.rssi);
      b.append(name, meta);
      b.addEventListener("click", () => {
        document.getElementById("wifi-ssid").value = net.ssid;
        box.hidden = true;
        msg.textContent = "Выбрана сеть «" + net.ssid + "». Теперь введите пароль.";
        document.getElementById("wifi-password").focus();
      });
      li.appendChild(b);
      list.appendChild(li);
    });
    box.hidden = !data.networks.length;
    msg.textContent = data.networks.length
      ? "Нажмите на свою сеть. Плата видит только сети 2,4 ГГц."
      : "Сети не найдены. Плата видит только сети 2,4 ГГц — попробуйте ещё раз.";
  } catch (err) {
    msg.textContent = "Не удалось найти сети: " + err.message;
  } finally {
    button.disabled = false;
  }
});

document.getElementById("wifi-scan-collapse").addEventListener("click", () => {
  document.getElementById("wifi-networks-box").hidden = true;
  document.getElementById("wifi-scan-msg").textContent = "";
});

// Глазик у пароля: показать/скрыть введённые символы.
document.getElementById("wifi-pw-toggle").addEventListener("click", (ev) => {
  const input = document.getElementById("wifi-password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  ev.currentTarget.classList.toggle("shown", show);
  ev.currentTarget.setAttribute("aria-label", show ? "Скрыть пароль" : "Показать пароль");
  ev.currentTarget.title = show ? "Скрыть пароль" : "Показать пароль";
});

document.getElementById("preview-refresh").addEventListener("click", refreshPreview);

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

async function saveNightMode() {
  const msg = document.getElementById("notifications-msg");
  const night = {
    enabled: document.getElementById("set-night-enabled").checked,
    start: document.getElementById("set-night-start").value || "22:00",
    end: document.getElementById("set-night-end").value || "08:00",
  };
  try {
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

document.getElementById("set-visual-alert").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { visual_alert: ev.target.checked } }),
    });
    msg.textContent = "Сохранено";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

document.getElementById("set-beep").addEventListener("change", async (ev) => {
  const msg = document.getElementById("notifications-msg");
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display: { beep_on_sale: ev.target.checked } }),
    });
    msg.textContent = "Сохранено";
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

function setBreakdownClass(on) {
  // Стрелки порядка столбиков имеют смысл только в режиме «Каждый отдельно».
  document.getElementById("marketplaces-section").classList.toggle("breakdown-on", on);
}

["mode-total", "mode-breakdown"].forEach((id) => {
  document.getElementById(id).addEventListener("change", async () => {
    const msg = document.getElementById("marketplace-breakdown-msg");
    const on = document.getElementById("mode-breakdown").checked;
    try {
      await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display: { show_marketplace_breakdown: on } }),
      });
      // {} без ключа per_marketplace — см. комментарий в renderMarketplaces
      // про redrawWithoutTouchingTestOverride: перерисовывает, не трогая
      // тестовый оверрайд, который мог быть выставлен с основной страницы.
      await api("/api/display/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setBreakdownClass(on);
      msg.textContent = "Сохранено и перерисовано";
      msg.classList.remove("error");
      refreshPreview();
    } catch (err) {
      // Возвращаем выбор назад, раз не сохранилось.
      document.getElementById("mode-breakdown").checked = !on;
      document.getElementById("mode-total").checked = on;
      msg.textContent = "Ошибка: " + err.message;
      msg.classList.add("error");
    }
    setTimeout(() => (msg.textContent = ""), 3000);
  });
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

document.getElementById("mp-sounds-save").addEventListener("click", async (ev) => {
  const button = ev.target;
  const msg = document.getElementById("notifications-msg");
  const rows = document.querySelectorAll("#mp-sounds-list .notif-row[data-mp-id]");
  button.disabled = true;
  msg.classList.remove("error");
  msg.textContent = "Сохраняю...";
  notificationsCache.selected_by_marketplace = notificationsCache.selected_by_marketplace || {};
  try {
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

async function saveAutoUpdate() {
  const msg = document.getElementById("auto-update-msg");
  const hour = Math.min(23, Math.max(0, parseInt(document.getElementById("set-auto-update-hour").value, 10) || 0));
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_update: { enabled: document.getElementById("set-auto-update").checked, hour } }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || res.status);
    msg.textContent = "Сохранено";
    msg.classList.remove("error");
  } catch (err) {
    msg.textContent = "Ошибка: " + err.message;
    msg.classList.add("error");
  }
  setTimeout(() => (msg.textContent = ""), 3000);
}
document.getElementById("set-auto-update").addEventListener("change", saveAutoUpdate);
document.getElementById("set-auto-update-hour").addEventListener("change", saveAutoUpdate);

document.getElementById("ota-sources-check").addEventListener("click", async (ev) => {
  const button = ev.target;
  const list = document.getElementById("ota-sources-list");
  button.disabled = true;
  list.innerHTML = "<li>Проверяю серверы...</li>";
  try {
    const res = await fetch("/api/ota/sources", { method: "POST" });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || res.status);
    list.innerHTML = "";
    for (const src of data.sources) {
      const li = document.createElement("li");
      li.textContent = src.online
        ? "● " + src.name + " — онлайн, версия " + src.version + " (" + (src.ms / 1000).toFixed(1) + " с)"
        : "○ " + src.name + " — недоступен";
      if (!src.online) li.classList.add("offline");
      list.appendChild(li);
    }
  } catch (err) {
    list.innerHTML = "<li class=\"offline\">Ошибка: " + err.message + "</li>";
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
    msg.textContent = "Соединение прервано (возможно, плата уже перезагружается) — обнови страницу через полминуты.";
    checkButton.disabled = false;
  }
});

// Верхнее меню: если раздел — свёрнутая вкладка, раскрываем её при переходе.
document.querySelectorAll(".quick-nav a[href^='#']:not(.help)").forEach((link) => {
  link.addEventListener("click", () => {
    const target = document.querySelector(link.getAttribute("href"));
    if (target && target.tagName === "DETAILS") target.open = true;
  });
});

// «Как настроить?» — внешняя ссылка на туториал. Пока адреса нет — ничего не делает.
(function () {
  const help = document.getElementById("help-link");
  if (HELP_URL === "#") {
    help.addEventListener("click", (ev) => ev.preventDefault());
  } else {
    help.href = HELP_URL;
    help.target = "_blank";
    help.rel = "noopener";
  }
})();

loadState(true);
loadNotifications();
refreshPreview();
setInterval(() => loadState(false), 30000);
setInterval(refreshPreview, 30000);

// Плашка «Онлайн · IP»: клик копирует адрес платы в домашней сети. На http://
// navigator.clipboard недоступен, поэтому запасной вариант через выделение текста.
(function () {
  const badge = document.getElementById("conn-status");
  if (!badge) return;
  badge.addEventListener("click", () => {
    const ip = badge.dataset.ip;
    if (!ip) return;
    const done = () => {
      const prev = badge.textContent;
      badge.textContent = "Скопировано ✓";
      setTimeout(() => { if (badge.dataset.ip === ip) badge.textContent = prev; }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(ip).then(done, () => {});
      return;
    }
    const ta = document.createElement("textarea");
    ta.value = ip;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { if (document.execCommand("copy")) done(); } catch (e) {}
    document.body.removeChild(ta);
  });
})();
