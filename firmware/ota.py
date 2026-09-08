# OTA-обновление прошивки — скачивает файлы с GitHub (raw.githubusercontent.com
# и jsDelivr как независимое зеркало того же репозитория), сверяет по sha256
# и заменяет локальные файлы. Ручное — по кнопке в веб-интерфейсе, не в фоне
# само по себе (сломанный релиз на удалённой плате без присмотра — так себе
# идея, особенно на раннем этапе проекта).
#
# Источники нарочно два и независимых друг от друга: raw.githubusercontent.com
# и cdn.jsdelivr.net иногда блокируются российскими провайдерами по отдельности
# (то один, то другой, то оба сразу, ситуация меняется) — если первый не
# ответил, пробуем следующий, а не считаем обновление недоступным сразу.
#
# ota_manifest.json (см. tools/gen_ota_manifest.py) содержит {"version": int,
# "files": {"relative/path.py": "sha256hex", ...}} — генерируется на
# компьютере из содержимого firmware/, коммитится вместе с изменениями кода.
# Версия, которая реально СТОИТ на плате, хранится отдельно в
# /ota_version.txt — не в самом коде (иначе обновлять версию было бы негде
# взять ДО того, как код обновился).
#
# Что НЕ обновляется через OTA (см. gen_ota_manifest.py EXCLUDE_PREFIXES) —
# display/assets/ (свой фон, свои координаты текста — данные пользователя) и
# notifications/ (свои мелодии).

import os
import binascii

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import sc_http as requests

OTA_SOURCES = (
    "https://raw.githubusercontent.com/itsskin/SellerCounter/main/firmware/",
    "https://cdn.jsdelivr.net/gh/itsskin/SellerCounter@main/firmware/",
)

VERSION_PATH = "/ota_version.txt"
# Таймаут одного источника — сумма (все источники таймаутят) не должна
# приближаться к WDT_TIMEOUT_MS (30с, см. main.py): пока идёт синхронный
# HTTP-запрос, event loop полностью стоит, кормление watchdog не может
# случиться. 10с * 2 источника = 20с худший случай, с запасом от 30с.
MANIFEST_TIMEOUT_SEC = 10
FILE_TIMEOUT_SEC = 20


class OtaError(Exception):
    pass


def current_version():
    try:
        with open(VERSION_PATH) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        # Ни разу не обновлялись через OTA — версия "0", любой манифест с
        # version >= 1 будет считаться обновлением.
        return 0


def _set_current_version(v):
    with open(VERSION_PATH, "w") as f:
        f.write(str(v))


def _headers():
    return {"User-Agent": "SellerCounter-ESP32/1.0"}


def _get(url, timeout):
    response = requests.request("GET", url, headers=_headers(), timeout=timeout)
    try:
        if response.status_code != 200:
            raise OtaError("HTTP %d от %s" % (response.status_code, url))
        return response.content
    finally:
        response.close()


async def check():
    """Пробует источники по очереди; у ПЕРВОГО, кто ответил, доверяем его
    версии (оба источника — зеркала одного и того же репозитория, дальше
    ходить не за чем — переключаемся на следующий источник ТОЛЬКО если этот
    вообще не ответил, не если ответил "обновлений нет").

    async и с await между попытками (не внутри самого блокирующего HTTP-
    запроса — sc_http синхронный) — чтобы между двумя таймаутами подряд
    (10с * 2 источника, см. MANIFEST_TIMEOUT_SEC) event loop успел отдать
    время кормлению watchdog, а не стоял все 20с одним куском.

    Возвращает {"current_version", "available_version", "update_available",
    "manifest", "source"}. Бросает OtaError, если ни один источник не
    ответил вообще."""
    import ujson as json

    cur = current_version()
    errors = []
    for base in OTA_SOURCES:
        try:
            raw = _get(base + "ota_manifest.json", MANIFEST_TIMEOUT_SEC)
            manifest = json.loads(raw)
        except Exception as exc:
            print("ota: источник недоступен (%s): %s" % (base, exc))
            errors.append("%s: %s" % (base, exc))
            await asyncio.sleep_ms(0)
            continue
        available = manifest.get("version", 0)
        return {
            "current_version": cur,
            "available_version": available,
            "update_available": available > cur,
            "manifest": manifest,
            "source": base,
        }
    raise OtaError("ни один источник не ответил: " + "; ".join(errors))


