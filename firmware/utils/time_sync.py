import time

try:
    import ntptime
except ImportError:
    ntptime = None


def sync_ntp(retries=3):
    """Синхронизирует системные часы ESP32 по NTP (нужно для границ дня и
    для TLS-хэндшейка, которому важно правильное время)."""
    if ntptime is None:
        return False
    for _ in range(retries):
        try:
            ntptime.settime()
            return True
        except Exception:
            time.sleep(1)
    return False


def today_local_bounds(timezone_offset_hours, day_offset=0):
    """Возвращает (start_iso, end_iso, date_str) для дня в локальной
    таймзоне, посчитанные из UTC-времени платы (после NTP-синхронизации).

    day_offset сдвигает день на N суток (0 — сегодня, -1 — вчера и т.д.) —
    используется только для временной отладки (cfg["debug_day_offset"]),
    когда за сегодня ещё нет продаж и хочется посмотреть на данные за
    прошлый день. В обычной эксплуатации day_offset всегда 0.
    """
    now = time.time() + int(timezone_offset_hours * 3600) + int(day_offset) * 86400
    y, m, d, hh, mm, ss, wd, yd = time.gmtime(now)
    start = "%04d-%02d-%02dT00:00:00" % (y, m, d)
    end = "%04d-%02d-%02dT23:59:59" % (y, m, d)
    date_str = "%04d-%02d-%02d" % (y, m, d)
    return start, end, date_str


def today_utc_bounds_z(timezone_offset_hours, day_offset=0):
    """Возвращает (since_iso, to_iso) — начало и конец "сегодня" в местном
    часовом поясе, но выраженные как настоящие UTC-моменты с суффиксом "Z"
    (RFC3339, например "2026-08-15T21:00:00Z") — такой формат ожидают
    некоторые методы Ozon Seller API (filter.since/filter.to в
    /v3/posting/fbs/list), в отличие от today_local_bounds(), которая
    возвращает "наивную" строку без часового пояса.
    """
    tz_offset_sec = int(timezone_offset_hours * 3600)
    day_offset_sec = int(day_offset) * 86400
    shifted_now = time.time() + tz_offset_sec + day_offset_sec
    local_midnight_shifted = (shifted_now // 86400) * 86400
    since_utc = local_midnight_shifted - tz_offset_sec
    to_utc = local_midnight_shifted + 86399 - tz_offset_sec
    return _iso_z(since_utc), _iso_z(to_utc)


def _iso_z(epoch_utc):
    y, m, d, hh, mm, ss, _, _ = time.gmtime(epoch_utc)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (y, m, d, hh, mm, ss)
