class MarketplaceError(Exception):
    def __init__(self, message, retry_after_sec=None):
        super().__init__(message)
        # Если сервер прислал rate-limit заголовок с числом секунд до
        # следующей попытки (см. utils/http.py._retry_after_from_headers) —
        # он тут. None, если такого заголовка не было (обычная ошибка сети/
        # сервера) или он не распарсился — тогда просто ждём до следующего
        # обычного цикла опроса, как раньше.
        self.retry_after_sec = retry_after_sec


class MarketplaceClient:
    """Общий интерфейс клиента маркетплейса.

    Наследники должны определить `id`, `name` и реализовать
    `fetch_daily_stats()`, возвращающий словарь вида
    {"orders": int, "revenue": float}. Это данные ЗА СЕГОДНЯ (границы дня —
    локальные, см. utils/time_sync.py).
    """

    id = "base"
    name = "Base marketplace"
    # Короткая подпись (2 латинские буквы) для экрана "детализация по
    # маркетплейсам" (см. display/layout_400x300.py, cfg["display"]
    # ["show_marketplace_breakdown"]) — там нет места под полное name.
    short_label = "??"
    # Список ключей настроек, которые нужны в config["marketplaces"][i],
    # помимо "id" и "enabled". Используется веб-формой, чтобы знать какие
    # поля показать пользователю.
    required_fields = ()

    def __init__(self, settings):
        self.settings = settings
        # Уникальный ключ ИМЕННО ЭТОГО магазина (не площадки — на одной
        # площадке их может быть несколько, см. config.py) — используется
        # stats_engine, чтобы держать "последнее успешное значение" отдельно
        # на каждый магазин при частичном сбое одного из них.
        self.key = settings.get("key")

    def fetch_daily_stats(self):
        raise NotImplementedError

    @classmethod
    def is_configured(cls, settings):
        return all(settings.get(field) for field in cls.required_fields)
