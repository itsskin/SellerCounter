# Веб-интерфейс настройки, поднятый прямо на ESP32 (и в режиме точки
# доступа при первой настройке, и потом в обычном Wi-Fi режиме).
# Использует microdot (лёгкий async HTTP-фреймворк для MicroPython),
# вендоренный в firmware/lib/ — см. lib/VENDORED.md.

import os

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import machine

import breadcrumb
import config as config_module
import ota
import wifi_manager
from display import layout as layout_module
from display import layout_common
from display.framebuf_sim import to_bmp_bytes
from marketplaces.registry import available_marketplaces, get_client_class
from microdot import Microdot, Request, Response

app = Microdot()

# Дефолт microdot — 16КБ на тело запроса, маловато для картинки фона
# (наши тестовые PNG были 2-6КБ, но с запасом на более сложные макеты).
Request.max_content_length = 200 * 1024
Request.max_body_length = 200 * 1024

NOTIFICATIONS_DIR = "/notifications"
PLAYABLE_EXTENSIONS = (".mid", ".midi", ".wav")
ASSETS_DIR = "/display/assets"
BACKGROUND_UPLOAD_NAME = "web_upload.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Состояние, общее для всех обработчиков — заполняется в run_server().
# Модуль импортируется один раз за сессию прошивки, так что module-level
# словарь тут безопасен (не нужен класс ради одного инстанса).
_state = {
    "cfg": None,
    "mode": "provisioning",
    "engine": None,
    "display": None,
    "buzzer": None,
}


def _mask(value):
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _public_marketplace(entry):
    cls = get_client_class(entry.get("id"))
    out = {
        "id": entry.get("id"),
        "key": entry.get("key"),
        "configured": cls.is_configured(entry) if cls else False,
    }
    for field in ("client_id", "campaign_id"):
        if field in entry:
            out[field] = _mask(entry.get(field, ""))
    out["api_key_set"] = bool(entry.get("api_key"))
    return out


@app.route("/")
async def index(request):
    return Response.send_file("/www/index.html", content_type="text/html")


@app.route("/style.css")
async def style(request):
    return Response.send_file("/www/style.css", content_type="text/css")


@app.route("/app.js")
async def app_js(request):
    return Response.send_file("/www/app.js", content_type="application/javascript")


@app.route("/api/state")
async def api_state(request):
    cfg = _state["cfg"]
    engine = _state["engine"]
    data = {
        "mode": _state["mode"],
        "ip": wifi_manager.get_ip(),
        "ap_ip": wifi_manager.AP_IP,
        "wifi_ssid": cfg["wifi"]["ssid"],
        "wifi_connected": wifi_manager.is_sta_connected(),
        "poll_interval_sec": cfg["poll_interval_sec"],
        "timezone_offset_hours": cfg["timezone_offset_hours"],
        "debug_day_offset": cfg.get("debug_day_offset", 0),
        "display": cfg["display"],
        "buzzer": cfg["buzzer"],
        "marketplaces_available": available_marketplaces(),
        "marketplaces": [_public_marketplace(e) for e in cfg["marketplaces"]],
        "ota_version": ota.current_version(),
    }
    if engine is not None:
        data["stats"] = engine.latest
        data["errors"] = engine.last_errors
        data["per_marketplace"] = engine.per_marketplace
        data["next_poll_in_sec"] = engine.next_poll_in_sec()
    display = _state["display"]
    if display is not None:
        # Реальное разрешение подключённого экрана (не cfg["display"]["screen"]
        # — то поле только для driver="sim", для настоящего железа не значит
        # ничего) — веб-интерфейсу нужно знать его для формы загрузки фона
        # (см. www/app.js, подсказка про нужный размер PNG).
        data["display_width"] = display.width
        data["display_height"] = display.height
    return data


@app.route("/api/wifi", methods=["POST"])
async def api_wifi(request):
    body = request.json or {}
    cfg = _state["cfg"]
    cfg["wifi"]["ssid"] = body.get("ssid", "")
    cfg["wifi"]["password"] = body.get("password", "")
    config_module.save(cfg)
    asyncio.create_task(_reset_soon())
    return {"ok": True, "message": "saved, rebooting"}


async def _reset_soon():
    await asyncio.sleep(1)
    machine.reset()


@app.route("/api/reboot", methods=["POST"])
async def api_reboot(request):
    """Перезагрузка по явному запросу — нужна там, где настройка (сейчас
    только display.driver) применяется один раз при старте main.py и не
    может быть переключена на живом объекте без пересоздания SPI/пинов."""
    asyncio.create_task(_reset_soon())
    return {"ok": True, "message": "rebooting"}


