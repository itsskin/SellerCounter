# Yandex Market Partner API.
# ВАЖНО: сверить с актуальной документацией перед использованием —
# https://yandex.ru/dev/market/partner-api/doc/ru/reference/orders/getOrders
# (метод /v2/campaigns/{campaignId}/orders — версия в пути обязательна,
# без неё был HTTP 505).
#
# Авторизация — заголовок Api-Key, а не Authorization: Bearer. У API
# Яндекс Маркета два способа авторизации (OAuth-токен через Bearer, или
# API-ключ через Api-Key) — токен, выданный в кабинете партнёра без
# отдельной OAuth-регистрации приложения, это именно API-ключ.

from marketplaces.base import MarketplaceClient, MarketplaceError
from utils.http import request_json
from utils.time_sync import today_local_bounds

API_URL_TEMPLATE = "https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/orders"
CANCELLED_STATUS = "CANCELLED"
# Ещё не подготовлен к отправке — см. документацию Yandex Market Partner
# API (updateOrderStatus/getOrder): жизненный цикл заказа —
# PROCESSING/STARTED ("оформлен, продавец ещё должен его подготовить") ->
# PROCESSING/READY_TO_SHIP (уже подготовлен, ждёт передачи в доставку) ->
# PROCESSING/SHIPPED -> DELIVERY/... Только STARTED реально требует
# действия продавца прямо сейчас — READY_TO_SHIP и дальше уже сделаны.
# Проверено на реальном заказе (2026-09-12): оформлен вчера в 23:56,
# сегодня всё ещё STARTED — то есть подтверждено, что статус не сбрасывается
# сам по себе с наступлением новых суток, в отличие от прежнего счётчика
# (который был завязан на календарный день — см. _fetch_pending_count).
PENDING_STATUS = "PROCESSING"
PENDING_SUBSTATUS = "STARTED"

_last_good_pending = {}


class YandexClient(MarketplaceClient):
    id = "yandex"
    name = "Yandex Market"
    required_fields = ("campaign_id", "api_key")

    def fetch_daily_stats(self):
        _, _, date_str = today_local_bounds(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        url = API_URL_TEMPLATE.format(campaign_id=self.settings["campaign_id"])
        url += "?fromDate=%s&toDate=%s" % (date_str, date_str)
        headers = {"Api-Key": self.settings["api_key"]}
        data = request_json("GET", url, headers=headers)

        orders = data.get("orders", [])
        count = 0
        revenue = 0.0
        for order in orders:
            if order.get("status") == CANCELLED_STATUS:
                continue
            count += 1
            revenue += float(order.get("buyerTotal", order.get("buyerItemsTotal", 0)))

        result = {"orders": count, "revenue": revenue}
        try:
            pending = self._fetch_pending_count(headers)
            _last_good_pending[self.key] = pending
        except MarketplaceError as exc:
            pending = _last_good_pending.get(self.key, 0)
            result["partial_error"] = "несобранные заказы: %s" % exc
        result["fbs_orders"] = pending
        return result

    def _fetch_pending_count(self, headers, lookback_days=7):
        # ОТДЕЛЬНЫЙ запрос за более широкое окно (по умолчанию 7 дней) —
        # именно для счётчика "ещё не собран", НЕ для orders/revenue (те
        # остаются строго за сегодня, см. fetch_daily_stats выше). Без
        # этого заказ, оформленный вчера поздно вечером и до сих пор не
        # собранный, переставал бы учитываться ровно в полночь — просто
        # выпадал бы из диапазона запроса, хотя физически его всё ещё нужно
        # собрать. HW-подтверждено: реальный заказ на этом аккаунте,
        # оформленный вчера в 23:56, был причиной исходной жалобы.
        _, _, date_str_from = today_local_bounds(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0) - lookback_days,
        )
        _, _, date_str_to = today_local_bounds(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        url = API_URL_TEMPLATE.format(campaign_id=self.settings["campaign_id"])
        url += "?fromDate=%s&toDate=%s" % (date_str_from, date_str_to)
        data = request_json("GET", url, headers=headers)
        orders = data.get("orders", [])
        return sum(
            1 for o in orders
            if o.get("status") == PENDING_STATUS and o.get("substatus") == PENDING_SUBSTATUS
        )
