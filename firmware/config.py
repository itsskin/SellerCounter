import ujson as json

CONFIG_PATH = "/config.json"

DEFAULT_CONFIG = {
    # Пусто — плата уходит в AP-провижининг при первом включении, пока
    # пользователь не введёт свою сеть через веб-форму. НЕ вписывать сюда
    # реальные SSID/пароль даже временно — этот файл теперь публичный
    # (см. репозиторий на GitHub, OTA), любой дефолт здесь уедет в интернет.
    "wifi": {"ssid": "", "password": ""},
    "ap": {"ssid": "SellerCounter-Setup", "password": "12345678"},
    # 300 (5 минут), не 60 — на площадке теперь может быть НЕСКОЛЬКО
    # магазинов (см. "marketplaces" ниже), а значит несколько запросов за
    # один цикл опроса; более редкий цикл снижает риск словить rate limit
    # с одного IP (см. также SHOP_REQUEST_GAP_MS в stats_engine.py — пауза
    # МЕЖДУ магазинами одной площадки внутри одного цикла).
    "poll_interval_sec": 300,
    "timezone_offset_hours": 3,
    # Временная отладочная настройка: сдвиг "текущего дня" в сутках, на
    # который смотрит вся статистика (0 = сегодня, -1 = вчера). Нужна,
    # когда за сегодня ещё нет продаж и хочется проверить экран/цифры на
    # вчерашних данных. В обычной работе держать 0.
    "debug_day_offset": 0,
    # Отдельного флага "enabled" нет — магазин опрашивается, как только
    # заполнены его обязательные поля (см. marketplaces/registry.py).
    #
    # На одной площадке (id) может быть НЕСКОЛЬКО записей — несколько
    # магазинов/кабинетов под разными API-ключами (см. "+"/"-" в
    # веб-интерфейсе, config.add_marketplace_shop/remove_marketplace_shop).
    # Их заказы и выручка суммируются в одну строку "по площадке" —
    # отдельной разбивки по магазинам в интерфейсе нет (так и задумано).
    # "key" — стабильный уникальный идентификатор ИМЕННО ЭТОЙ записи
    # (не площадки — id у нескольких записей может повторяться), не
    # показывается пользователю, нужен только чтобы веб мог адресовать
    # конкретный магазин (сохранить/удалить именно его) и чтобы
    # stats_engine мог держать "последнее успешное значение" отдельно на
    # каждый магазин, а не только на площадку целиком.
    "marketplaces": [
        {"id": "ozon", "key": "ozon-1", "client_id": "", "api_key": ""},
        {"id": "wb", "key": "wb-1", "api_key": ""},
        {"id": "yandex", "key": "yandex-1", "campaign_id": "", "api_key": ""},
    ],
    # driver: "epd1in54" (1.54" 200x200, SSD1681 — то, что сейчас физически
    # подключено), "epd4in2" (4.2" 400x300, WeAct — когда придёт), или "sim"
    # (без экрана вообще, только превью в браузере). screen — какой размер
    # симулировать, когда driver="sim" ("200x200" или "400x300"), на сам
    # выбор реального железа не влияет.
    # show_fbs_reminder — включает напоминание "Собрать FBS" на экране (см.
    # fbs_label.* в assets/layout*.txt) — рисуется САМО, когда за сегодня
    # реально есть хотя бы один FBS-заказ (см. StatsEngine.latest["fbs_orders"]),
    # и исчезает, когда их нет. Этот чекбокс только включает/выключает саму
    # функцию, не форсирует надпись — см. галочку в веб-интерфейсе, раздел
    # "Маркетплейсы".
    "display": {
        "driver": "epd1in54",
        "screen": "200x200",
        "rotation": 0,
        # Раз в сколько обновлений экрана делать ЧЕСТНЫЙ full refresh
        # (без температурного трюка на "быстрый" — см. display/epd4in2.py
        # и display/epd1in54.py, show()) — чистит лёгкие призраки
        # предыдущих кадров, которые "быстрый" вариант со временем
        # оставляет, несмотря на формально полное перещёлкивание пикселей.
        # Первое обновление после включения платы — всегда честное,
        # независимо от этого числа (см. self._update_count в драйвере).
        # Применяется сразу, без перезагрузки платы (см. web_server.py
        # /api/settings — живой объект display уже создан при старте).
        "full_refresh_every": 50,
        "beep_on_sale": True,
        "show_fbs_reminder": False,
        # Отладочный форс-чекбокс в веб-интерфейсе — держит надпись "Собрать
        # FBS" на экране ВСЕГДА, независимо от show_fbs_reminder выше и от
        # реального наличия несобранных заказов (StatsEngine.latest
        # ["fbs_orders"]). Нужен, чтобы проверить положение/шрифт надписи
        # (например через layout.txt), не дожидаясь настоящего FBS-заказа.
        "show_fbs_test_label": False,
        # Пусто — макет выбирается автоматически по РЕАЛЬНОМУ разрешению
        # подключённого физического экрана (см. display/layout.py
        # get_layout). "200x200" или "400x300" — принудительно рисовать
        # именно этот макет поверх любого физически подключённого экрана
        # (см. layout_override в display/layout.py) — для разработки/
        # проверки вёрстки макета без физического переключения панелей:
        # например можно держать подключённым большой 400x300 экран и
        # смотреть, как будет выглядеть макет 200x200 (он просто займёт
        # верхний левый угол буфера физического экрана, остальное
        # останется пустым). Сам физический драйвер (display.driver выше)
        # не трогает — SPI/буфер экрана работают со своим настоящим
        # разрешением как обычно, меняется только то, какой код рисования
        # вызывается.
        "layout_override": "",
        # Экран "детализация по маркетплейсам" — только для 400x300 (см.
        # display/layout_400x300.py), вместо одной общей суммы показывает
        # каждый подключённый маркетплейс отдельным столбиком (короткая
        # подпись "Oz"/"Wb"/"Ya" — см. MarketplaceClient.short_label — плюс
        # его выручка и заказы). Столбики — только по маркетплейсам, которые
        # реально опрашиваются (заполнены ключи).
        "show_marketplace_breakdown": False,
        # {marketplace_id: bool} — какие из них показывать на этом экране,
        # НЕЗАВИСИМО от show_marketplace_breakdown выше (например можно
        # держать включённым сам режим, но скрыть маркетплейс с маленькими
        # продажами и следить только за одним-двумя важными). Отсутствие
        # ключа = показывать (дефолт "все включены", не нужно вручную
        # включать каждый при первой настройке).
        "marketplace_breakdown_visible": {},
        # [marketplace_id, ...] — порядок столбиков слева направо (веб-
        # интерфейс, раздел "Маркетплейсы", стрелки вверх/вниз у каждого).
        # Пусто — порядок как в cfg["marketplaces"] (по умолчанию Ozon/WB/
        # Yandex). Id, которых нет в списке (например добавили новый
        # маркетплейс уже после того, как порядок настроили руками), просто
        # дорисовываются в конце в естественном порядке — не ломает экран.
        "marketplace_breakdown_order": [],
        # Заказы под каждым столбиком заменяются ОДНИМ числом по центру —
        # суммой выручки именно по отображаемым сейчас столбикам (не
        # общий итог по всем маркетплейсам платы, скрытые через
        # marketplace_breakdown_visible в сумму не входят).
        "marketplace_breakdown_show_total_revenue": False,
    },
    # volume: 0-500%. 100 — как есть (для тонов это уже физический потолок
    # громкости на 3.3В, см. buzzer.py). Для .wav можно поднимать выше 100,
    # чтобы цифрово усилить тихую запись (с искажениями на больших значениях,
    # чем выше — тем сильнее).
    # volume_curve: "linear" / "capped" / "quadratic" — как volume% переходит
    # в скважность PWM для тонов/MIDI, см. buzzer.py (шапка файла и
    # VOLUME_CURVES) — там же объяснение, зачем это вообще нужно (на 100%
    # "linear" звучит скорее тише некоторых высоких нот, чем на 80-90%, из-за
    # особенностей гармоник ровно на 50% скважности).
    # night_mode: окно времени (локальное, timezone_offset_hours), когда
    # уведомления о продажах молчат (см. StatsEngine._in_night_mode) — сам
    # опрос маркетплейсов и экран это не трогает, только звук. start/end —
    # "HH:MM". start > end означает окно через полночь (например
    # "22:00"-"08:00"). start == end — ночной режим фактически выключен,
    # даже если enabled=True (пустой диапазон).
    "buzzer": {
        "pin": 13,
        "enabled": True,
        "volume": 100,
        "volume_curve": "linear",
        "night_mode": {"enabled": False, "start": "22:00", "end": "08:00"},
        # Отдельный переключатель конкретно для сигнала при ФИЗИЧЕСКОМ
        # включении платы (main.py: beep() + startup_chime(), только на
        # machine.reset_cause() == PWRON_RESET) — независим от "enabled"
        # выше (тот глушит вообще всё; этот — только звук включения,
        # продажи/тест по-прежнему звучат). На обычные перезагрузки
        # (сохранение настроек, OTA и т.п.) не влияет — там теперь тихо
        # всегда, ни этот флаг, ни watchdog_sound ниже. Проверяется ОДИН
        # раз, в main.py при старте — в отличие от enabled/volume/
        # volume_curve, тут нет живого объекта Buzzer, который можно
        # поменять на лету, только со следующего включения.
        "boot_sound": True,
        # Отдельный сигнал именно для перезагрузки по watchdog (см.
        # main.py: reset_cause() == WDT_RESET) — по просьбе пользователя,
        # чтобы на слух сразу отличать самостоятельный сбой от обычной
        # ручной/деплойной перезагрузки, не заглядывая в лог через serial.
        # Та же логика проверки один раз при старте, что и у boot_sound.
        "watchdog_sound": True,
    },
    # Имя файла в /notifications/, который играется при новой продаже и по
    # кнопке "Тест" в веб-интерфейсе (см. web_server.py: /api/notifications*)
    # — дефолт/фолбэк для маркетплейсов без своей мелодии в
    # notification_sounds ниже.
    "notification_sound": "sale.mid",
    # Мелодия конкретного маркетплейса (id -> имя файла в /notifications/),
    # переопределяет notification_sound выше только для этого маркетплейса.
    # Нет записи для id — играется общий notification_sound. См.
    # StatsEngine._sound_for_marketplace.
    "notification_sounds": {},
}


