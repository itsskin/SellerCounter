# Ozon Seller API.
# ВАЖНО: сверить с актуальной документацией перед использованием —
# https://docs.ozon.ru/api/seller/ (эндпоинты периодически меняются).
#
# /v1/analytics/data оказался недоступен на реальном аккаунте — стабильно
# отдавал 429 "rate limit exceeded" даже на самый первый запрос со свежим
# ключом (проверено curl'ом в обход платы). Похоже, метод требует Ozon
# Premium/Premium Plus. Поэтому считаем продажи сами — по спискам
# отправлений FBS и FBO за сегодня (оба метода не требуют Premium),
# суммируя оба канала. Схемы полей сверены с реальной Go-библиотекой
# github.com/diphantxm/ozon-api-client (ozon/fbs.go, ozon/fbo.go).
#
# "Заказы" здесь — количество отправлений (posting) за день, не сумма
# количества товаров в них (иначе не совпадало бы по смыслу с тем, как
# считает Wildberries-клиент). "Выручка" — валовая сумма (что заплатил
# покупатель), без вычета комиссии Ozon и логистики.

from marketplaces.base import MarketplaceClient, MarketplaceError
from utils.http import request_json
from utils.time_sync import today_utc_bounds_z

FBS_URL = "https://api-seller.ozon.ru/v3/posting/fbs/list"
# /v2/posting/fbo/list стабильно отдавал HTTP 429 "rate limit per second" на
# этом аккаунте много часов подряд, включая одиночные запросы с интервалом
# в несколько минут (не похоже на настоящий троттлинг по частоте) — завели
# тикет в поддержку Ozon, порекомендовали перейти на /v3/posting/fbo/list.
# Проверено вручную curl'ом в обход платы (реальный Client-Id/Api-Key,
# 2026-09-11): v3 отвечает 200 с реальными данными, пока v2 в это же время
# по-прежнему 429. У v3 другой контракт, оба момента учтены ниже:
#  - лимit максимум 100 за раз (валидатор v3 прямо ругается на 1000:
#    "invalid PostingFboListRequest.Limit: value must be inside range
#    (0, 100]"), у v2 было до 1000.
#  - тело ответа БЕЗ обёртки "result" — сразу {"has_next", "cursor",
#    "postings"} в корне, не {"result": [...]} как у v2.
#  - "products[].price" — не плоское число (как у FBS), а вложенный объект
#    {"amount": "1050", "currency": "RUB"} — учтено в _sum_postings.
FBO_URL = "https://api-seller.ozon.ru/v3/posting/fbo/list"
FBO_LIST_LIMIT = 100
CANCELLED_STATUS = "cancelled"
# Статусы FBS-отправления, при которых продавец ЕЩЁ должен его физически
# собрать — используется только для счётчика напоминания "Собрать FBS"
# (см. "fbs_orders" в fetch_daily_stats), не для orders/revenue (там считаем
# ВСЕ несортированные заказы, включая уже собранные и отправленные).
# "awaiting_packaging" — официальное имя статуса по документации Ozon
# (https://docs.ozon.ru/api/seller/, раздел posting.status): "ожидает
# сборки". После сборки статус переходит в "awaiting_deliver" (упаковано,
# ждёт передачи в доставку) — с этого момента продавцу по этому
# отправлению уже физически нечего делать, поэтому дальше в список не
# входит. ВАЖНО: сверить с актуальной документацией, если Ozon когда-нибудь
# переименует статусы.
PENDING_FBS_STATUS = "awaiting_packaging"
# TODO: если в день будет больше 1000 отправлений по FBS или больше
# FBO_LIST_LIMIT (100) по FBO — понадобится пагинация. У FBS она через
# offset (см. _fetch_fbs), у FBO v3 — ЧЕРЕЗ CURSOR (data["has_next"]/
# data["cursor"]), не offset (offset в теле запроса v3, похоже, просто
# игнорируется дальше первой страницы — не проверяли на практике, страниц
# больше одной пока не бывало). Для одного продавца с небольшим
# ассортиментом такое маловероятно, оставлено как есть.

