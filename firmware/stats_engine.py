import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import breadcrumb
from display import layout
from marketplaces.base import MarketplaceError
from marketplaces.registry import build_enabled_clients
from utils.time_sync import today_local_bounds

# Пауза между запросами к РАЗНЫМ магазинам ОДНОЙ площадки (см. poll_once) —
# несколько магазинов на одной площадке означают несколько запросов подряд с
# одного IP; без паузы это реально ловило rate limit (HTTP 429 от WB).
SHOP_REQUEST_GAP_MS = 1500

# Время последнего опроса — на флеше, а не только в памяти (см. __init__ и
# poll_once): переживает перезагрузку платы. Без этого троттлинг "не чаще
# раза в poll_interval_sec" сбрасывался на КАЖДОМ ребуте, и первый опрос
# после загрузки всегда происходил немедленно, игнорируя интервал — при
# частых перезагрузках (например во время заливки прошивки по USB) это
# означало лишние внеплановые запросы к маркетплейсам почти сразу друг за
# другом. HW-подтверждено: похоже, именно так и словили HTTP 429 от Ozon
# ("rate limit per second") во время серии перезагрузок при отладке.
LAST_POLL_PATH = "/last_poll_at.txt"


def _read_last_poll_epoch():
    try:
        with open(LAST_POLL_PATH) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_last_poll_epoch(epoch):
    try:
        with open(LAST_POLL_PATH, "w") as f:
            f.write(str(int(epoch)))
    except OSError:
        pass


