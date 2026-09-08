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

from marketplaces.base import MarketplaceClient
from utils.http import request_json
from utils.time_sync import today_utc_bounds_z

FBS_URL = "https://api-seller.ozon.ru/v3/posting/fbs/list"
FBO_URL = "https://api-seller.ozon.ru/v2/posting/fbo/list"
CANCELLED_STATUS = "cancelled"
# TODO: если в день будет больше 1000 отправлений по одному из каналов —
# понадобится пагинация (result.has_next / offset). Для одного продавца
# с небольшим ассортиментом это маловероятно, оставлено как есть.


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
        fbs_count, fbs_revenue = self._fetch_fbs(headers)
        fbo_count, fbo_revenue = self._fetch_fbo(headers)
        return {
            "orders": fbs_count + fbo_count,
            "revenue": fbs_revenue + fbo_revenue,
            # Отдельно от общего orders — нужно stats_engine, чтобы играть
            # звук именно на новый FBS-заказ (см. StatsEngine.poll_once):
            # FBS продавец обязан собрать и отправить сам, а FBO уже лежит
            # на складе Ozon — то есть FBS реально требует его действия
            # прямо сейчас, в отличие от FBO. WB/Yandex такого разделения
            # не имеют (их API не различает FBS/FBO в наших запросах) — у
            # них этого поля в возвращаемом словаре просто нет, stats_engine
            # трактует отсутствие как 0.
            "fbs_orders": fbs_count,
        }

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
        return _sum_postings(postings)

    def _fetch_fbo(self, headers):
        # /v2/posting/fbo/list на самом деле хочет то же самое, что и FBS —
        # полноценный google.protobuf.Timestamp (RFC3339 с "Z"), а не просто
        # дату. Сам Ozon подсказал это в тексте ошибки на дату без времени:
        # "invalid google.protobuf.Timestamp value" — расходится с тем, что
        # написано в комментариях сторонней Go-библиотеки, которой я
        # ориентировался при первой реализации.
        since_iso, to_iso = today_utc_bounds_z(
            self.settings.get("timezone_offset_hours", 3),
            self.settings.get("day_offset", 0),
        )
        body = {
            "filter": {"since": since_iso, "to": to_iso, "status": ""},
            "limit": 1000,
            "offset": 0,
        }
        data = request_json("POST", FBO_URL, headers=headers, json_body=body)
        postings = data.get("result", [])
        return _sum_postings(postings)


def _sum_postings(postings):
    count = 0
    revenue = 0.0
    for posting in postings:
        if posting.get("status") == CANCELLED_STATUS:
            continue
        count += 1
        for product in posting.get("products", []):
            try:
                price = float(product.get("price", 0))
            except (TypeError, ValueError):
                price = 0.0
            revenue += price * int(product.get("quantity", 1))
    return count, revenue
