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
#   # "детализация по маркетплейсам" (см. _draw_marketplace_breakdown) —
#   # заменяет обычные orders/revenue выше, когда включена:
#   "show_marketplace_breakdown": bool,
#   "per_marketplace": {mp_id: {"short_label": str, "orders": int, "revenue": float, ...}},
#   "marketplace_breakdown_visible": {mp_id: bool},
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


def _draw_marketplace_breakdown(fb, cfg, data):
    """"Детализация по маркетплейсам" — вместо одной общей суммы СТОЛБИК на
    каждый подключённый и видимый маркетплейс (короткая подпись + его
    выручка/заказы), рядом друг с другом. Внутри столбика — сверху вниз,
    как на общем экране: подпись, выручка, заказы. См. cfg["display"]
    ["show_marketplace_breakdown"]/["marketplace_breakdown_visible"] и
    комментарий у mp_row.* в layout_common.DEFAULTS."""
    visible = data.get("marketplace_breakdown_visible") or {}
    # per_marketplace — обычный dict, вставленный stats_engine.py в порядке
    # опроса (cfg["marketplaces"], по умолчанию Ozon/WB/Yandex). order —
    # cfg["display"]["marketplace_breakdown_order"], список id в желаемом
    # порядке столбиков (веб-интерфейс, раздел "Маркетплейсы", стрелки
    # вверх/вниз) — пусто или неполный список, значит для отсутствующих id
    # порядок как в per_marketplace (естественный).
    per_marketplace = data.get("per_marketplace") or {}
    order = data.get("marketplace_breakdown_order") or []
    # "not in ordered_ids" тут же и дедуплицирует — если order (например
    # из-за старого/битого cfg) содержит один id дважды, второе вхождение
    # просто не пройдёт эту проверку.
    ordered_ids = []
    for mp_id in order:
        if mp_id in per_marketplace and mp_id not in ordered_ids:
            ordered_ids.append(mp_id)
    ordered_ids += [mp_id for mp_id in per_marketplace if mp_id not in ordered_ids]
    columns = [
        (mp_id, per_marketplace[mp_id]) for mp_id in ordered_ids if visible.get(mp_id, True)
    ]
    if not columns:
        return

    label_font, label_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.label_font"))
    revenue_font_name = LAYOUT.cfg_str(cfg, "mp_row.revenue_font")
    revenue_font, revenue_scale = resolve_font(revenue_font_name)
    revenue_decimal_font, revenue_decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.revenue_decimal_font"))
    orders_font_name = LAYOUT.cfg_str(cfg, "mp_row.orders_font")
    orders_font, orders_scale = resolve_font(orders_font_name)
    orders_decimal_font, orders_decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.orders_decimal_font"))
    column_margin = LAYOUT.cfg_int(cfg, "mp_row.column_margin")
    column_width = LAYOUT.cfg_int(cfg, "mp_row.column_width")
    area_x = LAYOUT.cfg_int(cfg, "mp_row.area_x")
    area_width = LAYOUT.cfg_int(cfg, "mp_row.area_width")
    label_y = LAYOUT.cfg_int(cfg, "mp_row.label_y")
    revenue_y = LAYOUT.cfg_int(cfg, "mp_row.revenue_y")
    orders_y = LAYOUT.cfg_int(cfg, "mp_row.orders_y")

    n = len(columns)
    # column_width — ФИКСИРОВАННАЯ ширина под столбик, не area_width/n:
    # при area_width/n столбики растягивались на всю ширину области даже
    # когда их 1-2 (реже 3), разъезжаясь к противоположным краям экрана с
    # пустым разрывом посередине — визуально хуже, чем группа столбиков
    # постоянной ширины, отцентрированная в area_x..area_x+area_width с
    # запасом СНАРУЖИ группы, а не разрывом ВНУТРИ нее.
    group_width = column_width * n
    group_x = area_x + (area_width - group_width) // 2
    max_width = max(1, column_width - column_margin)

    def _draw_number(value, x, y, font, font_name, decimal_font, decimal_scale, scale, max_decimals, min_abbrev=0):
        text = custom_font.format_compact(
            font, value, max_width, scale,
            decimal_font=decimal_font, decimal_scale=decimal_scale, max_decimals=max_decimals,
            min_abbrev=min_abbrev,
        )
        big, tail = split_compact(text)
        trailing = [(tail, decimal_font, decimal_scale)] if tail else []
        tail_width = custom_font.text_width(decimal_font, tail, decimal_scale) if tail else 0
        if custom_font.text_width(font, big, scale) + tail_width > max_width:
            font, scale = shrink_font_to_fit(font_name, big, max_width, extra_width=tail_width)
        custom_font.draw_text_with_trailing(
            fb, font, big, x, y, trailing, big_scale=scale, center_whole=True,
        )

    for i, (mp_id, entry) in enumerate(columns):
        col_x = group_x + column_width * i + column_width // 2

        label = entry.get("short_label") or (mp_id[:1].upper() + mp_id[1:2])
        custom_font.draw_text_centered(fb, label_font, label, col_x, label_y, scale=label_scale)

        # Выручка — крупно, округление до целых K/M (max_decimals=0, "2K"
        # не "1.8K") — при таком большом шрифте в узком столбике decimal
        # часть почти никогда не влезла бы всё равно.
        # min_abbrev=1000 — иначе, например, 220 (меньше 0.5K) округлилась
        # бы до "0K" (max_decimals=0) при попытке K-сокращения — вместо
        # этого до 1000 показываем число как есть, шрифт сам ужмётся
        # (см. shrink_font_to_fit выше), если не влезает целиком.
        _draw_number(
            entry.get("revenue", 0), col_x, revenue_y,
            revenue_font, revenue_font_name, revenue_decimal_font, revenue_decimal_scale, revenue_scale,
            max_decimals=0, min_abbrev=1000,
        )
        # Нижнее число — обычно заказы ЭТОГО маркетплейса, но галочка в
        # веб-интерфейсе (раздел "Маркетплейсы") может заменить его на
        # ОБЩУЮ выручку по всем маркетплейсам сразу (одно и то же число
        # повторяется под каждым столбиком) — чтобы сразу видеть долю
        # каждого от общего рядом с его собственной выручкой сверху.
        if data.get("marketplace_breakdown_show_total_revenue"):
            _draw_number(
                data.get("revenue", 0), col_x, orders_y,
                orders_font, orders_font_name, orders_decimal_font, orders_decimal_scale, orders_scale,
                max_decimals=0, min_abbrev=1000,
            )
        else:
            _draw_number(
                entry.get("orders", 0), col_x, orders_y,
                orders_font, orders_font_name, orders_decimal_font, orders_decimal_scale, orders_scale,
                max_decimals=1, min_abbrev=10000,
            )


def update_numbers(fb, data):
    # Фон перезагружаем на каждой перерисовке (не только один раз при
    # старте) — та же причина, что у layout_200x200: текст не должен
    # оставлять "призраков" от старого значения.
    _load_background(fb)
    cfg = LAYOUT.get()

    if data.get("show_marketplace_breakdown"):
        _draw_marketplace_breakdown(fb, cfg, data)
    elif LAYOUT.cfg_bool(cfg, res_key("revenue", "show", RES)):
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

    if not data.get("show_marketplace_breakdown") and LAYOUT.cfg_bool(cfg, res_key("orders", "show", RES)):
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