def _local_hash(path):
    """sha256 уже лежащего на плате файла, или None если файла нет.
    Нужно, чтобы не перекачивать по сети файлы, которые и так уже
    актуальны (HW-подтверждено: полный набор из ~70 файлов, включая
    крупные шрифты, качается по TLS с GitHub несколько минут в основном
    из-за накладных расходов TLS-хендшейка на КАЖДЫЙ файл — большинство
    обновлений на практике меняют единицы файлов, а не все разом)."""
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            while True:
                chunk = f.read(512)
                if not chunk:
                    break
                h.update(chunk)
            return binascii.hexlify(h.digest()).decode()
    except OSError:
        return None


def _ensure_dirs(path):
    parts = path.strip("/").split("/")[:-1]
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            os.mkdir(cur)
        except OSError:
            pass  # уже существует


async def apply(manifest, base_url, progress=None):
    """Скачивает и проверяет ВСЕ файлы манифеста во временные копии
    (*.ota_new) ПЕРЕД тем, как тронуть хоть один настоящий файл — если
    скачивание/проверка чего-то одного из 70+ файлов сорвётся на середине
    (сеть моргнула, источник отдал не то), плата остаётся на старой,
    рабочей версии целиком, а не в смеси старого и нового.

    Файлы, чей локальный sha256 уже совпадает с манифестом, вообще не
    скачиваются — см. _local_hash.

    await asyncio.sleep_ms(0) после каждого файла — отдаём управление event
    loop, чтобы кормление аппаратного watchdog (main.py._feed_watchdog) и
    веб-сервер не простаивали 70+ синхронных HTTP-запросов подряд (HW-
    подтверждено на другом сценарии в этом проекте: длинная синхронная
    работа без await реально роняет плату по watchdog).

    Голый except (не except Exception) — HW-подтверждено: KeyboardInterrupt
    (например Ctrl-C от raw-REPL сессии диагностики) НЕ ловится
    except Exception в этой прошивке, и без голого except недокачанные
    .ota_new оставались бы мусором на флеше навсегда."""
    files = manifest["files"]
    total = len(files)
    downloaded = []
    try:
        for i, rel_path in enumerate(sorted(files.keys())):
            expected_hash = files[rel_path]
            if progress:
                progress(i, total, rel_path)
            dest = "/" + rel_path
            if _local_hash(dest) == expected_hash:
                await asyncio.sleep_ms(0)
                continue
            data = _get(base_url + rel_path, FILE_TIMEOUT_SEC)
            actual_hash = binascii.hexlify(hashlib.sha256(data).digest()).decode()
            if actual_hash != expected_hash:
                raise OtaError(
                    "%s: хэш не совпал (ожидали %s, получили %s)"
                    % (rel_path, expected_hash, actual_hash)
                )
            _ensure_dirs(dest)
            tmp = dest + ".ota_new"
            with open(tmp, "wb") as f:
                f.write(data)
            downloaded.append((tmp, dest))
            await asyncio.sleep_ms(0)
    except:
        # Подчищаем недокачанные .ota_new — настоящие файлы ещё не тронуты,
        # плата остаётся в рабочем состоянии на старой версии. Голый except
        # (см. докстринг) — ловит и KeyboardInterrupt тоже.
        for tmp, _dest in downloaded:
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise

    if progress:
        progress(total, total, "применяю...")
    # Все файлы скачаны и проверены — переименование локальное, без сети,
    # быстрое и не может сорваться на середине от плохого интернета.
    for tmp, dest in downloaded:
        os.rename(tmp, dest)

    _set_current_version(manifest["version"])