def _deep_merge(defaults, overrides):
    result = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _shop_key(marketplace_id, existing_keys):
    n = 1
    while "%s-%d" % (marketplace_id, n) in existing_keys:
        n += 1
    return "%s-%d" % (marketplace_id, n)


def _ensure_marketplace_keys(cfg):
    """Миграция: config.json, сохранённый ДО поддержки нескольких магазинов
    на одной площадке, не имеет "key" у записей marketplaces — присваиваем
    один раз при загрузке, стабильно (id + первый свободный номер), не
    трогая записи, у которых key уже есть."""
    existing_keys = set(e["key"] for e in cfg["marketplaces"] if e.get("key"))
    for entry in cfg["marketplaces"]:
        if entry.get("key"):
            continue
        entry["key"] = _shop_key(entry["id"], existing_keys)
        existing_keys.add(entry["key"])
    return cfg


def load():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    else:
        cfg = _deep_merge(DEFAULT_CONFIG, data)
    return _ensure_marketplace_keys(cfg)


def save(cfg):
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cfg, f)
    try:
        import os
        os.remove(CONFIG_PATH)
    except OSError:
        pass
    import os
    os.rename(tmp_path, CONFIG_PATH)


def has_wifi_credentials(cfg):
    return bool(cfg["wifi"]["ssid"])


