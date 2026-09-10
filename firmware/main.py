try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import machine

import breadcrumb
import config as config_module
import wifi_manager
from buzzer import Buzzer
from display import layout
from utils.time_sync import sync_ntp
from web_server import run_server

# Печатаем СРАЗУ при импорте, до всего остального — если прошлая загрузка
# закончилась зависанием + сбросом по watchdog (см. WDT ниже), это первое,
# что должно попасть в лог, до того как что-либо новое перезапишет
# last_activity.txt. None — самая первая загрузка вообще (файла ещё нет)
# или чистое штатное выключение/сброс не через зависание.
_last_activity_before_boot = breadcrumb.read_last()
if _last_activity_before_boot:
    print("main: последняя активность до этой загрузки: %s" % _last_activity_before_boot)


def _get_display(cfg):
    driver_name = cfg["display"].get("driver", "sim")
    if driver_name == "epd4in2":
        from display.epd4in2 import Epd4in2Display
        return Epd4in2Display()
    if driver_name == "epd1in54":
        from display.epd1in54 import Epd1in54Display
        return Epd1in54Display()
    # "sim" — превью в браузере без физического экрана; какой размер
    # симулировать, берём из cfg["display"]["screen"] (независимо от
    # driver, чтобы можно было проверить оба макета без железа).
    from display.framebuf_sim import SimDisplay
    screen = cfg["display"].get("screen", "400x300")
    if screen == "200x200":
        return SimDisplay(width=200, height=200)
    return SimDisplay(width=400, height=300)


# 3 минуты — компромисс между двумя разными сценариями:
# 1) Заливка кода по USB (tools/mpy-raw-serial) — raw-REPL сессии полностью
#    останавливают event loop (а значит и кормёжку) на всё время, пока плата
#    в raw REPL. После урезания набора шрифтов (~600КБ вместо ~2.3МБ, см.
#    generate_verdana_font.py/generate_orbitron_font.py) заливка одного
#    файла укладывается в секунды — тут хватило бы и 1 минуты.
# 2) Обычный опрос маркетплейсов (stats_engine.poll_once) — HW-подтверждено:
#    на 1-минутном таймауте плата реально роняла себя по watchdog ПРИ ЭТОМ,
#    без всякой заливки по USB — каждый HTTP-запрос синхронный с таймаутом
#    до 15с (utils/http.py), а за один цикл их несколько (Ozon FBS+FBO, WB,
#    Yandex, у каждой площадки может быть больше одного магазина) — если
#    несколько подряд подвисают близко к таймауту (например когда сам
#    маркетплейс отвечает медленно/деградировал), суммарное время
#    блокировки event loop реально может приблизиться к 60с почти без
#    запаса. 3 минуты дают комфортный запас на этот случай, оставаясь
#    заметно короче прежних 10 минут.
WDT_TIMEOUT_MS = 3 * 60_000
WDT_FEED_INTERVAL_MS = 5_000


async def _feed_watchdog(wdt):
    """Аппаратный watchdog (machine.WDT) — если событийный цикл когда-либо
    намертво зависнет (по ЛЮБОЙ причине — необработанное исключение,
    зависший сокет без таймаута, баг в новом коде и т.п.), эта корутина
    просто перестанет получать своё время в cooperative-шедулере вместе со
    всеми остальными задачами, кормёжка прекратится, и через WDT_TIMEOUT_MS
    плата перезагрузится сама — без необходимости физически переткнуть
    кабель (см. запрос пользователя "почему надо постоянно передёргивать").
    watchdog не отключаем даже если что-то из остального не запустилось —
    так безопаснее, чем тихо повиснуть навсегда."""
    while True:
        wdt.feed()
        await asyncio.sleep_ms(WDT_FEED_INTERVAL_MS)


async def _safe_render(display, data):
    """Рендерит и показывает экран, но не роняет всю плату, если с
    экраном что-то не так (HW busy timeout и т.п.) — WiFi/веб-сервер/опрос
    маркетплейсов должны работать независимо от того, жив ли экран."""
    try:
        layout.get_layout(display.width, display.height).render(display.fb, data)
        await display.show()
    except Exception as exc:
        print("main: display error (продолжаем без экрана):", exc)


async def _run_provisioning_async(cfg, display, buzzer, wdt):
    # gather, а не последовательно — render (у e-paper ~20с) не должен
    # блокировать доступность страницы провижининга, см. пояснение в
    # display/epd1in54.py._wait_busy и main()._run_normal ниже.
    await asyncio.gather(
        _safe_render(display, {"orders": 0, "revenue": 0, "ip": wifi_manager.AP_IP}),
        run_server(cfg, mode="provisioning", display=display, buzzer=buzzer),
        _feed_watchdog(wdt),
    )


def _run_provisioning(cfg, display, buzzer, wdt):
    """Ждём пока пользователь введёт домашний Wi-Fi через веб-форму. Точка
    доступа к этому моменту уже поднята в main(). Обработчик /api/wifi
    сохраняет конфиг и перезагружает плату — оттуда управление уже пойдёт
    в обычный (STA) режим."""
    asyncio.run(_run_provisioning_async(cfg, display, buzzer, wdt))


async def _run_normal(cfg, engine, display, buzzer, wdt):
    await asyncio.gather(
        run_server(cfg, mode="normal", engine=engine, display=display, buzzer=buzzer),
        engine.run(),
        _feed_watchdog(wdt),
    )


