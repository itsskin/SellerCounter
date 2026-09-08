from marketplaces.ozon import OzonClient
from marketplaces.wb import WBClient
from marketplaces.yandex import YandexClient

# Чтобы добавить новый маркетплейс: создать marketplaces/<id>.py с классом
# — наследником MarketplaceClient (см. marketplaces/base.py), и добавить его
# сюда. Веб-интерфейс и stats_engine дальше подхватывают его автоматически.
# Порядок в этом списке = порядок карточек в веб-интерфейсе (Ozon, WB,
# Yandex) — используем список, а не порядок ключей словаря, чтобы порядок
# не зависел от деталей реализации dict в конкретной сборке MicroPython.
REGISTRY_ORDER = [OzonClient, WBClient, YandexClient]
REGISTRY = {cls.id: cls for cls in REGISTRY_ORDER}


def get_client_class(marketplace_id):
    return REGISTRY.get(marketplace_id)


def available_marketplaces():
    return [
        {"id": cls.id, "name": cls.name, "required_fields": list(cls.required_fields)}
        for cls in REGISTRY_ORDER
    ]


def build_enabled_clients(cfg):
    """Маркетплейс опрашивается, если для него заполнены все нужные поля
    (ID/ключ) — отдельного тумблера "включён" нет: заполнил ключи, значит
    активен, стёр — значит нет."""
    clients = []
    for entry in cfg["marketplaces"]:
        cls = get_client_class(entry["id"])
        if cls is None or not cls.is_configured(entry):
            continue
        settings = dict(entry)
        settings["timezone_offset_hours"] = cfg.get("timezone_offset_hours", 3)
        settings["day_offset"] = cfg.get("debug_day_offset", 0)
        clients.append(cls(settings))
    return clients
