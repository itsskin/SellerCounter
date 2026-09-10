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
# выручка и заказы. Где именно и каким шрифтом — задаётся текстовым файлом
# assets/layout.txt (создаётся с дефолтами при первом запуске, если его
# нет) — правится руками, подхватывается на следующей перерисовке без
# перезагрузки платы. Время/дата/IP — отложены, пока не рисуются.
#
# data, ожидаемый на входе render()/update_numbers():
# {
#   "orders": int,
#   "revenue": float,
# }

import framebuf

from display import custom_font
from display.layout_common import LayoutTxtConfig, resolve_font, shrink_font_to_fit, split_compact

WIDTH = 200
HEIGHT = 200

ASSETS_DIR = "/display/assets"
BG_PATH = ASSETS_DIR + "/bg_200x200.bin"
LAYOUT_TXT_PATH = ASSETS_DIR + "/layout.txt"

# Дефолты — то, что было жёстко зашито раньше (макет seller_m8_v1.1). Если
# assets/layout.txt нет или в нём опечатка в каком-то поле — используется
# значение отсюда, так что кривая правка руками не может сломать экран
# насмерть, просто откатится к дефолту по этому конкретному полю.
DEFAULTS = {
    "revenue.x": "100",
    "revenue.y": "73",
    "revenue.font": "orbitron_52",
    "revenue.max_width": "176",
    # Когда выручка сокращается до вида "12.3K"/"1.2M" (см. format_compact),
    # часть от точки и дальше рисуется этим, более мелким шрифтом — для
    # визуального разделения целой части и сокращения, как копейки на
    # ценнике. Если revenue.font поменяешь на что-то сильно другое по
    # размеру — этот дефолт может смотреться непропорционально, тогда
    # поправь и его тоже.
    "revenue.decimal_font": "orbitron_36",
    "orders.x": "100",
    "orders.y": "126",
    "orders.font": "orbitron_42",
    "orders.max_width": "176",
    # Если заказы тоже сокращаются до вида "1.5K" (см. format_compact) —
    # часть от точки рисуется этим, более мелким шрифтом, тем же приёмом,
    # что и revenue.decimal_font у выручки.
    "orders.decimal_font": "orbitron_24",
    # Подпись после числа заказов (например "шт") — маленькими буквами,
    # отдельным шрифтом. Orbitron кириллицу не умеет вообще, поэтому тут
    # обязательно verdana_*, а не orbitron_*. Пусто по умолчанию — подпись
    # теперь часть фоновой картинки (статично, под цифрой), не рисуется
    # динамически; можно включить обратно, просто вписав текст в это поле.
    "orders.suffix": "",
    "orders.suffix_font": "verdana_15",
    "clock.x": "100",
    "clock.y": "10",
    # Дата — только цифры и дефис, кириллица не нужна — можно Orbitron
    # (гораздо компактнее файла шрифта, чем Verdana, см.
    # generate_orbitron_font.py). Verdana в комплекте остаётся только под
    # то, что реально кириллическое (suffix "шт", fbs_label).
    "clock.font": "orbitron_20",
    # Напоминание "Собрать FBS" (см. cfg["display"]["show_fbs_reminder"] в
    # web_server.py/www) — рисуется, только когда чекбокс в веб-интерфейсе
    # включён. Текст настраивается через fbs_label.text (можно вписать
    # что угодно — Verdana теперь умеет полный алфавит кириллицы и
    # латиницы, не только "шт"). Orbitron кириллицу не умеет — font
    # обязательно verdana_*.
    "fbs_label.x": "100",
    "fbs_label.y": "165",
    "fbs_label.font": "verdana_15",
    "fbs_label.text": "Собрать FBS",
}

LAYOUT_TXT_TEMPLATE = """\
# Расположение текста на экране 200x200 (SellerCounter).
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
#   сокращается ("12345" -> "12.3K", "1234567" -> "1.2M"). У даты (clock)
#   такого поля нет — она не сокращается, просто выводится как есть.
# revenue.decimal_font / orders.decimal_font — когда число сокращается
#   ("12.3K"), часть от точки рисуется этим (обычно более мелким) шрифтом —
#   для визуального разделения, как копейки на ценнике.
# orders.suffix — подпись после числа заказов (например "шт"), маленькими
#   буквами шрифтом orders.suffix_font. Пусто — подпись не рисуется.
#   ВАЖНО: Orbitron кириллицу не содержит вообще, так что suffix_font
#   должен быть verdana_*, а не orbitron_* — иначе буквы не нарисуются.

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

# Дата, формат ДД-ММ-ГГГГ (например "05-12-2026") — берётся из данных
# опроса (stats_engine), сам формат тут не настраивается.
clock.x = {clock.x}
clock.y = {clock.y}
clock.font = {clock.font}

# Напоминание "Собрать FBS" — рисуется, только когда включён чекбокс в веб-
# интерфейсе (раздел "Маркетплейсы"), см. cfg["display"]["show_fbs_reminder"].
# fbs_label.text — сам текст (любой, кириллица и латиница поддерживаются).
# fbs_label.font обязательно verdana_* (Orbitron кириллицу не умеет).
fbs_label.x = {fbs_label.x}
fbs_label.y = {fbs_label.y}
fbs_label.font = {fbs_label.font}
fbs_label.text = {fbs_label.text}
"""