@app.route("/api/ota/check", methods=["POST"])
async def api_ota_check(request):
    try:
        result = await ota.check()
    except ota.OtaError as exc:
        return {"ok": False, "error": str(exc)}, 502
    return {
        "ok": True,
        "current_version": result["current_version"],
        "available_version": result["available_version"],
        "update_available": result["update_available"],
        "source": result["source"],
    }


@app.route("/api/ota/apply", methods=["POST"])
async def api_ota_apply(request):
    """Проверяет ещё раз (на случай если с последней проверки в вебе
    прошло время и версия успела поменяться) и, если обновление реально
    доступно, качает+проверяет все файлы и перезагружает плату — см.
    ota.apply() про то, почему это безопасно на середине сорвавшейся сети."""
    try:
        result = await ota.check()
    except ota.OtaError as exc:
        return {"ok": False, "error": str(exc)}, 502
    if not result["update_available"]:
        return {"ok": False, "error": "обновлений нет"}, 400

    breadcrumb.mark("applying OTA update to version %d" % result["available_version"])
    try:
        await ota.apply(result["manifest"], result["source"])
    except Exception as exc:
        breadcrumb.mark("OTA update failed: %s" % exc)
        return {"ok": False, "error": str(exc)}, 500

    breadcrumb.mark("OTA update applied — rebooting")
    asyncio.create_task(_reset_soon())
    return {"ok": True, "new_version": result["available_version"]}


@app.route("/api/marketplaces/<marketplace_id>/add", methods=["POST"])
async def api_marketplace_add(request, marketplace_id):
    """Добавляет ещё один (пустой, ещё не настроенный) магазин на площадку
    marketplace_id — кнопка "+" в веб-интерфейсе. Реальные API-ключи
    сохраняются отдельным запросом на /api/shops/<key>, этот только
    заводит запись и возвращает её key, чтобы веб знал, куда сохранять."""
    if get_client_class(marketplace_id) is None:
        return {"ok": False, "error": "unknown marketplace"}, 404
    cfg = _state["cfg"]
    key = config_module.add_marketplace_shop(cfg, marketplace_id)
    config_module.save(cfg)
    return {"ok": True, "key": key}


@app.route("/api/shops/<key>", methods=["POST"])
async def api_shop_save(request, key):
    """Сохраняет API-ключи конкретного магазина (адресуется по key, не по
    id площадки — на площадке их может быть несколько, см. config.py)."""
    cfg = _state["cfg"]
    entry = config_module.get_shop(cfg, key)
    if entry is None:
        return {"ok": False, "error": "unknown shop"}, 404
    body = request.json or {}
    updates = {}
    for field in ("client_id", "campaign_id", "api_key"):
        # пустое значение с формы = "оставить как было", не затираем секрет
        if body.get(field):
            updates[field] = body[field]
    config_module.set_shop_settings(cfg, key, updates)
    config_module.save(cfg)
    return {"ok": True}


@app.route("/api/shops/<key>/remove", methods=["POST"])
async def api_shop_remove(request, key):
    """Кнопка "-" — удаляет конкретный магазин целиком (можно удалить и
    последний магазин площадки, она просто перестанет опрашиваться)."""
    cfg = _state["cfg"]
    if not config_module.remove_marketplace_shop(cfg, key):
        return {"ok": False, "error": "unknown shop"}, 404
    config_module.save(cfg)
    return {"ok": True}


@app.route("/api/settings", methods=["POST"])
async def api_settings(request):
    body = request.json or {}
    cfg = _state["cfg"]
    if "poll_interval_sec" in body:
        cfg["poll_interval_sec"] = int(body["poll_interval_sec"])
    if "timezone_offset_hours" in body:
        cfg["timezone_offset_hours"] = float(body["timezone_offset_hours"])
    if "debug_day_offset" in body:
        cfg["debug_day_offset"] = int(body["debug_day_offset"])
    if "display" in body:
        cfg["display"].update(body["display"])
    if "buzzer" in body:
        cfg["buzzer"].update(body["buzzer"])
        buzzer = _state["buzzer"]
        if buzzer is not None:
            # Живой объект Buzzer уже создан с этими значениями при старте —
            # применяем изменения сразу, без перезагрузки платы.
            buzzer.volume = cfg["buzzer"].get("volume", buzzer.volume)
            buzzer.enabled = cfg["buzzer"].get("enabled", buzzer.enabled)
            buzzer.volume_curve = cfg["buzzer"].get("volume_curve", buzzer.volume_curve)
    config_module.save(cfg)
    return {"ok": True}


