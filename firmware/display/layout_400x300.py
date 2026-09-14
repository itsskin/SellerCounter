# Точный пиксельный макет под экран 400x300 (WeAct 4.2").
#
# Как и 200x200 — весь интерфейс это фоновая картинка (assets/bg_400x300.bin,
# 1bpp), сконвертированная из .png прямо на плате (см. check_new_background()
# ниже, png_to_bin.py — размер PNG проверяется по WIDTH/HEIGHT этого модуля).
# Никакой рамки/заголовка/подписей код сам не рисует — это дело фоновой
# картинки. Поверх неё кастомным пиксельным шрифтом Orbitron/Verdana
# (display/fonts/, display/custom_font.py, подбор шрифта — см.
# display/layout_common.py) рисуются выручка и заказы (+ "шт" после
# заказов); IP — отдельно, встроенным ASCII-шрифтом framebuf (мельче и
# не нужен кастомный кириллический — IP только цифры и точки).
#
# Положение/шрифты/суффикс/видимость — в ОБЩЕМ (на оба экрана сразу)
# assets/layout.txt, см. display/layout_common.py (LAYOUT, res_key) —
# правится руками или через веб (/api/layout/text), подхватывается на
# следующей перерисовке без перезагрузки платы.
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
    res_key,
    resolve_font,
    shrink_font_to_fit,
    split_compact,
)

WIDTH = 400
HEIGHT = 300
RES = "400x300"

ASSETS_DIR = "/display/assets"
BG_PATH = ASSETS_DIR + "/bg_400x300.bin"


def _load_background(fb):
    fb.fill(0)
    try:
        with open(BG_PATH, "rb") as f:
            data = bytearray(f.read())
    except OSError as exc:
        print(
            "layout_400x300: не смог загрузить %s (%s) — заливал firmware/display/assets/? "
            "Рисую пустой экран." % (BG_PATH, exc)
        )
        return
    bg_fb = framebuf.FrameBuffer(data, WIDTH, HEIGHT, framebuf.MONO_HLSB)
    fb.blit(bg_fb, 0, 0)


def static_frame(fb):
    _load_background(fb)


def check_new_background():
    """Ищет .png в assets/, конвертирует первый подходящий (ровно 400x300)
    в bg_400x300.bin и удаляет исходник — тот же приём, что и в
    layout_200x200.check_new_background(), см. её докстринг. Вызывается
    из main.py при старте; веб-загрузка фона (web_server.py
    /api/background) тоже вызывает эту функцию, для текущего активного
    макета — если сейчас активен driver=epd4in2, сработает именно эта."""
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
                    "layout_400x300: %s это %dx%d, а нужно %dx%d — пропускаю"
                    % (name, w, h, WIDTH, HEIGHT)
                )
            else:
                with open(BG_PATH, "wb") as f:
                    f.write(buf)
                applied = True
                print("layout_400x300: %s стал новым фоном" % name)
        except Exception as exc:
            print("layout_400x300: не смог обработать %s (%s)" % (name, exc))
        try:
            os.remove(src)
        except OSError:
            pass
    return applied