_LAYOUT = LayoutTxtConfig(LAYOUT_TXT_PATH, DEFAULTS, LAYOUT_TXT_TEMPLATE, "layout_200x200")
_get_layout_config = _LAYOUT.get
_cfg_int = _LAYOUT.cfg_int
_cfg_str = _LAYOUT.cfg_str
_cfg_text = _LAYOUT.cfg_text


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
    cfg = _get_layout_config()

    revenue_font, revenue_scale = resolve_font(_cfg_str(cfg, "revenue.font"))
    # decimal_font резолвим ДО format_compact и передаём туда же — иначе
    # проверка "влезает ли по ширине" считала бы дробную часть тем же
    # крупным шрифтом, что и целую, и решила бы, что "13.5K" не влезает
    # (хотя реально рисуется мельче и прекрасно влезает) — откатывалась бы
    # на "14K" без точки раньше, чем нужно на самом деле.
    decimal_font, decimal_scale = resolve_font(_cfg_str(cfg, "revenue.decimal_font"))
    revenue_max_width = _cfg_int(cfg, "revenue.max_width")
    revenue_text = custom_font.format_compact(
        revenue_font,
        data.get("revenue", 0),
        revenue_max_width,
        revenue_scale,
        decimal_font=decimal_font,
        decimal_scale=decimal_scale,
        max_decimals=1,  # "13.5K" с точкой, если влезает; иначе сама откатится на "654K" без точки
    )
    revenue_x = _cfg_int(cfg, "revenue.x")
    revenue_y = _cfg_int(cfg, "revenue.y")
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
            _cfg_str(cfg, "revenue.font"), revenue_big, revenue_max_width, extra_width=tail_width
        )
    custom_font.draw_text_with_trailing(
        fb, revenue_font, revenue_big, revenue_x, revenue_y, revenue_trailing, big_scale=revenue_scale,
        center_whole=True,
    )

    orders_font, orders_scale = resolve_font(_cfg_str(cfg, "orders.font"))
    orders_decimal_font, orders_decimal_scale = resolve_font(_cfg_str(cfg, "orders.decimal_font"))

    # Суффикс резолвим и меряем ДО format_compact и вычитаем его ширину из
    # бюджета — иначе на очень больших количествах заказов (в жизни
    # маловероятно, но мало ли) "шт" рисовалась бы за пределами экрана:
    # format_compact без этого гарантирует, что влезет только само число,
    # без места под то, что дорисуется следом.
    suffix = _cfg_text(cfg, "orders.suffix")
    suffix_font = suffix_scale = None
    orders_max_width = _cfg_int(cfg, "orders.max_width")
    if suffix:
        # У Orbitron нет кириллицы вообще, поэтому suffix_font обязательно
        # verdana_*, а не orbitron_* (см. DEFAULTS/шаблон).
        suffix_font, suffix_scale = resolve_font(_cfg_str(cfg, "orders.suffix_font"))
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
        min_abbrev=10000,  # до "9999" показываем полностью, "10000"+ — можно сократить, если не влезает
    )
    orders_x = _cfg_int(cfg, "orders.x")
    orders_y = _cfg_int(cfg, "orders.y")

    # Само число (без хвостов) центрируется по orders.x/y — ни дробная
    # часть ("1.5K"), ни подпись ("шт") в расчёт центра не идут, иначе
    # число будет "гулять" от центра в зависимости от того, что к нему
    # дописано (см. запрос пользователя — раньше так и было для суффикса).
    orders_big, orders_tail = split_compact(orders_text)
    orders_trailing = [(orders_tail, orders_decimal_font, orders_decimal_scale)] if orders_tail else []
    if not orders_tail:
        # min_abbrev держит число полным даже если оно не влезает по ширине
        # (классика — "999" ещё влезает, "1000"+ уже нет) — раз сократить в
        # "1K" нельзя, ужимаем сам шрифт, кегль за кеглем, пока не влезет.
        if custom_font.text_width(orders_font, orders_big, orders_scale) > orders_max_width:
            orders_font, orders_scale = shrink_font_to_fit(
                _cfg_str(cfg, "orders.font"), orders_big, orders_max_width
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
    if clock_text:
        clock_font, clock_scale = resolve_font(_cfg_str(cfg, "clock.font"))
        custom_font.draw_text_centered(
            fb, clock_font, clock_text, _cfg_int(cfg, "clock.x"), _cfg_int(cfg, "clock.y"), scale=clock_scale
        )

    # Напоминание "Собрать FBS" — см. cfg["display"]["show_fbs_reminder"].
    if data.get("show_fbs_label"):
        fbs_text = _cfg_text(cfg, "fbs_label.text")
        if fbs_text:
            fbs_font, fbs_scale = resolve_font(_cfg_str(cfg, "fbs_label.font"))
            custom_font.draw_text_centered(
                fb, fbs_font, fbs_text, _cfg_int(cfg, "fbs_label.x"), _cfg_int(cfg, "fbs_label.y"), scale=fbs_scale
            )


def render(fb, data):
    update_numbers(fb, data)
