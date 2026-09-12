# Модуль называется sc_http, а не requests/urequests — в прошивке этой платы
# (кастомная Octal-SPIRAM сборка) есть ВШИТЫЙ в firmware ("frozen") модуль с
# именем requests, и .frozen стоит в sys.path раньше /lib — наш файл с тем же
# именем никогда бы не перекрыл его, поэтому назвали иначе. См. lib/VENDORED.md.
import time

try:
    import _thread
except ImportError:  # pragma: no cover — на симуляторе/хосте может не быть
    _thread = None

import sc_http as requests

from marketplaces.base import MarketplaceError

# Заголовки с rate-limit-таймингом — сверено с официальной документацией
# каждой площадки (docs.ozon.ru/api/seller/, yandex.ru/dev/market/
# partner-api/doc/ru/concepts/limits) плюс реальным HW-ответом WB:
#
# - Wildberries: "X-RateLimit-Retry" (сек., целое число) — из текста
#   реальной 429-ошибки: "retry after the period specified in the
#   X-RateLimit-Retry header".
# - Yandex Market: заголовок "X-RateLimit-Resource-Until" на ответе с
#   кодом 420 Enhance Your Calm — но это НЕ секунды, а абсолютная дата в
#   формате RFC822/RFC1123 ("Thu, 10 Jul 2018 00:42:42 GMT"). Лимит на
#   опрашиваемый нами /v2/campaigns/{campaignId}/orders — 10 000
#   запросов в час, при поллинге раз в 5 минут упереться в него почти
#   нереально, но заголовок разбираем на случай ресурсного ограничения.
# - Ozon: в документации НЕТ retry-after-заголовка для методов, которые
#   мы используем (/v3/posting/fbs/list, /v2/posting/fbo/list) — такой
#   заголовок ("Item-Retry-After", в минутах) есть только у методов
#   загрузки/обновления товаров, которые мы не вызываем. У Ozon есть
#   общий лимит 50 запросов/сек на Client ID (нам недостижим) и явное
#   предупреждение "мы можем ограничить доступ ... без предупреждения"
#   при подозрительном трафике — поэтому Ozon намеренно не спамили
#   реальными запросами ради проверки; используем только стандартный
#   "Retry-After" (RFC 9110) на случай, если он всё же появится.
_RETRY_AFTER_SECONDS_HEADERS = ("x-ratelimit-retry",)
_RETRY_AFTER_DATE_HEADERS = ("x-ratelimit-resource-until",)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_http_date(value):
    """Разбирает HTTP-дату вида "Thu, 10 Jul 2018 00:42:42 GMT" (формат
    RFC822/RFC1123) в epoch-секунды платы (та же шкала, что и time.time()
    — HW-подтверждено: time.mktime(time.gmtime(t)) == t на этой прошивке).
    None, если формат не разобрался."""
    try:
        parts = value.split()
        day = int(parts[1])
        month = _MONTHS[parts[2].lower()[:3]]
        year = int(parts[3])
        hh, mm, ss = (int(x) for x in parts[4].split(":"))
        return time.mktime((year, month, day, hh, mm, ss, 0, 0))
    except (IndexError, ValueError, KeyError):
        return None


def _retry_after_from_headers(headers):
    """Ищет секунды до следующей попытки в заголовках ответа (без учёта
    регистра — sc_http хранит их как сервер прислал, не нормализует).
    None, если ни один из известных заголовков не пришёл или не
    разобрался — тогда просто ждём до следующего обычного цикла опроса."""
    if not headers:
        return None
    lower = dict((k.lower(), v) for k, v in headers.items())

    for name in _RETRY_AFTER_SECONDS_HEADERS:
        if name in lower:
            try:
                return int(lower[name])
            except (TypeError, ValueError):
                pass

    if "retry-after" in lower:
        val = lower["retry-after"]
        try:
            return int(val)
        except (TypeError, ValueError):
            as_epoch = _parse_http_date(val)
            if as_epoch is not None:
                return max(0, as_epoch - time.time())

    for name in _RETRY_AFTER_DATE_HEADERS:
        if name in lower:
            as_epoch = _parse_http_date(lower[name])
            if as_epoch is not None:
                return max(0, as_epoch - time.time())

    return None