# Последние успешно полученные данные ПО КАЖДОМУ КАНАЛУ отдельно (FBS/FBO),
# на магазин (ключ — settings["key"], например "ozon-1" — на случай
# нескольких магазинов Ozon). У FBS кортеж (count, revenue, pending) — у
# FBO просто (count, revenue), см. _fetch_fbo: понятия "ещё не собран" для
# FBO не существует, заказ и так уже на складе Ozon. Модульный уровень, не
# атрибут
# OzonClient — build_enabled_clients() создаёт новый инстанс клиента на
# КАЖДЫЙ цикл опроса (см. marketplaces/registry.py), инстанс не переживает
# между опросами, а этот кэш должен.
#
# Нужен, потому что FBS и FBO — это два НЕЗАВИСИМЫХ HTTP-запроса, и один
# может сломаться, пока другой прекрасно работает (HW-подтверждено: Ozon
# реально отдавал 429 стабильно на /v2/posting/fbo/list несколько минут,
# пока /v3/posting/fbs/list на то же время отвечал нормально). Раньше
# fetch_daily_stats() был "всё или ничего" — сбой ЛЮБОГО из двух вызовов
# ронял исключение ДО return, и уже полученные данные рабочего канала
# просто выбрасывались, а не только сломанного. Теперь при сбое ОДНОГО
# канала берём последнее успешное значение ИМЕННО ЭТОГО канала (не 0) —
# рабочий канал при этом остаётся полностью свежим.
_last_good_fbs = {}
_last_good_fbo = {}


