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
from utils.time_sync import today_local_bounds

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
        for order in orders:
            if order.get("isCancel"):
                continue
            order_date = order.get("date", "")
            if not order_date.startswith(date_str):
                continue
            count += 1
            revenue += float(order.get("priceWithDisc", 0))

        result = {"orders": count, "revenue": revenue}
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
            result["partial_error"] = "несобранные заказы: %s" % exc
        result["fbs_orders"] = pending
        return result

    def _fetch_pending_count(self, headers):
        data = request_json("GET", NEW_ORDERS_URL, headers=headers)
        return len(data.get("orders", []))