def get_shop(cfg, key):
    """Находит запись конкретного магазина по её "key" (не по id площадки —
    их на одной площадке может быть несколько, см. DEFAULT_CONFIG выше)."""
    for entry in cfg["marketplaces"]:
        if entry.get("key") == key:
            return entry
    return None


def set_shop_settings(cfg, key, updates):
    """True, если магазин с таким key нашёлся и обновился; False — если
    такого key нет (например уже удалили с другой вкладки)."""
    entry = get_shop(cfg, key)
    if entry is None:
        return False
    entry.update(updates)
    return True


def add_marketplace_shop(cfg, marketplace_id):
    """Добавляет пустой (ещё не настроенный) магазин на площадку
    marketplace_id — веб-форма "+" рядом с площадкой. Возвращает key новой
    записи, чтобы веб сразу мог адресовать её (сохранить введённые поля)."""
    existing_keys = set(e["key"] for e in cfg["marketplaces"] if e.get("key"))
    key = _shop_key(marketplace_id, existing_keys)
    cfg["marketplaces"].append({"id": marketplace_id, "key": key})
    return key


def remove_marketplace_shop(cfg, key):
    """True, если магазин с таким key нашёлся и удалился. Можно удалить
    вообще все магазины площадки, включая последний — площадка просто
    перестанет опрашиваться, как и раньше при пустых полях."""
    for i, entry in enumerate(cfg["marketplaces"]):
        if entry.get("key") == key:
            del cfg["marketplaces"][i]
            return True
    return False