class OzonClient(MarketplaceClient):
    id = "ozon"
    name = "Ozon"
    required_fields = ("client_id", "api_key")

    def fetch_daily_stats(self):
        headers = {
            "Client-Id": self.settings["client_id"],
            "Api-Key": self.settings["api_key"],
            "Content-Type": "application/json",
        }

        try:
            fbs_count, fbs_revenue, fbs_pending = self._fetch_fbs(headers)
            _last_good_fbs[self.key] = (fbs_count, fbs_revenue, fbs_pending)
            fbs_error = None
        except MarketplaceError as exc:
            fbs_count, fbs_revenue, fbs_pending = _last_good_fbs.get(self.key, (0, 0.0, 0))
            fbs_error = exc

        try:
            fbo_count, fbo_revenue = self._fetch_fbo(headers)
            _last_good_fbo[self.key] = (fbo_count, fbo_revenue)
            fbo_error = None
        except MarketplaceError as exc:
            fbo_count, fbo_revenue = _last_good_fbo.get(self.key, (0, 0.0))
            fbo_error = exc

        if fbs_error is not None and fbo_error is not None:
            # Оба канала упали В ЭТОМ цикле — сообщить об ошибке целиком и
            # отдать разбираться дальше (см. stats_engine.poll_once —
            # у него есть свой, отдельный откат на last_good ВСЕГО
            # магазина, этого достаточно, не дублируем ту же подстраховку
            # тут ещё раз на уровне канала).
            raise MarketplaceError("FBS: %s; FBO: %s" % (fbs_error, fbo_error))

        result = {
            "orders": fbs_count + fbo_count,
            "revenue": fbs_revenue + fbo_revenue,
            # ВАЖНО: это НЕ "все FBS-заказы за сегодня" (тот count уже учтён
            # в orders/revenue выше) — а только те, что ещё в статусе
            # PENDING_FBS_STATUSES, то есть продавцу ещё физически нужно их
            # собрать. Раньше тут был общий fbs_count, и напоминание
            # "Собрать FBS" на экране (см. StatsEngine._redraw,
            # www/index.html) не гасло весь день даже после того, как заказ
            # реально собрали и отправили — HW-подтверждено пользователем
            # (собрал и отправил, в личном кабинете 0 висящих, а на экране
            # надпись осталась). Тем же полем играется звук на новый
            # FBS-заказ (см. StatsEngine.poll_once) — рост НЕсобранных при
            # опросе работает для этого ничуть не хуже роста общего count.
            # FBO тут нет вообще — эти заказы уже на складе Ozon, продавцу
            # физически нечего "собирать". WB/Yandex такого разделения не
            # имеют (их API не различает FBS/FBO) — у них этого поля в
            # возвращаемом словаре просто нет, stats_engine трактует
            # отсутствие как 0.
            "fbs_orders": fbs_pending,
        }
        if fbs_error is not None or fbo_error is not None:
            # Ровно ОДИН канал упал (оба сразу — см. raise выше) — это уже
            # не "всё в порядке", хоть и не повод отбрасывать данные
            # рабочего канала (см. комментарий у _last_good_fbs/_last_good_fbo
            # выше). Раньше такой частичный сбой был вообще не виден в
            # веб-интерфейсе: fetch_daily_stats() просто возвращал числа как
            # ни в чём не бывало, а stats_engine.poll_once() пишет в
            # per_marketplace[...]["error"] только когда сюда прилетает
            # исключение (см. except MarketplaceError). Пользователь видел
            # "1 заказ" без единого намёка, что часть данных на самом деле
            # устаревшая (кэш _last_good_fbo, а не свежий ответ Ozon) —
            # обнаружили это только ручной диагностикой через serial, когда
            # в личном кабинете Ozon заказов было больше, чем на экране.
            # Отдаём эту причину отдельным полем — stats_engine добавляет
            # его в error без отбрасывания уже посчитанных orders/revenue.
            parts = []
            if fbs_error is not None:
                parts.append("FBS: %s" % fbs_error)
            if fbo_error is not None:
                parts.append("FBO: %s" % fbo_error)
            result["partial_error"] = "; ".join(parts)
        return result

    def _fetch_fbs(self, headers):
        # /v3/posting/fbs/list хочет since/to как настоящие UTC-моменты в
        # формате RFC3339 с "Z" на конце.
        since_iso, to_iso = today_utc_bounds_z(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        body = {
            "dir": "ASC",
            "filter": {"since": since_iso, "to": to_iso, "status": ""},
            "limit": 1000,
            "offset": 0,
            "with": {"financial_data": False},
        }
        data = request_json("POST", FBS_URL, headers=headers, json_body=body)
        postings = data.get("result", {}).get("postings", [])
        count, revenue = _sum_postings(postings)
        pending = self._fetch_pending_fbs_count(headers)
        return count, revenue, pending

    def _fetch_pending_fbs_count(self, headers, lookback_days=7):
        # ОТДЕЛЬНЫЙ запрос за более широкое окно (по умолчанию 7 дней) —
        # именно для счётчика "ещё не собран", НЕ для orders/revenue (те
        # остаются строго за сегодня, см. _fetch_fbs выше). Если ограничить
        # проверку "несобранности" только сегодняшними отправлениями, заказ,
        # оформленный вчера поздно вечером и до сих пор не собранный,
        # перестаёт учитываться ровно в полночь — просто выпадает из
        # диапазона запроса, хотя физически его всё ещё нужно собрать.
        # HW-подтверждено пользователем: заказ на Yandex в 23:56 корректно
        # засветил напоминание, а в 00:00 (новые сутки) оно погасло само,
        # хотя заказ так и остался несобранным — тот же принцип относится и
        # к Ozon. Фильтр по статусу передаём самому Ozon ("status":
        # "awaiting_packaging" вместо "") — сервер сам отдаёт уже
        # отфильтрованное, не нужно тащить все отправления за неделю ради
        # подсчёта.
        since_iso, _ = today_utc_bounds_z(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0) - lookback_days,
        )
        _, to_iso = today_utc_bounds_z(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        body = {
            "dir": "ASC",
            "filter": {"since": since_iso, "to": to_iso, "status": PENDING_FBS_STATUS},
            "limit": 1000,
            "offset": 0,
            "with": {"financial_data": False},
        }
        data = request_json("POST", FBS_URL, headers=headers, json_body=body)
        postings = data.get("result", {}).get("postings", [])
        return len(postings)

    def _fetch_fbo(self, headers):
        # since/to — полноценный google.protobuf.Timestamp (RFC3339 с "Z"),
        # а не просто дата: так хотел ещё v2, и v3 требует то же самое.
        since_iso, to_iso = today_utc_bounds_z(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        body = {
            "filter": {"since": since_iso, "to": to_iso, "status": ""},
            "limit": FBO_LIST_LIMIT,
            "offset": 0,
        }
        data = request_json("POST", FBO_URL, headers=headers, json_body=body)
        # v3 отдаёт "postings" сразу в корне, БЕЗ обёртки "result" (та была
        # у v2) — см. комментарий у FBO_URL выше.
        postings = data.get("postings", [])
        return _sum_postings(postings)


def _sum_postings(postings):
    count = 0
    revenue = 0.0
    for posting in postings:
        if posting.get("status") == CANCELLED_STATUS:
            continue
        count += 1
        for product in posting.get("products", []):
            price_field = product.get("price", 0)
            # FBS (v3) отдаёт price ПЛОСКИМ числом/строкой ("293.0000").
            # FBO (v3) отдаёт вложенный объект {"amount": "1050",
            # "currency": "RUB"} — разные контракты у формально одной и той
            # же версии API, HW-подтверждено сравнением реальных ответов.
            if isinstance(price_field, dict):
                price_field = price_field.get("amount", 0)
            try:
                price = float(price_field)
            except (TypeError, ValueError):
                price = 0.0
            revenue += price * int(product.get("quantity", 1))
    return count, revenue