def _do_request(method, url, headers, json_body, timeout):
    response = None
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
        if response.status_code >= 400:
            retry_after = _retry_after_from_headers(getattr(response, "headers", None))
            raise MarketplaceError(
                "HTTP %d from %s: %s" % (response.status_code, url, response.text[:400]),
                retry_after_sec=retry_after,
            )
        return response.json()
    finally:
        if response is not None:
            response.close()


def request_json(method, url, headers=None, json_body=None, timeout=15):
    """Тонкая обёртка над requests с разбором JSON, понятными ошибками и
    ЖЁСТКИМ верхним пределом по времени на весь запрос целиком.

    timeout передаётся в requests.request -> s.settimeout, но одной этой
    защиты оказалось недостаточно: сам sc_http честно предупреждает (см.
    комментарий у wrap_socket в lib/sc_http/__init__.py), что settimeout,
    поставленный на raw-сокет ДО обёртки в TLS, "не всегда переживает
    обёртку... на некоторых портах MicroPython" — то есть даже повторная
    установка после wrap_socket не 100% гарантия на каждом этапе (DNS,
    connect, TLS handshake, чтение заголовков, чтение тела). Если
    settimeout молча не сработает хоть на одном из них — чтение
    зависнет НАВСЕГДА, а поскольку весь проект (веб-сервер, watchdog-
    подкормка, опрос — всё) крутится в одном потоке/event loop, это
    замораживает плату целиком без единого исключения в консоли (HW-
    подтверждено: watchdog срабатывал сам по себе после нескольких минут
    полной тишины, хотя память и сокеты были в порядке — то есть не крах,
    а именно тихое зависание).

    Поэтому реальный HTTP-запрос выполняется в отдельном потоке (_thread,
    второе ядро ESP32-S3), а тут — просто ожидание результата с жёстким
    дедлайном (hard_limit_sec, заметно больше timeout — с запасом на
    случай, если settimeout всё-таки отработал на КАЖДОМ этапе по
    отдельности, а не как единый бюджет на весь обмен). Если дедлайн
    настал, а поток так и не завершился — честно бросаем ошибку и
    отдаём управление обратно (остальные задачи /marketplace'ы/веб-сервер
    продолжают жить), а не виснем вместе с ним. Сам поток при этом может
    остаться висеть в фоне навсегда — это не идеально (второе ядро он не
    блокирует), но несравнимо лучше, чем заморозка всей платы.

    Единый таймаут для всех маркетплейсов — "зависания" именно на Yandex
    Market были багом в readline() (см. lib/sc_http, _LineBufferedSocket),
    а не реальной медлительностью их сервера, так что отдельный запас для
    него больше не нужен.
    """
    req_headers = dict(headers or {})
    if "User-Agent" not in req_headers:
        # Некоторые WAF/прокси относятся к запросам без User-Agent как к
        # подозрительным и гоняют их через более медленный пайплайн — curl
        # его шлёт автоматически, наш минимальный клиент не слал вообще
        # ничего. Дешёвая проверка на случай, если именно в этом разница
        # в скорости ответа у Yandex.
        req_headers["User-Agent"] = "SellerCounter-ESP32/1.0"

    if _thread is None:
        # Нет потоков (симулятор на хосте) — работаем как раньше, без
        # защиты от зависания settimeout.
        try:
            return _do_request(method, url, req_headers, json_body, timeout)
        except MarketplaceError:
            raise
        except Exception as exc:
            raise MarketplaceError("request to %s failed: %s" % (url, exc))

    result = [None]
    error = [None]
    done = [False]

    def _worker():
        try:
            result[0] = _do_request(method, url, req_headers, json_body, timeout)
        except Exception as exc:
            error[0] = exc
        finally:
            done[0] = True

    _thread.start_new_thread(_worker, ())

    hard_limit_sec = max(timeout * 4, 30)
    deadline = time.ticks_add(time.ticks_ms(), int(hard_limit_sec * 1000))
    while not done[0]:
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise MarketplaceError(
                "request to %s exceeded hard limit of %ds (settimeout may not "
                "have fired on one of the network steps)" % (url, hard_limit_sec)
            )
        time.sleep_ms(20)

    if error[0] is not None:
        exc = error[0]
        if isinstance(exc, MarketplaceError):
            raise exc
        raise MarketplaceError("request to %s failed: %s" % (url, exc))
    return result[0]