def update_numbers(fb, data):
    # Фон перезагружаем на каждой перерисовке (не только один раз при
    # старте) — та же причина, что у layout_200x200: текст не должен
    # оставлять "призраков" от старого значения.
    _load_background(fb)
    cfg = LAYOUT.get()

    if LAYOUT.cfg_bool(cfg, res_key("revenue", "show", RES)):
        revenue_font, revenue_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("revenue", "font", RES)))
        decimal_font, decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("revenue", "decimal_font", RES)))
        revenue_max_width = LAYOUT.cfg_int(cfg, res_key("revenue", "max_width", RES))
        revenue_text = custom_font.format_compact(
            revenue_font,
            data.get("revenue", 0),
            revenue_max_width,
            revenue_scale,
            decimal_font=decimal_font,
            decimal_scale=decimal_scale,
            max_decimals=1,
        )
        revenue_big, revenue_tail = split_compact(revenue_text)
        revenue_trailing = [(revenue_tail, decimal_font, decimal_scale)] if revenue_tail else []
        tail_width = custom_font.text_width(decimal_font, revenue_tail, decimal_scale) if revenue_tail else 0
        if custom_font.text_width(revenue_font, revenue_big, revenue_scale) + tail_width > revenue_max_width:
            revenue_font, revenue_scale = shrink_font_to_fit(
                LAYOUT.cfg_str(cfg, res_key("revenue", "font", RES)), revenue_big, revenue_max_width,
                extra_width=tail_width,
            )
        revenue_x = LAYOUT.cfg_int(cfg, res_key("revenue", "x", RES))
        revenue_y = LAYOUT.cfg_int(cfg, res_key("revenue", "y", RES))
        custom_font.draw_text_with_trailing(
            fb, revenue_font, revenue_big, revenue_x, revenue_y, revenue_trailing, big_scale=revenue_scale,
            center_whole=True,
        )

    if LAYOUT.cfg_bool(cfg, res_key("orders", "show", RES)):
        orders_font, orders_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("orders", "font", RES)))
        orders_decimal_font, orders_decimal_scale = resolve_font(
            LAYOUT.cfg_str(cfg, res_key("orders", "decimal_font", RES))
        )
        suffix = LAYOUT.cfg_text(cfg, res_key("orders", "suffix", RES))
        suffix_font = suffix_scale = None
        orders_max_width = LAYOUT.cfg_int(cfg, res_key("orders", "max_width", RES))
        if suffix:
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
            min_abbrev=10000,  # до "9999" показываем полностью, как на 200x200
        )
        orders_big, orders_tail = split_compact(orders_text)
        orders_trailing = [(orders_tail, orders_decimal_font, orders_decimal_scale)] if orders_tail else []
        if not orders_tail:
            if custom_font.text_width(orders_font, orders_big, orders_scale) > orders_max_width:
                orders_font, orders_scale = shrink_font_to_fit(
                    LAYOUT.cfg_str(cfg, res_key("orders", "font", RES)), orders_big, orders_max_width
                )
        if suffix:
            orders_trailing.append((" " + suffix, suffix_font, suffix_scale))

        orders_x = LAYOUT.cfg_int(cfg, res_key("orders", "x", RES))
        orders_y = LAYOUT.cfg_int(cfg, res_key("orders", "y", RES))
        custom_font.draw_text_with_trailing(
            fb, orders_font, orders_big, orders_x, orders_y, orders_trailing, big_scale=orders_scale,
        )

    # Дата — как на 200x200, по умолчанию выключена тут (clock.show.400x300
    # = 0 в DEFAULTS, место по умолчанию занято IP ниже).
    clock_text = data.get("updated_date", "")
    if clock_text and LAYOUT.cfg_bool(cfg, res_key("clock", "show", RES)):
        clock_font, clock_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("clock", "font", RES)))
        custom_font.draw_text_centered(
            fb, clock_font, clock_text,
            LAYOUT.cfg_int(cfg, res_key("clock", "x", RES)), LAYOUT.cfg_int(cfg, res_key("clock", "y", RES)),
            scale=clock_scale,
        )

    ip = data.get("ip") or ""
    if ip and LAYOUT.cfg_bool(cfg, res_key("ip", "show", RES)):
        ip_font, ip_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("ip", "font", RES)))
        ip_x = LAYOUT.cfg_int(cfg, res_key("ip", "x", RES))
        ip_y = LAYOUT.cfg_int(cfg, res_key("ip", "y", RES))
        custom_font.draw_text_centered(fb, ip_font, ip, ip_x, ip_y, scale=ip_scale)

    # Напоминание "Собрать FBS" — см. cfg["display"]["show_fbs_reminder"].
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
    """Полная перерисовка (статика + динамика) — используется при первом
    выводе после включения/сна панели."""
    static_frame(fb)
    update_numbers(fb, data)
