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

from marketplaces.base import MarketplaceClient
from utils.http import request_json
from utils.time_sync import today_local_bounds

API_URL_TEMPLATE = "https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/orders"
CANCELLED_STATUS = "CANCELLED"


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
        return {"orders": count, "revenue": revenue}
