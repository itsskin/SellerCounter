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
    fbs_line,
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
# Отдельный фон для экрана детализации по маркетплейсам. Нет файла —
# используется обычный BG_PATH.
BG_BREAKDOWN_PATH = ASSETS_DIR + "/bg_400x300_breakdown.bin"


def _load_background(fb, breakdown=False):
    fb.fill(0)
    data = None
    if breakdown:
        try:
            with open(BG_BREAKDOWN_PATH, "rb") as f:
                data = bytearray(f.read())
        except OSError:
            data = None
    if data is None:
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
                # Имя файла с "breakdown" — фон экрана детализации.
                target = BG_BREAKDOWN_PATH if "breakdown" in name.lower() else BG_PATH
                with open(target, "wb") as f:
                    f.write(buf)
                applied = True
                print("layout_400x300: %s стал новым фоном (%s)" % (name, target))
        except Exception as exc:
            print("layout_400x300: не смог обработать %s (%s)" % (name, exc))
        try:
            os.remove(src)
        except OSError:
            pass
    return applied


COLUMN_DOTS_PATH = "/display/column.png"
_column_dots = None


def _get_column_dots():
    """Точечный разделитель из display/column.png (1bpp, читается один раз).
    Нет файла или не разобрался — None, разделителей не будет."""
    global _column_dots
    if _column_dots is None:
        try:
            from display import png_to_bin

            _column_dots = png_to_bin.decode_to_1bpp(COLUMN_DOTS_PATH)
        except Exception as exc:
            print("layout_400x300: не смог прочитать %s (%s)" % (COLUMN_DOTS_PATH, exc))
            _column_dots = (0, 0, b"")
    return _column_dots if _column_dots[0] else None