@app.route("/api/refresh", methods=["POST"])
async def api_refresh(request):
    engine = _state["engine"]
    if engine is None:
        return {"ok": False, "error": "not running (provisioning mode)"}, 400
    polled = await engine.poll_once(force=True)
    return {
        "ok": True,
        "polled": polled,
        "stats": engine.latest,
        "errors": engine.last_errors,
        "per_marketplace": engine.per_marketplace,
    }


@app.route("/api/display/preview.bmp")
async def api_preview(request):
    display = _state["display"]
    if display is None:
        return Response(body=b"", status_code=404)
    bmp = to_bmp_bytes(display.buffer, display.width, display.height)
    return Response(body=bmp, headers={"Content-Type": "image/bmp"})


@app.route("/api/display/test", methods=["POST"])
async def api_display_test(request):
    """Рисует экран с подставленными вручную заказами/выручкой — чтобы
    посмотреть, как это будет выглядеть, не дожидаясь реальных данных с
    такими значениями. 0 или отсутствие поля = показать реальные текущие
    (см. StatsEngine.redraw). Реальные данные (self.latest) при этом не
    трогаются — следующий обычный опрос всё равно перерисует настоящими
    цифрами, если они успели измениться."""
    engine = _state["engine"]
    if engine is None:
        return {"ok": False, "error": "not running (provisioning mode)"}, 400

    body = request.json or {}
    try:
        orders = int(body.get("orders") or 0)
        revenue = float(body.get("revenue") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "orders/revenue должны быть числами"}, 400

    try:
        await engine.redraw(orders=orders, revenue=revenue)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}, 500

    return {"ok": True}


@app.route("/api/layout/text")
async def api_layout_text_get(request):
    """Отдаёт содержимое ОБЩЕГО layout.txt (координаты/шрифты для ОБОИХ
    экранов сразу — 200x200 и 400x300, см. display/layout_common.LAYOUT) —
    для редактирования прямо в браузере, без Thonny/физического доступа к
    плате."""
    return {"ok": True, "path": layout_common.LAYOUT.path, "text": layout_common.LAYOUT.read_text()}


@app.route("/api/layout/fonts")
async def api_layout_fonts(request):
    """Список имён шрифтов, РЕАЛЬНО доступных на этой плате сейчас (сканирует
    display/fonts/*.py) — то, что можно подставлять в поля *.font.* в
    layout.txt. Не статический список из репозитория — плата могла ещё не
    получить свежий OTA с новыми шрифтами, так что это честная проверка "по
    факту"."""
    try:
        names = sorted(
            n[:-3] for n in os.listdir("/display/fonts") if n.endswith(".py")
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}, 500
    return {"ok": True, "fonts": names}


@app.route("/api/layout/text", methods=["POST"])
async def api_layout_text_post(request):
    """Сохраняет отредактированный layout.txt и сразу перерисовывает экран
    текущими данными (без нового опроса маркетплейсов) — правка видна на
    экране (или в /api/display/preview.bmp) сразу после нажатия "Применить"."""
    display = _state["display"]
    engine = _state["engine"]
    if display is None or engine is None:
        return {"ok": False, "error": "not running (provisioning mode)"}, 400

    body = request.json or {}
    text = body.get("text")
    if text is None:
        return {"ok": False, "error": "text обязателен"}, 400

    layout_common.LAYOUT.write_text(text)

    try:
        await engine.redraw()
    except Exception as exc:
        return {"ok": True, "saved": True, "redraw_error": str(exc)}
    return {"ok": True, "saved": True}


