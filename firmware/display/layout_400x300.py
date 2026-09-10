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
# Положение/шрифты/суффикс — в assets/layout.txt (создаётся с дефолтами
# при первом запуске), тот же формат и механика, что у 200x200 (см.
# display/layout_common.LayoutTxtConfig) — отдельный файл в той же папке
# assets/, оба макета делят ASSETS_DIR, но не сам layout.txt (у каждого
# макета свой набор полей под свою геометрию).
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
    LayoutTxtConfig,
    draw_scaled_text_centered,
    resolve_font,
    shrink_font_to_fit,
    split_compact,
)

WIDTH = 400
HEIGHT = 300
CENTER_X = WIDTH // 2

ASSETS_DIR = "/display/assets"
BG_PATH = ASSETS_DIR + "/bg_400x300.bin"
LAYOUT_TXT_PATH = ASSETS_DIR + "/layout_400x300.txt"

# Дефолты подобраны под свободное место без рамки/заголовка (см. коммент в
# шапке файла): выручка сверху и крупнее, заказы снизу и чуть мельче — по
# запросу пользователя ("деньги побольше, штуки поменьше"). max_width — с
# запасом от полных 400px, чтобы точно не вылезти за край даже с
# сокращением "K"/"M"/дробным хвостом.
DEFAULTS = {
    "revenue.x": "200",
    "revenue.y": "95",
    "revenue.font": "orbitron_128",
    "revenue.max_width": "360",
    "revenue.decimal_font": "orbitron_70",
    "orders.x": "200",
    "orders.y": "205",
    "orders.font": "orbitron_96",
    "orders.max_width": "320",
    "orders.decimal_font": "orbitron_52",
    "orders.suffix": "шт",
    "orders.suffix_font": "verdana_28",
    # IP рисуется встроенным ASCII-шрифтом framebuf (не кастомным
    # Orbitron/Verdana) — поэтому вместо "font" тут "scale" (целочисленный
    # множитель, как в draw_scaled_text): 1 — самый мелкий вариант, ровно
    # то же, что framebuf.text() рисует нативно.
    "ip.x": "200",
    "ip.y": "282",
    "ip.scale": "1",
    # Напоминание "Собрать FBS" (см. cfg["display"]["show_fbs_reminder"] в
    # web_server.py/www) — рисуется, только когда чекбокс в веб-интерфейсе
    # включён. Текст настраивается через fbs_label.text (можно вписать
    # что угодно — Verdana теперь умеет полный алфавит кириллицы и
    # латиницы, не только "шт"). Orbitron кириллицу не умеет — font
    # обязательно verdana_*.
    "fbs_label.x": "200",
    "fbs_label.y": "260",
    "fbs_label.font": "verdana_28",
    "fbs_label.text": "Собрать FBS",
}

LAYOUT_TXT_TEMPLATE = """\
# Расположение текста на экране 400x300 (SellerCounter, WeAct 4.2").
# Правь числа и сохраняй — подхватится на следующей перерисовке экрана,
# перезапускать плату не нужно. Опечатка в поле не ломает экран — просто
# для этого поля вернётся значение по умолчанию.
#
# x / y — центр текста в пикселях (0,0 — левый верхний угол экрана).
# font — <семейство>_<размер> из display/fonts/, без ".py" (сейчас есть
#   orbitron_* и verdana_*; полный список размеров и их реальной высоты в
#   пикселях — см. display/fonts/available_sizes.txt). Если написать
#   размер, которого нет у этого семейства — возьмётся ближайший меньший
#   ИЗ ТОГО ЖЕ семейства и увеличится до нужного (апскейл, выйдет чуть
#   "кубиками", но разборчиво).
# max_width — если число по ширине не влезает в столько пикселей, оно
#   сокращается ("12345" -> "12.3K", "1234567" -> "1.2M").
# revenue.decimal_font / orders.decimal_font — когда число сокращается
#   ("12.3K"), часть от точки рисуется этим (обычно более мелким) шрифтом —
#   для визуального разделения, как копейки на ценнике.
# orders.suffix — подпись после числа заказов (например "шт"), маленькими
#   буквами шрифтом orders.suffix_font. Пусто — подпись не рисуется.
#   ВАЖНО: Orbitron кириллицу не содержит вообще, так что suffix_font
#   должен быть verdana_*, а не orbitron_* — иначе буквы не нарисуются.
# ip.scale — IP рисуется ВСТРОЕННЫМ шрифтом framebuf (не Orbitron/Verdana),
#   поэтому тут не "font", а целочисленный масштаб (1 — самый мелкий).

revenue.x = {revenue.x}
revenue.y = {revenue.y}
revenue.font = {revenue.font}
revenue.max_width = {revenue.max_width}
revenue.decimal_font = {revenue.decimal_font}

orders.x = {orders.x}
orders.y = {orders.y}
orders.font = {orders.font}
orders.max_width = {orders.max_width}
orders.decimal_font = {orders.decimal_font}
orders.suffix = {orders.suffix}
orders.suffix_font = {orders.suffix_font}

ip.x = {ip.x}
ip.y = {ip.y}
ip.scale = {ip.scale}

# Напоминание "Собрать FBS" — рисуется, только когда включён чекбокс в веб-
# интерфейсе (раздел "Маркетплейсы"), см. cfg["display"]["show_fbs_reminder"].
# fbs_label.text — сам текст (любой, кириллица и латиница поддерживаются).
# fbs_label.font обязательно verdana_* (Orbitron кириллицу не умеет).
fbs_label.x = {fbs_label.x}
fbs_label.y = {fbs_label.y}
fbs_label.font = {fbs_label.font}
fbs_label.text = {fbs_label.text}
"""