def _draw_column_dividers(fb, cfg, centers):
    dots = _get_column_dots()
    if dots is None or len(centers) < 2:
        return
    w, h, buf = dots
    row_bytes = (w + 7) // 8
    y0 = LAYOUT.cfg_int(cfg, "mp_row.divider_y")
    for a, b in zip(centers, centers[1:]):
        x0 = (a + b) // 2 - w // 2
        for row in range(h):
            for col in range(w):
                if buf[row * row_bytes + col // 8] & (0x80 >> (col % 8)):
                    fb.pixel(x0 + col, y0 + row, 1)


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
    revenue_font, revenue_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.revenue_font"))
    revenue_decimal_font, revenue_decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.revenue_decimal_font"))
    orders_font, orders_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.orders_font"))
    orders_decimal_font, orders_decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, "mp_row.orders_decimal_font"))
    column_margin = LAYOUT.cfg_int(cfg, "mp_row.column_margin")
    area_x = LAYOUT.cfg_int(cfg, "mp_row.area_x")
    area_width = LAYOUT.cfg_int(cfg, "mp_row.area_width")
    edge_margin = LAYOUT.cfg_int(cfg, "mp_row.edge_margin")
    label_y = LAYOUT.cfg_int(cfg, "mp_row.label_y")
    revenue_y = LAYOUT.cfg_int(cfg, "mp_row.revenue_y")
    orders_y = LAYOUT.cfg_int(cfg, "mp_row.orders_y")

    n = len(columns)
    # ПОЗИЦИЯ и БЮДЖЕТ ШИРИНЫ столбика — ОДНА и та же формула (area_width
    # // n), не раздельные: пробовали раздельно (фиксированный шаг между
    # столбиками + растущий бюджет ширины) — при 1-2 столбиках текст
    # вырастал шире расстояния между столбиками и сливался с соседним.
    column_width = area_width // n
    group_x = area_x
    max_width = max(1, column_width - column_margin)

    def _draw_number(value, x, y, font, decimal_font, decimal_scale, scale, max_decimals, min_abbrev=0):
        text = custom_font.format_compact(
            font, value, max_width, scale,
            decimal_font=decimal_font, decimal_scale=decimal_scale, max_decimals=max_decimals,
            min_abbrev=min_abbrev,
        )
        big, tail = split_compact(text)
        trailing = [(tail, decimal_font, decimal_scale)] if tail else []
        custom_font.draw_text_with_trailing(
            fb, font, big, x, y, trailing, big_scale=scale, center_whole=True,
        )

    # Размеры шрифтов (mp_row.revenue_font/orders_font) — ручные: рисуем
    # ровно тем, что указано в layout.txt, без авто-подгонки под ширину.
    # Не влезло — обрежется/наложится, это уже забота автора layout.txt.
    # Сокращение "K"/"M" (format_compact) остаётся — это про формат числа.
    revenue_items = []
    for mp_id, entry in columns:
        text = custom_font.format_compact(
            revenue_font, entry.get("revenue", 0), max_width, revenue_scale,
            decimal_font=revenue_decimal_font, decimal_scale=revenue_decimal_scale,
            max_decimals=0, min_abbrev=1000,
        )
        big, tail = split_compact(text)
        revenue_items.append((mp_id, entry, big, tail))

    centers = []
    for i, (mp_id, entry, big, tail) in enumerate(revenue_items):
        col_x = group_x + column_width * i + column_width // 2
        # Отступ крайних столбиков от краёв: первый сдвигается вправо,
        # последний влево (у единственного столбика сдвига нет).
        if n > 1:
            if i == 0:
                col_x += edge_margin
            elif i == n - 1:
                col_x -= edge_margin
        centers.append(col_x)

        # FBS этой площадки — просто число под заказами, без подписи и
        # "шт" (подпись "FBS" уже есть на фоне). Шрифт — тот же, что у
        # напоминания "Собрать FBS" на Итогах (fbs_label.font.400x300), но
        # y СВОЙ (mp_row.fbs_y) — общий с Итогами y раньше сажал число
        # слишком высоко, вплотную к подписи "шт" у заказов (HW-
        # подтверждено), потому что раскладки этих двух экранов не совпадают.
        if data.get("show_fbs_label") and LAYOUT.cfg_bool(cfg, res_key("fbs_label", "show", RES)):
            fbs_font, fbs_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("fbs_label", "font", RES)))
            custom_font.draw_text_centered(
                fb, fbs_font, str(entry.get("fbs_orders", 0)), col_x,
                LAYOUT.cfg_int(cfg, "mp_row.fbs_y"), scale=fbs_scale,
            )

        label = entry.get("short_label") or (mp_id[:1].upper() + mp_id[1:2])
        custom_font.draw_text_centered(fb, label_font, label, col_x, label_y, scale=label_scale)

        trailing = [(tail, revenue_decimal_font, revenue_decimal_scale)] if tail else []
        custom_font.draw_text_with_trailing(
            fb, revenue_font, big, col_x, revenue_y, trailing,
            big_scale=revenue_scale, center_whole=True,
        )

        # Нижнее число — заказы этого маркетплейса.
        _draw_number(
            entry.get("orders", 0), col_x, orders_y,
            orders_font, orders_decimal_font, orders_decimal_scale, orders_scale,
            max_decimals=1, min_abbrev=10000,
        )

    _draw_column_dividers(fb, cfg, centers)


def _draw_revenue(fb, cfg, value, key):
    revenue_font, revenue_scale = resolve_font(LAYOUT.cfg_str(cfg, key("font")))
    decimal_font, decimal_scale = resolve_font(LAYOUT.cfg_str(cfg, key("decimal_font")))
    revenue_max_width = LAYOUT.cfg_int(cfg, key("max_width"))
    revenue_text = custom_font.format_compact(
        revenue_font,
        value,
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
            LAYOUT.cfg_str(cfg, key("font")), revenue_big, revenue_max_width,
            extra_width=tail_width,
        )
    revenue_x = LAYOUT.cfg_int(cfg, key("x"))
    revenue_y = LAYOUT.cfg_int(cfg, key("y"))
    custom_font.draw_text_with_trailing(
        fb, revenue_font, revenue_big, revenue_x, revenue_y, revenue_trailing, big_scale=revenue_scale,
        center_whole=True,
    )