class StatsEngine:
    """Опрашивает включённые маркетплейсы, суммирует заказы/выручку за
    сегодня, обновляет экран и пищит зуммером при росте числа заказов."""

    def __init__(self, cfg, display, buzzer, get_ip):
        self.cfg = cfg
        self.display = display
        self.buzzer = buzzer
        self.get_ip = get_ip
        # Заказы на конец предыдущего опроса, по каждому маркетплейсу
        # отдельно ({id: orders}) — чтобы понимать, у КОГО именно выросло
        # число заказов, и играть мелодию именно этого маркетплейса (см.
        # notification_sounds в config.py). Обновляется только по успешным
        # опросам (ошибка API — значение маркетплейса не трогаем, чтобы
        # временный сбой не создал ложный "рост" на следующем удачном опросе
        # и не съел реальный прирост, случившийся, пока API был недоступен).
        self._last_orders_by_mp = {}
        # То же самое, но только для FBS-заказов (см. "fbs_orders" в
        # ozon.py.fetch_daily_stats) — отдельное отслеживание роста, чтобы
        # звук уведомления мог сыграть именно на новый FBS-заказ, даже если
        # он совпал по циклу опроса с отменой FBO-заказа (тогда суммарные
        # orders могли бы не вырасти вообще, а FBS-заказ, требующий сборки
        # прямо сейчас, всё равно появился — см. poll_once).
        self._last_fbs_orders_by_mp = {}
        # Последние УСПЕШНО полученные orders/revenue по каждому МАГАЗИНУ
        # отдельно (ключ — entry["key"] из config.json, не marketplace id —
        # на одной площадке может быть несколько магазинов/API-ключей, см.
        # config.add_marketplace_shop) — {shop_key: {"orders", "revenue"}}.
        # Когда опрос конкретного МАГАЗИНА падает с ошибкой (rate limit,
        # сеть и т.п.), его вклад в сумму по площадке берётся ОТСЮДА, а не
        # считается нулём — иначе временный сбой одного магазина утаскивал
        # бы вниз весь суммарный счётчик на экране на один цикл опроса, а на
        # следующем удачном — обратно вверх; пользователь видел бы
        # бессмысленное "моргание" цифр туда-обратно от сбоя, который сам
        # себя чинит (см. запрос пользователя после реального HTTP 429 от
        # Wildberries).
        self._last_good_by_shop = {}
        # Когда магазин отвечает 429 и присылает заголовок с числом секунд
        # до следующей попытки (X-RateLimit-Retry/Retry-After, см.
        # utils/http.py), запоминаем "не раньше чем" (time.time() —
        # монотонные секунды с эпохи, не время суток) — {shop_key: unix_ts}.
        # Пока это время не наступило, вообще НЕ делаем HTTP-запрос к этому
        # магазину (используем last_good молча) — раз сервер прямо просит
        # подождать, долбить его на каждом цикле опроса — только продлевать
        # себе бан, а не чинить его.
        self._retry_not_before_by_shop = {}
        self._current_date = None
        # Восстанавливаем с флеша (см. LAST_POLL_PATH выше) — переживает
        # перезагрузку платы, поэтому действует сразу на ВСЕ маркетплейсы
        # (Ozon, WB, Yandex опрашиваются одним общим циклом poll_once, тут
        # нет разделения по конкретному магазину).
        self._last_poll_epoch = _read_last_poll_epoch()
        self.latest = {"orders": 0, "revenue": 0.0, "fbs_orders": 0}
        self.last_errors = {}
        # Разбивка последнего опроса по каждому маркетплейсу отдельно —
        # {id: {"name", "orders", "revenue", "error", "updated_at"}}.
        # Нужна, чтобы в веб-интерфейсе было видно, какой конкретно API
        # насчитал лишнее/не то, а не только суммарную цифру (см. web_server
        # /api/state, www/app.js renderMarketplaceStats).
        self.per_marketplace = {}
        # Что реально отрисовано на экране сейчас — чтобы не гонять
        # e-paper (десятки секунд + видимое моргание на каждое обновление)
        # ради одних и тех же чисел. Экран перерисовывается только когда
        # заказы/выручка реально изменились — при включении первый кадр
        # рисует main.py напрямую, сюда это не относится.
        self._displayed = None

    async def run(self):
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                print("stats_engine: unexpected error:", exc)
            await asyncio.sleep(self.cfg.get("poll_interval_sec", 60))

    def _min_poll_gap_sec(self):
        # Фоновый цикл (run()) не должен опрашивать API маркетплейсов чаще,
        # чем раз в poll_interval_sec. На ручное обновление (force=True)
        # это ограничение не действует — см. poll_once().
        return int(self.cfg.get("poll_interval_sec", 60))

    def next_poll_in_sec(self):
        """Сколько секунд осталось до следующего разрешённого опроса (0, если
        уже можно/пора). Нужно веб-интерфейсу: сразу после перезагрузки
        per_marketplace пуст (реального опроса ещё не было в этом процессе),
        и без этого www/app.js показывал "настрой маркетплейсы", хотя на
        самом деле они настроены и опрос просто ждёт своей очереди из-за
        персистентного троттлинга (см. _read_last_poll_epoch выше) — вводило
        в заблуждение."""
        if self._last_poll_epoch is None:
            return 0
        remaining = self._min_poll_gap_sec() - (time.time() - self._last_poll_epoch)
        return max(0, int(remaining))

    async def poll_once(self, force=False):
        """Возвращает True, если реально сходили в API, False — если пропустили
        из-за минимального интервала (см. _min_poll_gap_sec).

        force=True (используется ручной кнопкой "Обновить сейчас" в
        веб-интерфейсе) отключает эту защиту — опрос происходит всегда,
        по явному запросу человека."""
        ts = _now_hms(self.cfg.get("timezone_offset_hours", 3))
        now_epoch = time.time()
        if not force and self._last_poll_epoch is not None:
            elapsed_sec = now_epoch - self._last_poll_epoch
            min_gap_sec = self._min_poll_gap_sec()
            if elapsed_sec < min_gap_sec:
                print(
                    "[stats %s] пропускаю: последний опрос был %.0f с назад (мин. пауза %d с)"
                    % (ts, elapsed_sec, min_gap_sec)
                )
                return False
        self._last_poll_epoch = now_epoch
        _write_last_poll_epoch(now_epoch)

        _, _, date_str = today_local_bounds(
            self.cfg.get("timezone_offset_hours", 3),
            self.cfg.get("debug_day_offset", 0),
        )
        if date_str != self._current_date:
            # новый день — забываем предыдущие счётчики, чтобы не пищать
            # на разницу со вчерашними данными и не тащить вчерашние
            # "последние успешные" цифры магазина в подстраховку сегодня
            self._current_date = date_str
            self._last_orders_by_mp = {}
            self._last_fbs_orders_by_mp = {}
            self._last_good_by_shop = {}

        total_orders = 0
        total_revenue = 0.0
        errors = {}
        per_marketplace = {}
        print("[stats %s] polling for %s..." % (ts, date_str))

        # Группируем клиентов по площадке (marketplace id), сохраняя порядок
        # появления — на одной площадке теперь может быть НЕСКОЛЬКО
        # магазинов/API-ключей (см. config.add_marketplace_shop), их
        # заказы/выручку просто суммируем в одну строку "по площадке" —
        # разбивки по магазинам в интерфейсе нет (так и задумано).
        clients_by_mp = {}
        mp_order = []
        for client in build_enabled_clients(self.cfg):
            if client.id not in clients_by_mp:
                clients_by_mp[client.id] = []
                mp_order.append(client.id)
            clients_by_mp[client.id].append(client)

        for mp_id in mp_order:
            shops = clients_by_mp[mp_id]
            mp_orders = 0
            mp_revenue = 0.0
            mp_fbs_orders = 0
            shop_errors = []
            mp_name = shops[0].name
            for i, client in enumerate(shops):
                # Время берём заново перед каждым запросом — иначе по логам
                # не видно, сколько реально ждали именно этот запрос
                # (запутало при отладке таймаутов Yandex).
                client_ts = _now_hms(self.cfg.get("timezone_offset_hours", 3))

                retry_at = self._retry_not_before_by_shop.get(client.key)
                if retry_at is not None and time.time() < retry_at:
                    # Сервер САМ попросил подождать (429 + заголовок с
                    # числом секунд, см. utils/http.py) — ещё не наступило.
                    # НЕ делаем запрос вообще: раз он прямо просит подождать,
                    # долбить его на каждом цикле опроса — только продлевать
                    # себе бан, а не чинить его. Молча используем last_good.
                    wait_left = int(retry_at - time.time())
                    print(
                        "[stats %s]   %s (%s): пропускаю — просили подождать ещё %d с"
                        % (client_ts, client.name, client.key, wait_left)
                    )
                    shop_errors.append("%s: ждём лимит ещё %d с" % (client.key, wait_left))
                    last_good = self._last_good_by_shop.get(client.key)
                    if last_good is not None:
                        mp_orders += last_good["orders"]
                        mp_revenue += last_good["revenue"]
                        mp_fbs_orders += last_good.get("fbs_orders", 0)
                    await asyncio.sleep_ms(0)
                    continue

                breadcrumb.mark("polling %s (%s)" % (client.name, client.key))
                try:
                    stats = client.fetch_daily_stats()
                    mp_orders += stats["orders"]
                    mp_revenue += stats["revenue"]
                    mp_fbs_orders += stats.get("fbs_orders", 0)
                    print(
                        "[stats %s]   %s (%s): %d заказ(ов), %.2f руб"
                        % (client_ts, client.name, client.key, stats["orders"], stats["revenue"])
                    )
                    self._last_good_by_shop[client.key] = {
                        "orders": stats["orders"],
                        "revenue": stats["revenue"],
                        "fbs_orders": stats.get("fbs_orders", 0),
                    }
                    # Успешный запрос — прошлый бан (если был) точно снят.
                    self._retry_not_before_by_shop.pop(client.key, None)
                    # Не бросил исключение — не значит "всё точно ок": у
                    # Ozon (см. marketplaces/ozon.py) один из двух каналов
                    # (FBS/FBO) может молча упасть и подставить кэш, пока
                    # другой отвечает свежими данными — это НЕ считается
                    # фатальной ошибкой (см. try/except MarketplaceError
                    # ниже), но должно быть видно для диагностики, а не
                    # выглядеть как "всё в порядке, просто мало заказов".
                    partial_error = stats.get("partial_error")
                    if partial_error:
                        shop_errors.append("%s: %s" % (client.key, partial_error))
                except MarketplaceError as exc:
                    done_ts = _now_hms(self.cfg.get("timezone_offset_hours", 3))
                    print(
                        "[stats %s->%s]   %s (%s): ошибка — %s"
                        % (client_ts, done_ts, client.name, client.key, exc)
                    )
                    shop_errors.append("%s: %s" % (client.key, exc))
                    if exc.retry_after_sec is not None:
                        # Сервер сказал явно, сколько секунд ждать (429 +
                        # X-RateLimit-Retry/Retry-After) — запоминаем, чтобы
                        # СЛЕДУЮЩИЙ цикл опроса вообще не трогал этот
                        # магазин, пока не пройдёт (см. проверку в начале
                        # этого цикла выше).
                        self._retry_not_before_by_shop[client.key] = time.time() + exc.retry_after_sec
                        print(
                            "[stats %s]   %s (%s): сервер просит подождать %d с"
                            % (done_ts, client.name, client.key, exc.retry_after_sec)
                        )
                    # Подстраховка — берём последние УСПЕШНО полученные
                    # цифры этого МАГАЗИНА вместо нуля, чтобы временная
                    # ошибка API не утаскивала сумму по площадке
                    # вниз-и-обратно (см. коммент у _last_good_by_shop в
                    # __init__). Если успешных данных ещё не было вообще
                    # (например ошибка на самом первом опросе после
                    # включения) — честно 0, подставить нечего.
                    last_good = self._last_good_by_shop.get(client.key)
                    if last_good is not None:
                        mp_orders += last_good["orders"]
                        mp_revenue += last_good["revenue"]
                        mp_fbs_orders += last_good.get("fbs_orders", 0)
                # Пауза между запросами К ОДНОЙ И ТОЙ ЖЕ площадке (несколько
                # магазинов = несколько запросов подряд с одного IP) — чтобы
                # не словить rate limit, реально случалось с Wildberries
                # (HTTP 429) даже с одним магазином при частом опросе.
                # Отдаём управление event loop в обоих случаях — сами
                # HTTP-запросы синхронные (см. utils/http.py) и не
                # прерываются на середине, но так веб-сервер получает шанс
                # ответить, пока идёт опрос.
                if i < len(shops) - 1:
                    await asyncio.sleep_ms(SHOP_REQUEST_GAP_MS)
                else:
                    await asyncio.sleep_ms(0)

            total_orders += mp_orders
            total_revenue += mp_revenue
            per_marketplace[mp_id] = {
                "name": mp_name,
                "orders": mp_orders,
                "revenue": mp_revenue,
                "fbs_orders": mp_fbs_orders,
                "error": "; ".join(shop_errors) if shop_errors else None,
                "updated_at": _now_hms(self.cfg.get("timezone_offset_hours", 3)),
            }
            if shop_errors:
                errors[mp_id] = "; ".join(shop_errors)

        breadcrumb.mark("idle (all marketplaces polled)")
        self.last_errors = errors
        self.per_marketplace = per_marketplace
        ts = _now_hms(self.cfg.get("timezone_offset_hours", 3))
        print(
            "[stats %s] итого за %s: %d заказ(ов), %.2f руб"
            % (ts, date_str, total_orders, total_revenue)
        )

        # Кто из маркетплейсов вырос по сумме заказов (по площадке, все её
        # магазины вместе) с прошлого опроса. orders в per_marketplace —
        # ВСЕГДА реальное число теперь (при ошибке подставляется последнее
        # успешное по каждому магазину отдельно, см. цикл выше) — сравниваем
        # без оглядки на entry["error"], частичный сбой одного магазина
        # площадки не должен глушить обнаружение роста у остальных её
        # магазинов. Список, а не одна проверка "выросло ли суммарно" —
        # чтобы у каждой площадки играть СВОЮ мелодию (notification_sounds),
        # а не одну общую на всех.
        grown = []
        for mp_id, entry in per_marketplace.items():
            prev = self._last_orders_by_mp.get(mp_id, 0)
            if entry["orders"] > prev:
                grown.append(mp_id)
            self._last_orders_by_mp[mp_id] = entry["orders"]

            # Отдельно — рост именно FBS-заказов (сейчас только у Ozon, см.
            # ozon.py). Проверяем ДАЖЕ если mp_id уже попал в grown выше —
            # это разные события: суммарный рост мог быть от FBO (склад
            # Ozon сам всё делает, действие продавца не требуется), а вырос
            # ли именно FBS — отдельный, независимый вопрос. Но играть звук
            # дважды за один и тот же mp_id не нужно — append только если
            # его там ещё нет.
            fbs_prev = self._last_fbs_orders_by_mp.get(mp_id, 0)
            if entry.get("fbs_orders", 0) > fbs_prev and mp_id not in grown:
                grown.append(mp_id)
            self._last_fbs_orders_by_mp[mp_id] = entry.get("fbs_orders", 0)

        beep_enabled = self.cfg["display"].get("beep_on_sale", True)
        if grown and beep_enabled:
            if self._in_night_mode():
                print("[stats %s] новые заказы есть, но ночной режим — молчим: %s" % (ts, grown))
            else:
                for mp_id in grown:
                    sound = self._sound_for_marketplace(mp_id)
                    breadcrumb.mark("playing notification for %s (%s)" % (mp_id, sound))
                    await self.buzzer.play_notification("/notifications/" + sound)
                breadcrumb.mark("idle (after notification)")

        # Суммарно по всем площадкам — нужно для напоминания "Собрать FBS"
        # на экране (см. cfg["display"]["show_fbs_reminder"] и _redraw):
        # оно должно появляться само, когда за сегодня реально есть хотя бы
        # один несобранный FBS-заказ, и пропадать, когда их нет.
        total_fbs_orders = sum(entry.get("fbs_orders", 0) for entry in per_marketplace.values())
        self.latest = {"orders": total_orders, "revenue": total_revenue, "fbs_orders": total_fbs_orders}

        # total_fbs_orders — ОБЯЗАТЕЛЬНО в этом сравнении, не только orders/
        # revenue: заказ уже учтён в сумме/количестве в момент оформления,
        # и когда его потом собирают/отгружают, orders и revenue не
        # меняются вообще — меняется только то, нужно ли ещё его собирать.
        # Без fbs_orders тут экран не перерисовывался бы в момент отгрузки
        # заказа, хотя self.latest уже содержит верные данные — HW-
        # подтверждено пользователем (отгрузил на Yandex, а "Собрать FBS"
        # так и осталось на экране, пока не случился следующий редрав по
        # другой причине).
        current = (total_orders, total_revenue, total_fbs_orders)
        if current != self._displayed:
            await self._redraw()
            self._displayed = current
        else:
            print("[stats %s] данные не изменились — экран не трогаем" % ts)

        return True

    def _sound_for_marketplace(self, marketplace_id):
        overrides = self.cfg.get("notification_sounds", {})
        return overrides.get(marketplace_id) or self.cfg.get("notification_sound", "sale.mid")

    def _in_night_mode(self):
        """cfg["buzzer"]["night_mode"] — окно локального времени, когда
        уведомления о продажах не играются (см. DEFAULT_CONFIG в config.py).
        Не трогает опрос/экран — только гейтит звук в poll_once()."""
        night = self.cfg["buzzer"].get("night_mode", {})
        if not night.get("enabled"):
            return False
        start = _parse_hhmm(night.get("start", ""))
        end = _parse_hhmm(night.get("end", ""))
        if start is None or end is None or start == end:
            return False

        tz = self.cfg.get("timezone_offset_hours", 3)
        now = time.time() + int(tz * 3600)
        _, _, _, hh, mm, _, _, _ = time.gmtime(now)
        cur = hh * 60 + mm

        if start < end:
            return start <= cur < end
        # окно через полночь, например "22:00"-"08:00"
        return cur >= start or cur < end

    async def redraw(self, orders=None, revenue=None):
        """Публичная обёртка над _redraw() — перерисовать экран прямо
        сейчас, без нового опроса маркетплейсов. Нужна например после смены
        фона через веб (см. web_server.py /api/background) — картинка на
        экране должна обновиться сразу, не дожидаясь следующего изменения
        заказов/выручки.

        orders/revenue — если заданы и не 0, подставляются ВМЕСТО
        self.latest (см. web_server.py /api/display/test — ручной ввод
        цифр в веб-интерфейсе, чтобы посмотреть, как это будет выглядеть,
        не дожидаясь реальных данных с такими значениями). 0/None — как
        будто override не задан, показываем реальные данные."""
        await self._redraw(orders, revenue)

    async def _redraw(self, orders_override=None, revenue_override=None):
        tz = self.cfg.get("timezone_offset_hours", 3)
        data = {
            "orders": orders_override if orders_override else self.latest["orders"],
            "revenue": revenue_override if revenue_override else self.latest["revenue"],
            "ip": self.get_ip() or "",
            "updated_at": _current_time_hhmm(tz),
            "updated_date": _current_date_ddmmyyyy(tz),
            # Показываем, только если функция включена в настройках И
            # реально есть хотя бы один FBS-заказ за сегодня — не форсируем
            # надпись вслепую (раньше, пока это был тестовый чекбокс,
            # форсировали).
            "show_fbs_label": (
                self.cfg["display"].get("show_fbs_reminder", False)
                and self.latest.get("fbs_orders", 0) > 0
            ),
        }
        breadcrumb.mark("redrawing display")
        try:
            layout_mod = layout.get_layout(self.display.width, self.display.height)
            layout_mod.update_numbers(self.display.fb, data)
            # display.show() у e-paper — async и внутри отдаёт управление
            # event loop на время busy-wait (~20с), так что веб-сервер не
            # блокируется на всё это время (см. display/epd1in54.py).
            await self.display.show()
            breadcrumb.mark("idle (after redraw)")
        except Exception as exc:
            # Сбой экрана (например HW busy timeout) не должен ронять весь
            # опрос маркетплейсов и веб-сервер.
            print("stats_engine: display error (продолжаем без экрана):", exc)


def _parse_hhmm(s):
    """"22:00" -> 1320 (минуты с полуночи). Некорректная/пустая строка ->
    None — вызывающая сторона (_in_night_mode) трактует это как "выключено",
    а не падает."""
    try:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None


def _current_time_hhmm(tz_offset_hours):
    now = time.time() + int(tz_offset_hours * 3600)
    _, _, _, hh, mm, _, _, _ = time.gmtime(now)
    return "%02d:%02d" % (hh, mm)


def _current_date_ddmmyyyy(tz_offset_hours):
    now = time.time() + int(tz_offset_hours * 3600)
    y, m, d, _, _, _, _, _ = time.gmtime(now)
    return "%02d-%02d-%04d" % (d, m, y)


def _now_hms(tz_offset_hours):
    """Время с секундами — для логов в терминал, чтобы был виден реальный
    интервал между опросами."""
    now = time.time() + int(tz_offset_hours * 3600)
    _, _, _, hh, mm, ss, _, _ = time.gmtime(now)
    return "%02d:%02d:%02d" % (hh, mm, ss)