_LAYOUT = LayoutTxtConfig(LAYOUT_TXT_PATH, DEFAULTS, LAYOUT_TXT_TEMPLATE, "layout_400x300")


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
    cfg = _LAYOUT.get()

    revenue_font, revenue_scale = resolve_font(_LAYOUT.cfg_str(cfg, "revenue.font"))
    decimal_font, decimal_scale = resolve_font(_LAYOUT.cfg_str(cfg, "revenue.decimal_font"))
    revenue_max_width = _LAYOUT.cfg_int(cfg, "revenue.max_width")
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
            _LAYOUT.cfg_str(cfg, "revenue.font"), revenue_big, revenue_max_width, extra_width=tail_width
        )
    revenue_x = _LAYOUT.cfg_int(cfg, "revenue.x")
    revenue_y = _LAYOUT.cfg_int(cfg, "revenue.y")
    custom_font.draw_text_with_trailing(
        fb, revenue_font, revenue_big, revenue_x, revenue_y, revenue_trailing, big_scale=revenue_scale,
        center_whole=True,
    )

    orders_font, orders_scale = resolve_font(_LAYOUT.cfg_str(cfg, "orders.font"))
    orders_decimal_font, orders_decimal_scale = resolve_font(_LAYOUT.cfg_str(cfg, "orders.decimal_font"))
    suffix = _LAYOUT.cfg_text(cfg, "orders.suffix")
    suffix_font = suffix_scale = None
    orders_max_width = _LAYOUT.cfg_int(cfg, "orders.max_width")
    if suffix:
        suffix_font, suffix_scale = resolve_font(_LAYOUT.cfg_str(cfg, "orders.suffix_font"))
        suffix_text = " " + suffix
        orders_max_width = max(1, orders_max_width - custom_font.text_width(suffix_font, suffix_text, suffix_scale))

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
                _LAYOUT.cfg_str(cfg, "orders.font"), orders_big, orders_max_width
            )
    if suffix:
        orders_trailing.append((" " + suffix, suffix_font, suffix_scale))

    orders_x = _LAYOUT.cfg_int(cfg, "orders.x")
    orders_y = _LAYOUT.cfg_int(cfg, "orders.y")
    custom_font.draw_text_with_trailing(
        fb, orders_font, orders_big, orders_x, orders_y, orders_trailing, big_scale=orders_scale,
    )

    ip = data.get("ip") or ""
    if ip:
        ip_scale = _LAYOUT.cfg_int(cfg, "ip.scale")
        ip_x = _LAYOUT.cfg_int(cfg, "ip.x")
        ip_y = _LAYOUT.cfg_int(cfg, "ip.y")
        draw_scaled_text_centered(fb, ip, ip_x, ip_y, scale=ip_scale)

    # Напоминание "Собрать FBS" — см. cfg["display"]["show_fbs_reminder"].
    if data.get("show_fbs_label"):
        fbs_text = _LAYOUT.cfg_text(cfg, "fbs_label.text")
        if fbs_text:
            fbs_font, fbs_scale = resolve_font(_LAYOUT.cfg_str(cfg, "fbs_label.font"))
            custom_font.draw_text_centered(
                fb, fbs_font, fbs_text,
                _LAYOUT.cfg_int(cfg, "fbs_label.x"), _LAYOUT.cfg_int(cfg, "fbs_label.y"), scale=fbs_scale,
            )


def render(fb, data):
    """Полная перерисовка (статика + динамика) — используется при первом
    выводе после включения/сна панели."""
    static_frame(fb)
    update_numbers(fb, data)
