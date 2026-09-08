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

from marketplaces.base import MarketplaceClient
from utils.http import request_json
from utils.time_sync import today_local_bounds

API_URL = "https://statistics-api.wildberries.ru/api/v1/supplier/orders"


class WBClient(MarketplaceClient):
    id = "wb"
    name = "Wildberries"
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
        return {"orders": count, "revenue": revenue}