@app.route("/api/background", methods=["POST"])
async def api_background(request):
    """Заливает новый PNG-фон прямо через веб — без Thonny/mpremote.
    Тело запроса — сырые байты PNG (не multipart/form-data, проще на
    стороне браузера: fetch(..., {body: file})). Конвертация — та же
    check_new_background(), что и для файлов, закинутых вручную в
    display/assets/ (см. display/layout_200x200.py), так что оба пути
    (веб и ручная заливка файла) ведут себя одинаково."""
    display = _state["display"]
    if display is None:
        return {"ok": False, "error": "экран не инициализирован"}, 400

    body = request.body
    if not body or body[:8] != PNG_SIGNATURE:
        return {"ok": False, "error": "это не PNG (нет сигнатуры файла)"}, 400

    cfg = _state["cfg"]
    layout_mod = layout_module.get_layout(display.width, display.height, cfg["display"].get("layout_override"))
    check_bg = getattr(layout_mod, "check_new_background", None)
    if check_bg is None:
        return {"ok": False, "error": "у этого макета экрана нет смены фона картинкой"}, 400

    path = ASSETS_DIR + "/" + BACKGROUND_UPLOAD_NAME
    try:
        with open(path, "wb") as f:
            f.write(body)
    except OSError as exc:
        return {"ok": False, "error": "не смог сохранить файл: %s" % exc}, 500

    breadcrumb.mark("converting uploaded background png")
    try:
        applied = check_bg()
    except Exception as exc:
        return {"ok": False, "error": "не смог обработать картинку: %s" % exc}, 500
    breadcrumb.mark("idle (after background upload)")

    if not applied:
        return {
            "ok": False,
            "error": "картинка не подошла (неверный размер или формат — подробности в логе платы)",
        }, 400

    engine = _state["engine"]
    if engine is not None:
        try:
            await engine.redraw()
        except Exception as exc:
            print("web_server: не смог перерисовать экран после смены фона:", exc)

    return {"ok": True}


def _is_safe_filename(name):
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".")


def _list_notifications():
    try:
        names = os.listdir(NOTIFICATIONS_DIR)
    except OSError:
        names = []
    files = []
    for name in sorted(names):
        lower = name.lower()
        ext = lower[lower.rfind("."):] if "." in lower else ""
        try:
            size = os.stat(NOTIFICATIONS_DIR + "/" + name)[6]
        except OSError:
            size = 0
        files.append(
            {"filename": name, "ext": ext, "playable": ext in PLAYABLE_EXTENSIONS, "size": size}
        )
    return files


@app.route("/api/notifications")
async def api_notifications_list(request):
    cfg = _state["cfg"]
    return {
        "files": _list_notifications(),
        "selected": cfg.get("notification_sound", ""),
        # {marketplace_id: filename} — только те маркетплейсы, у которых
        # явно выбрана СВОЯ мелодия (переопределяет "selected" выше). Нет
        # записи для id — играется общий "selected" (см.
        # StatsEngine._sound_for_marketplace).
        "selected_by_marketplace": cfg.get("notification_sounds", {}),
    }


@app.route("/api/notifications/select", methods=["POST"])
async def api_notifications_select(request):
    """marketplace_id в теле — необязательный: без него меняется общий
    (дефолтный) звук, с ним — звук конкретно этого маркетплейса
    (notification_sounds[marketplace_id]), остальные не трогаются."""
    body = request.json or {}
    filename = body.get("filename", "")
    marketplace_id = body.get("marketplace_id")
    cfg = _state["cfg"]

    if marketplace_id and not filename:
        # пустое значение при заданном marketplace_id = убрать override,
        # снова играть общий (дефолтный) звук для этого маркетплейса.
        if get_client_class(marketplace_id) is None:
            return {"ok": False, "error": "unknown marketplace"}, 404
        cfg["notification_sounds"].pop(marketplace_id, None)
        config_module.save(cfg)
        return {"ok": True}

    if not _is_safe_filename(filename):
        return {"ok": False, "error": "bad filename"}, 400
    try:
        os.stat(NOTIFICATIONS_DIR + "/" + filename)
    except OSError:
        return {"ok": False, "error": "file not found"}, 404

    if marketplace_id:
        if get_client_class(marketplace_id) is None:
            return {"ok": False, "error": "unknown marketplace"}, 404
        cfg["notification_sounds"][marketplace_id] = filename
    else:
        cfg["notification_sound"] = filename
    config_module.save(cfg)
    return {"ok": True}


@app.route("/api/notifications/test", methods=["POST"])
async def api_notifications_test(request):
    buzzer = _state["buzzer"]
    if buzzer is None:
        return {"ok": False, "error": "buzzer not ready"}, 400

    body = request.json or {}
    filename = body.get("filename") or _state["cfg"].get("notification_sound", "")
    if not _is_safe_filename(filename):
        return {"ok": False, "error": "bad filename"}, 400

    breadcrumb.mark("playing test notification %s" % filename)
    await buzzer.play_notification(NOTIFICATIONS_DIR + "/" + filename)
    breadcrumb.mark("idle (after test notification)")
    return {"ok": True}


async def run_server(cfg, mode, engine=None, display=None, buzzer=None):
    _state["cfg"] = cfg
    _state["mode"] = mode
    _state["engine"] = engine
    _state["display"] = display
    _state["buzzer"] = buzzer
    await app.start_server(port=80, debug=False)
