# Точный пиксельный макет под маленький экран 200x200 (1.54", Waveshare
# e-Paper B / SSD1681).
#
# Фон — картинка, запакованная в assets/bg_200x200.bin (1bpp MONO_HLSB).
# Менять её можно прямо на плате: положи .png (200x200) в display/assets/ —
# при следующей загрузке (см. check_new_background(), вызывается из
# main.py) он сам сконвертируется в bg_200x200.bin и удалится. Декодер —
# display/png_to_bin.py, пишет на PIL/freetype не завязан (их на
# MicroPython нет).
#
# Поверх фона кастомным пиксельным шрифтом Orbitron (display/fonts/, см.
# assets/generate_orbitron_font.py и display/custom_font.py) рисуются
# выручка и заказы. Где именно, каким шрифтом и показывать ли вообще —
# задаётся ОБЩИМ (на оба экрана сразу) текстовым файлом assets/layout.txt,
# см. display/layout_common.py (LAYOUT, res_key) — правится руками или
# через веб (/api/layout/text), подхватывается на следующей перерисовке
# без перезагрузки платы.
#
# data, ожидаемый на входе render()/update_numbers():
# {
#   "orders": int,
#   "revenue": float,
#   "ip": str,
# }

import framebuf

from display import custom_font
from display.layout_common import (
    LAYOUT,
    draw_scaled_text_centered,
    res_key,
    resolve_font,
    shrink_font_to_fit,
    split_compact,
)

WIDTH = 200
HEIGHT = 200
RES = "200x200"

ASSETS_DIR = "/display/assets"
BG_PATH = ASSETS_DIR + "/bg_200x200.bin"


def _load_background(fb):
    fb.fill(0)
    try:
        with open(BG_PATH, "rb") as f:
            data = bytearray(f.read())
    except OSError as exc:
        print(
            "layout_200x200: не смог загрузить %s (%s) — заливал firmware/display/assets/? "
            "Рисую пустой экран." % (BG_PATH, exc)
        )
        return
    # framebuf не даёт прямого доступа к своему буферу как атрибуту — грузим
    # фон как отдельный FrameBuffer той же геометрии и переносим через
    # штатный blit(), а не ручным копированием байт.
    bg_fb = framebuf.FrameBuffer(data, WIDTH, HEIGHT, framebuf.MONO_HLSB)
    fb.blit(bg_fb, 0, 0)


def static_frame(fb):
    _load_background(fb)


def check_new_background():
    """Ищет .png в assets/, конвертирует первый подходящий в bg_200x200.bin
    (см. png_to_bin.py) и удаляет исходник (успешно сконвертированный или
    нет — чтобы не пытаться конвертировать один и тот же битый файл на
    каждой загрузке). Вызывается один раз при старте из main.py."""
    import os

    try:
        names = sorted(n for n in os.listdir(ASSETS_DIR) if n.lower().endswith(".png"))
    except OSError:
        return False
    if not names:
        return False

    from display import png_to_bin

    applied = False
    for name in names:
        src = ASSETS_DIR + "/" + name
        try:
            w, h, buf = png_to_bin.decode_to_1bpp(src)
            if (w, h) != (WIDTH, HEIGHT):
                print(
                    "layout_200x200: %s это %dx%d, а нужно %dx%d — пропускаю"
                    % (name, w, h, WIDTH, HEIGHT)
                )
            else:
                with open(BG_PATH, "wb") as f:
                    f.write(buf)
                applied = True
                print("layout_200x200: %s стал новым фоном" % name)
        except Exception as exc:
            print("layout_200x200: не смог обработать %s (%s)" % (name, exc))
        try:
            os.remove(src)
        except OSError:
            pass
    return applied