def main():
    cfg = config_module.load()

    # Точка доступа остаётся включённой всегда, даже после успешного
    # подключения к домашнему Wi-Fi (ESP32 поддерживает AP+STA одновременно).
    # Это позволяет в любой момент подключиться к SellerCounter-Setup и
    # зайти на http://192.168.4.1/, чтобы посмотреть, какой IP плата
    # получила от роутера, без доступа к самому роутеру.
    wifi_manager.start_ap(cfg["ap"]["ssid"], cfg["ap"]["password"])
    print(
        "AP always-on: connect to '%s', open http://%s/"
        % (cfg["ap"]["ssid"], wifi_manager.AP_IP)
    )

    display = _get_display(cfg)

    # Если в display/assets/ на плате появился новый .png — конвертируем
    # его в фон экрана и удаляем (см. check_new_background() у обоих
    # макетов, layout_200x200.py и layout_400x300.py) — getattr на случай,
    # если когда-нибудь появится макет вообще без фона-картинки.
    layout_mod = layout.get_layout(display.width, display.height)
    check_bg = getattr(layout_mod, "check_new_background", None)
    if check_bg is not None:
        try:
            check_bg()
        except Exception as exc:
            print("main: не смог обработать новый фон (продолжаем со старым):", exc)

    # Зуммер создаём сразу (даже до Wi-Fi) — так кнопка "Тест" в
    # веб-интерфейсе работает и во время провижининга через точку доступа.
    buzzer = Buzzer(
        cfg["buzzer"]["pin"],
        cfg["buzzer"].get("enabled", True),
        cfg["buzzer"].get("volume", 100),
        cfg["buzzer"].get("volume_curve", "linear"),
    )

    # Аппаратный watchdog — см. _feed_watchdog() выше про то, зачем он
    # вообще нужен. Создаём один раз здесь (общий и для провижининга, и для
    # обычного режима) — после создания WDT выключить нельзя (так и
    # задумано у ESP32/MicroPython), это осознанный выбор "лучше лишний
    # автоматический ребут, чем зависшая насмерть плата".
    wdt = machine.WDT(timeout=WDT_TIMEOUT_MS)

    if not config_module.has_wifi_credentials(cfg):
        _run_provisioning(cfg, display, buzzer, wdt)
        return

    breadcrumb.mark("connecting wifi (boot)")
    sta = wifi_manager.connect_sta(cfg["wifi"]["ssid"], cfg["wifi"]["password"])
    if sta is None:
        print("Could not connect to saved Wi-Fi, staying in AP-only mode")
        _run_provisioning(cfg, display, buzzer, wdt)
        return

    print("Wi-Fi connected: IP from router =", wifi_manager.get_sta_ip())

    breadcrumb.mark("syncing ntp (boot)")
    sync_ntp()

    # Признак жизни сразу после подключения — короткий писк, до полного
    # startup_chime() ниже (тот подтверждает "всё готово", этот — просто
    # что плата включилась и дошла досюда). Отдельный переключатель
    # (buzzer.boot_sound) от общего "выключить звук" — можно приглушить
    # именно звук загрузки/перезагрузки, не трогая продажи и тест.
    if cfg["buzzer"].get("boot_sound", True):
        buzzer.beep(1000, 100)
        buzzer.startup_chime()

    from stats_engine import StatsEngine

    engine = StatsEngine(cfg, display, buzzer, wifi_manager.get_ip)

    # Отдельного "первого опроса перед стартом сервера" тут больше нет.
    # engine.run() (см. ниже, внутри _run_normal) сам опрашивает
    # маркетплейсы на первой же итерации без всякого force=True — это
    # обычный poll_once(), но т.к. self._last_poll_ticks ещё None, троттлинг
    # ("не чаще раза в poll_interval_sec") на самый первый вызов не
    # действует, он всё равно происходит сразу.
    #
    # Раньше эта строка запускалась в ОТДЕЛЬНОМ asyncio.run() ДО старта
    # веб-сервера — специально, чтобы не было двух подряд полных обновлений
    # экрана ("0", а через секунды поверх него реальные цифры). Это по
    # прежнему так (веб-сервер видит уже настоящие данные с самого начала).
    # Но раз e-paper показывает данные только когда они реально изменились
    # (self._displayed), и раз это единственное полное обновление всё равно
    # происходит ДО того, как что-либо ещё запущено — веб-сервер был
    # недоступен все ~20-30с, пока шло это самое первое обновление экрана
    # (HW-подтверждено: "маректы опрошены, а web не отвечает"). Раз
    # display.show() теперь async и отдаёт управление event loop во время
    # busy-wait (см. epd1in54.py), достаточно, чтобы первый опрос+рендер
    # шёл в ТОМ ЖЕ event loop, что и веб-сервер (через gather в
    # _run_normal), а не в отдельном asyncio.run() до него — тогда сервер
    # отвечает параллельно, а не после.
    breadcrumb.mark("starting main loop (web+poll+watchdog)")
    asyncio.run(_run_normal(cfg, engine, display, buzzer, wdt))


try:
    main()
except OSError as exc:
    if exc.args and exc.args[0] == 112:  # EADDRINUSE
        print(
            "\n[main] Порт 80 уже занят предыдущим запуском (характерно для "
            "повторного 'import main' в той же сессии Thonny без полного "
            "сброса — soft reset не всегда освобождает сокет). Сделай "
            "настоящий сброс: физически отключи-подключи USB или выполни "
            "machine.reset(), затем запусти import main заново.\n"
        )
    else:
        raise
