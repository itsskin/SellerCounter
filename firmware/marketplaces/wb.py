# Wildberries Statistics API.
# ВАЖНО: сверить с актуальной документацией перед использованием —
# https://dev.wildberries.ru/openapi/api-information (метод /supplier/orders).
#
# Считаем ЗАКАЗЫ (оформление), а не ВЫКУПЫ — единообразно с Ozon и Yandex,
# которые тоже считают по моменту оформления заказа, а не по факту выкупа.
#
# Раньше здесь стоял /supplier/sales ("выкупы") — сознательный выбор, чтобы
# не ловить заказы, которые потом отменят/не выкупят. На практике оказалось
# хуже: поле "date" в /sales — это дата ВЫКУПА, а не заказа. Заказ,
# оформленный много дней назад, в день фактического выкупа засчитывался
# "продажей сегодня" — HW-подтверждено сравнением одного и того же товара
# в /sales (date=выкуп, сегодня) и /orders (date=05.08, заказ почти
# две недели назад) плюс официальным отчётом поставщика WB (колонки
# "Заказано"/"Выкупили" по датам не совпадали). Пользователю нужна реакция
# на момент заказа, а не на выкуп — переключились на /orders и фильтруем
# отменённые через isCancel (это поле есть в /orders, в /sales его не было).
#
# Метод отдаёт записи начиная с dateFrom (не только за один день), поэтому
# агрегируем на плате: берём dateFrom = начало сегодняшнего дня и фильтруем
# локально по полю date (дата оформления заказа) + isCancel.

from marketplaces.base import MarketplaceClient, MarketplaceError
from utils.http import request_json
from utils.time_sync import today_local_bounds, today_unix_bounds

API_URL = "https://statistics-api.wildberries.ru/api/v1/supplier/orders"

# ДРУГОЙ домен и, судя по документации, отдельная категория API-ключа
# ("Marketplace", не "Statistics", которым пользуется API_URL выше) —
# https://dev.wildberries.ru/en/docs/openapi/orders-fbs. Проверено вручную
# на реальном аккаунте (2026-09-12): существующий ключ доступ имеет, но это
# не гарантировано для всех продавцов — если у сохранённого ключа нет прав
# именно на Marketplace-категорию, этот запрос будет падать отдельно от
# основного /supplier/orders. Обрабатываем как частичный сбой (см. ozon.py
# partial_error) — не роняем весь опрос ради одного счётчика напоминания.
#
# Отдаёт УЖЕ отфильтрованный сервером список — заказы со supplierStatus
# "new" (см. документацию: "new" = ожидает сборки, "confirm" = взят в
# сборку/поставку, "complete" = в доставке, "cancel" = отменён продавцом).
# Специально не завязан на календарный день — заказ, оформленный вчера
# поздно вечером и до сих пор не собранный, должен продолжать считаться
# "несобранным" и сегодня, а не пропадать из счётчика в полночь. HW-
# подтверждено пользователем на Yandex (см. yandex.py) — тот же принцип
# относится и к WB.
NEW_ORDERS_URL = "https://marketplace-api.wildberries.ru/api/v3/orders/new"

# FBS-заказы продавца за период (Marketplace API, в реальном времени) и их
# статусы. /supplier/orders (Statistics API) отдаёт данные с задержкой —
# свежий FBS-заказ может появиться там спустя десятки минут, и пока он
# "новый" (и горит "Собрать FBS"), в счётчике заказов его ещё нет. Поэтому к
# статистике добавляем FBS-заказы за сегодня, которых там пока нет (сверка по
# rid = srid из статистики).
FBS_ORDERS_URL = "https://marketplace-api.wildberries.ru/api/v3/orders"
FBS_STATUS_URL = "https://marketplace-api.wildberries.ru/api/v3/orders/status"
_CANCELLED_SUPPLIER = ("cancel",)
_CANCELLED_WB = ("canceled", "canceled_by_client", "declined_by_client")


class WBClient(MarketplaceClient):
    id = "wb"
    name = "Wildberries"
    short_label = "Wb"
    required_fields = ("api_key",)

    def fetch_daily_stats(self):
        start_iso, _, date_str = today_local_bounds(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        url = "%s?dateFrom=%s&flag=0" % (API_URL, start_iso)
        headers = {"Authorization": self.settings["api_key"]}
        orders = request_json("GET", url, headers=headers)

        count = 0
        revenue = 0.0
        seen = set()  # srid заказов, уже учтённых статистикой (в т.ч. отменённых)
        for order in orders:
            srid = order.get("srid")
            if srid:
                seen.add(srid)
            if order.get("isCancel"):
                continue
            order_date = order.get("date", "")
            if not order_date.startswith(date_str):
                continue
            count += 1
            revenue += float(order.get("priceWithDisc", 0))

        result = {}
        partial = []
        try:
            extra_count, extra_revenue = self._fetch_fbs_not_in_stats(headers, seen)
            count += extra_count
            revenue += extra_revenue
        except MarketplaceError as exc:
            partial.append("FBS-заказы: %s" % exc)

        result["orders"] = count
        result["revenue"] = revenue
        try:
            pending = self._fetch_pending_count(headers)
        except MarketplaceError as exc:
            # НЕ откатываемся на "последнее успешное" значение — см.
            # подробное объяснение у yandex.py (fetch_daily_stats): для
            # этого конкретного счётчика стухший кэш может ЗАЛИПНУТЬ
            # реминдер "Собрать FBS" горящим даже после того, как заказ
            # реально собрали/отменили, если ошибка API совпала именно с
            # этим моментом. Честный 0 — меньшее из двух зол.
            pending = 0
            partial.append("несобранные заказы: %s" % exc)
        result["fbs_orders"] = pending
        if partial:
            result["partial_error"] = "; ".join(partial)
        return result

    def _fetch_fbs_not_in_stats(self, headers, seen_srids):
        """FBS-заказы за сегодня из Marketplace API, которых ещё нет в
        статистике (seen_srids), без отменённых. Возвращает (кол-во, сумма)."""
        since, to = today_unix_bounds(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        fresh = []  # (id, цена в рублях)
        next_value = 0
        for _ in range(5):  # до 5000 заказов за день — с большим запасом
            url = "%s?limit=1000&next=%d&dateFrom=%d&dateTo=%d" % (FBS_ORDERS_URL, next_value, since, to)
            data = request_json("GET", url, headers=headers)
            batch = data.get("orders", [])
            for order in batch:
                rid = order.get("rid")
                if rid and rid in seen_srids:
                    continue
                # price — в копейках (валюта продавца)
                fresh.append((order.get("id"), float(order.get("price", 0)) / 100))
            next_value = data.get("next", 0)
            if len(batch) < 1000 or not next_value:
                break
        if not fresh:
            return 0, 0.0

        cancelled = set()
        ids = [order_id for order_id, _ in fresh if order_id is not None]
        for i in range(0, len(ids), 500):
            status = request_json(
                "POST", FBS_STATUS_URL, headers=headers, json_body={"orders": ids[i:i + 500]}
            )
            for item in status.get("orders", []):
                if item.get("supplierStatus") in _CANCELLED_SUPPLIER or item.get("wbStatus") in _CANCELLED_WB:
                    cancelled.add(item.get("id"))

        count = 0
        revenue = 0.0
        for order_id, price in fresh:
            if order_id in cancelled:
                continue
            count += 1
            revenue += price
        return count, revenue

    def _fetch_pending_count(self, headers):
        data = request_json("GET", NEW_ORDERS_URL, headers=headers)
        return len(data.get("orders", []))