def update_numbers(fb, data):
    # Перезагружаем фон на каждой перерисовке (не только один раз при
    # старте) — так текст никогда не оставляет "призраков" от старого
    # значения, независимо от формы конкретной картинки-фона, и не нужно
    # держать в коде отдельные прямоугольники под затирание для каждого
    # макета фона.
    _load_background(fb)
    cfg = LAYOUT.get()

    if LAYOUT.cfg_bool(cfg, res_key("revenue", "show", RES)):
        revenue_font, revenue_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("revenue", "font", RES)))
        # decimal_font резолвим ДО format_compact и передаём туда же — иначе
        # проверка "влезает ли по ширине" считала бы дробную часть тем же
        # крупным шрифтом, что и целую, и решила бы, что "13.5K" не влезает
        # (хотя реально рисуется мельче и прекрасно влезает) — откатывалась бы
        # на "14K" без точки раньше, чем нужно на самом деле.
        decimal_font, decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("revenue", "decimal_font", RES)))
        revenue_max_width = LAYOUT.cfg_int(cfg, res_key("revenue", "max_width", RES))
        revenue_text = custom_font.format_compact(
            revenue_font,
            data.get("revenue", 0),
            revenue_max_width,
            revenue_scale,
            decimal_font=decimal_font,
            decimal_scale=decimal_scale,
            max_decimals=1,  # "13.5K" с точкой, если влезает; иначе сама откатится на "654K" без точки
        )
        revenue_x = LAYOUT.cfg_int(cfg, res_key("revenue", "x", RES))
        revenue_y = LAYOUT.cfg_int(cfg, res_key("revenue", "y", RES))
        # "12.3K"/"1.2M" — часть от точки мельче основной цифры, для
        # визуального разделения (как копейки на ценнике). Отдельный, обычно
        # более мелкий шрифт того же семейства, не масштаб того же файла —
        # scale целочисленный, "чуть мельче" им не выразить. У выручки нет
        # суффикса-подписи (в отличие от заказов) — центрируем ВЕСЬ текст
        # целиком (center_whole=True), иначе число визуально "уезжает" от
        # центра экрана — там просто нечему уравновешивать хвост справа.
        revenue_big, revenue_tail = split_compact(revenue_text)
        revenue_trailing = [(revenue_tail, decimal_font, decimal_scale)] if revenue_tail else []
        # format_compact гарантирует влезание, только измеряя дробную часть
        # мелким decimal_font — а вот саму букву "K"/"M" без точки (decimals=0,
        # последний отступной вариант) она меряет ещё крупным основным
        # шрифтом, хотя рисуется та буква уже мелким. Поэтому даже "финальный"
        # candidate иногда реально не влезает (крупная часть + мелкий хвост) —
        # тогда, как и у заказов, ужимаем сам крупный шрифт кегль за кеглем.
        tail_width = custom_font.text_width(decimal_font, revenue_tail, decimal_scale) if revenue_tail else 0
        if custom_font.text_width(revenue_font, revenue_big, revenue_scale) + tail_width > revenue_max_width:
            revenue_font, revenue_scale = shrink_font_to_fit(
                LAYOUT.cfg_str(cfg, res_key("revenue", "font", RES)), revenue_big, revenue_max_width,
                extra_width=tail_width,
            )
        custom_font.draw_text_with_trailing(
            fb, revenue_font, revenue_big, revenue_x, revenue_y, revenue_trailing, big_scale=revenue_scale,
            center_whole=True,
        )

    if LAYOUT.cfg_bool(cfg, res_key("orders", "show", RES)):
        orders_font, orders_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("orders", "font", RES)))
        orders_decimal_font, orders_decimal_scale = resolve_font(
            LAYOUT.cfg_str(cfg, res_key("orders", "decimal_font", RES))
        )

        # Суффикс резолвим и меряем ДО format_compact и вычитаем его ширину из
        # бюджета — иначе на очень больших количествах заказов (в жизни
        # маловероятно, но мало ли) "шт" рисовалась бы за пределами экрана:
        # format_compact без этого гарантирует, что влезет только само число,
        # без места под то, что дорисуется следом.
        suffix = LAYOUT.cfg_text(cfg, res_key("orders", "suffix", RES))
        suffix_font = suffix_scale = None
        orders_max_width = LAYOUT.cfg_int(cfg, res_key("orders", "max_width", RES))
        if suffix:
            # У Orbitron нет кириллицы вообще, поэтому suffix_font обязательно
            # verdana_*, а не orbitron_* (см. DEFAULTS/шаблон).
            suffix_font, suffix_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("orders", "suffix_font", RES)))
            suffix_text = " " + suffix
            orders_max_width = max(
                1, orders_max_width - custom_font.text_width(suffix_font, suffix_text, suffix_scale)
            )

        orders_text = custom_font.format_compact(
            orders_font,
            data.get("orders", 0),
            orders_max_width,
            orders_scale,
            decimal_font=orders_decimal_font,
            decimal_scale=orders_decimal_scale,
            max_decimals=1,
            min_abbrev=10000,  # до "9999" показываем полностью, "10000"+ — можно сократить, если не влезает
        )
        orders_x = LAYOUT.cfg_int(cfg, res_key("orders", "x", RES))
        orders_y = LAYOUT.cfg_int(cfg, res_key("orders", "y", RES))

        # Само число (без хвостов) центрируется по orders.x/y — ни дробная
        # часть ("1.5K"), ни подпись ("шт") в расчёт центра не идут, иначе
        # число будет "гулять" от центра в зависимости от того, что к нему
        # дописано.
        orders_big, orders_tail = split_compact(orders_text)
        orders_trailing = [(orders_tail, orders_decimal_font, orders_decimal_scale)] if orders_tail else []
        if not orders_tail:
            # min_abbrev держит число полным даже если оно не влезает по ширине
            # (классика — "999" ещё влезает, "1000"+ уже нет) — раз сократить в
            # "1K" нельзя, ужимаем сам шрифт, кегль за кеглем, пока не влезет.
            if custom_font.text_width(orders_font, orders_big, orders_scale) > orders_max_width:
                orders_font, orders_scale = shrink_font_to_fit(
                    LAYOUT.cfg_str(cfg, res_key("orders", "font", RES)), orders_big, orders_max_width
                )

        if suffix:
            orders_trailing.append((" " + suffix, suffix_font, suffix_scale))

        custom_font.draw_text_with_trailing(
            fb, orders_font, orders_big, orders_x, orders_y, orders_trailing, big_scale=orders_scale
        )

    # Дата ("05-12-2026") — готовая строка из stats_engine (updated_date),
    # тут не форматируется и не сокращается через format_compact (это не
    # число, а фиксированный по длине текст).
    clock_text = data.get("updated_date", "")
    if clock_text and LAYOUT.cfg_bool(cfg, res_key("clock", "show", RES)):
        clock_font, clock_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("clock", "font", RES)))
        custom_font.draw_text_centered(
            fb, clock_font, clock_text,
            LAYOUT.cfg_int(cfg, res_key("clock", "x", RES)), LAYOUT.cfg_int(cfg, res_key("clock", "y", RES)),
            scale=clock_scale,
        )

    # IP — встроенным ASCII-шрифтом framebuf (не Orbitron/Verdana), как на
    # 400x300. На маленьком экране по умолчанию выключен (ip.show.200x200 =
    # 0 в DEFAULTS) — включается через layout.txt/веб при желании.
    ip = data.get("ip") or ""
    if ip and LAYOUT.cfg_bool(cfg, res_key("ip", "show", RES)):
        ip_scale = LAYOUT.cfg_int(cfg, res_key("ip", "scale", RES))
        ip_x = LAYOUT.cfg_int(cfg, res_key("ip", "x", RES))
        ip_y = LAYOUT.cfg_int(cfg, res_key("ip", "y", RES))
        draw_scaled_text_centered(fb, ip, ip_x, ip_y, scale=ip_scale)

    # Напоминание "Собрать FBS" — см. cfg["display"]["show_fbs_reminder"].
    # data["show_fbs_label"] уже учитывает и чекбокс в веб-интерфейсе, и
    # реальное наличие несобранного заказа (см. stats_engine.py); show.*
    # тут — дополнительный, самый жёсткий выключатель именно для этого
    # экрана.
    if data.get("show_fbs_label") and LAYOUT.cfg_bool(cfg, res_key("fbs_label", "show", RES)):
        fbs_text = LAYOUT.cfg_text(cfg, res_key("fbs_label", "text", RES))
        if fbs_text:
            fbs_font, fbs_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("fbs_label", "font", RES)))
            custom_font.draw_text_centered(
                fb, fbs_font, fbs_text,
                LAYOUT.cfg_int(cfg, res_key("fbs_label", "x", RES)),
                LAYOUT.cfg_int(cfg, res_key("fbs_label", "y", RES)),
                scale=fbs_scale,
            )


def render(fb, data):
    update_numbers(fb, data)