def _draw_orders(fb, cfg, value, key):
    orders_font, orders_scale = resolve_font(LAYOUT.cfg_str(cfg, key("font")))
    orders_decimal_font, orders_decimal_scale = resolve_font(
        LAYOUT.cfg_str(cfg, key("decimal_font"))
    )
    suffix = LAYOUT.cfg_text(cfg, key("suffix"))
    suffix_font = suffix_scale = None
    orders_max_width = LAYOUT.cfg_int(cfg, key("max_width"))
    if suffix:
        suffix_font, suffix_scale = resolve_font(LAYOUT.cfg_str(cfg, key("suffix_font")))
        suffix_text = " " + suffix
        orders_max_width = max(
            1, orders_max_width - custom_font.text_width(suffix_font, suffix_text, suffix_scale)
        )

    orders_text = custom_font.format_compact(
        orders_font,
        value,
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
                LAYOUT.cfg_str(cfg, key("font")), orders_big, orders_max_width
            )
    if suffix:
        orders_trailing.append((" " + suffix, suffix_font, suffix_scale))

    orders_x = LAYOUT.cfg_int(cfg, key("x"))
    orders_y = LAYOUT.cfg_int(cfg, key("y"))
    custom_font.draw_text_with_trailing(
        fb, orders_font, orders_big, orders_x, orders_y, orders_trailing, big_scale=orders_scale,
    )


def update_numbers(fb, data):
    # Фон перезагружаем на каждой перерисовке (не только один раз при
    # старте) — та же причина, что у layout_200x200: текст не должен
    # оставлять "призраков" от старого значения.
    _load_background(fb, breakdown=bool(data.get("show_marketplace_breakdown")))
    cfg = LAYOUT.get()

    breakdown = bool(data.get("show_marketplace_breakdown"))
    if breakdown:
        _draw_marketplace_breakdown(fb, cfg, data)
        # Общие выручка/заказы на экране детализации — свои поля
        # (mp_total_revenue.*/mp_total_orders.*): фон другой, положение и
        # размеры не совпадают с обычным экраном.
        if LAYOUT.cfg_bool(cfg, "mp_total_revenue.show"):
            _draw_revenue(fb, cfg, data.get("revenue", 0), lambda f: "mp_total_revenue." + f)
        if LAYOUT.cfg_bool(cfg, "mp_total_orders.show"):
            _draw_orders(fb, cfg, data.get("orders", 0), lambda f: "mp_total_orders." + f)
    else:
        if LAYOUT.cfg_bool(cfg, res_key("revenue", "show", RES)):
            _draw_revenue(fb, cfg, data.get("revenue", 0), lambda f: res_key("revenue", f, RES))
        if LAYOUT.cfg_bool(cfg, res_key("orders", "show", RES)):
            _draw_orders(fb, cfg, data.get("orders", 0), lambda f: res_key("orders", f, RES))

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
    if not breakdown and data.get("show_fbs_label") and LAYOUT.cfg_bool(cfg, res_key("fbs_label", "show", RES)):
        fbs_text = LAYOUT.cfg_text(cfg, res_key("fbs_label", "text", RES))
        if fbs_text:
            fbs_font, fbs_scale = resolve_font(LAYOUT.cfg_str(cfg, res_key("fbs_label", "font", RES)))
            # Одна строка целиком: "FBS: Oz - 1 шт | Wb - 29 шт".
            full_text = fbs_line(fbs_text, data.get("fbs_by_marketplace"), data.get("fbs_pending_count", 0))
            fbs_font, fbs_scale = shrink_font_to_fit(
                LAYOUT.cfg_str(cfg, res_key("fbs_label", "font", RES)), full_text, 400 - 4
            )
            custom_font.draw_text_centered(
                fb, fbs_font, full_text,
                LAYOUT.cfg_int(cfg, res_key("fbs_label", "x", RES)),
                LAYOUT.cfg_int(cfg, res_key("fbs_label", "y", RES)),
                scale=fbs_scale,
            )


def render(fb, data):
    """Полная перерисовка (статика + динамика) — используется при первом
    выводе после включения/сна панели."""
    static_frame(fb)
    update_numbers(fb, data)
