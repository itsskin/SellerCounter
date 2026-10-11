# Рендерер кастомных пиксельных шрифтов (см. display/fonts/*.py, сгенерированы
# assets/generate_orbitron_font.py из Fonts/Orbitron/Orbitron.ttf). Формат
# шрифта — свой, не framebuf: модуль экспортирует HEIGHT (px), SPACING
# (промежуток между глифами) и GLYPHS — {символ: (width, bytes)}, где bytes —
# 1bpp построчно, MSB первый, (width+7)//8 байт на строку, HEIGHT строк.
#
# scale — целочисленный апскейл поверх готового битмапа (см. layout_200x200
# ._resolve_font): если запрошенного размера нет среди сгенерированных
# файлов, берём ближайший меньший и увеличиваем его сюда. Разворачивать
# вниз (уменьшать) так нельзя — 1-битная картинка это не переживает
# (см. обсуждение в истории проекта), только вверх.


def text_width(font, text, scale=1):
    glyphs = font.GLYPHS
    w = 0
    first = True
    for ch in text:
        glyph = glyphs.get(ch)
        if glyph is None:
            continue
        if not first:
            w += font.SPACING
        w += glyph[0]
        first = False
    return w * scale


def _ink_bottom_row(font, text):
    """Последняя (считая от 0 сверху) строка среди глифов text, где есть
    хоть один закрашенный пиксель — -1, если text пустой/без известных
    символов.

    font.HEIGHT — общий на ВЕСЬ алфавит шрифта диапазон (см.
    font_render_lib.render_variant): он подгоняется под самый нижний глиф
    ВСЕГО charset, а не конкретно text. У Verdana в charset есть кириллица
    со спускающимися ниже строки буквами ("р", "у", "д", "ц", "щ") — под их
    хвостики HEIGHT включает запас снизу. Если в text таких букв нет
    (например "шт"), реальные чернила заканчиваются на несколько пикселей
    ВЫШЕ нижнего края font.HEIGHT — выравнивание по font.HEIGHT (как раньше
    делал draw_text_with_trailing) визуально "приподнимало" такой текст над
    базовой линией соседнего числа. Считаем реальный нижний край вместо
    того, чтобы полагаться на HEIGHT."""
    glyphs = font.GLYPHS
    height = font.HEIGHT
    bottom = -1
    for ch in text:
        glyph = glyphs.get(ch)
        if glyph is None:
            continue
        gw, data = glyph
        row_bytes = (gw + 7) // 8
        for gy in range(height - 1, bottom, -1):
            base = gy * row_bytes
            if any(data[base + gx // 8] & (1 << (7 - (gx % 8))) for gx in range(gw)):
                if gy > bottom:
                    bottom = gy
                break
    return bottom


def draw_text(fb, font, text, x, y, color=1, scale=1):
    """x, y — левый верхний угол текста."""
    glyphs = font.GLYPHS
    height = font.HEIGHT
    cx = x
    for ch in text:
        glyph = glyphs.get(ch)
        if glyph is None:
            continue
        gw, data = glyph
        row_bytes = (gw + 7) // 8
        if scale == 1:
            for gy in range(height):
                base = gy * row_bytes
                for gx in range(gw):
                    byte = data[base + gx // 8]
                    bit = 7 - (gx % 8)
                    if byte & (1 << bit):
                        fb.pixel(cx + gx, y + gy, color)
        else:
            for gy in range(height):
                base = gy * row_bytes
                for gx in range(gw):
                    byte = data[base + gx // 8]
                    bit = 7 - (gx % 8)
                    if byte & (1 << bit):
                        fb.fill_rect(cx + gx * scale, y + gy * scale, scale, scale, color)
        cx += (gw + font.SPACING) * scale


def draw_text_centered(fb, font, text, center_x, center_y, color=1, scale=1):
    w = text_width(font, text, scale)
    h = font.HEIGHT * scale
    x = center_x - w // 2
    y = center_y - h // 2
    draw_text(fb, font, text, x, y, color, scale)


def draw_text_with_trailing(
    fb, big_font, big_text, center_x, center_y, trailing, color=1, big_scale=1, gap=0, center_whole=False
):
    """trailing — список (text, font, scale), дорисовываются подряд правее
    big_text (с отступом gap перед каждым), низ каждого выровнен по низу
    РЕАЛЬНЫХ ЧЕРНИЛ big_text, не по границе его bitmap-бокса (нижний индекс
    — как копейки у выручки "12.3K" или подпись "шт" у заказов "128 шт";
    можно и то, и другое сразу: trailing=[(".3K", decimal_font, s1),
    (" шт", suffix_font, s2)]).

    Выравнивание по _ink_bottom_row(), а не по font.HEIGHT — нужно, потому
    что у Verdana (используется для кириллических суффиксов/подписей)
    font.HEIGHT подогнан под самый нижний глиф всего charset, включая буквы
    со спускающимися хвостиками ("р", "у", "д" и т.п.); у текста без таких
    букв ("шт") реальные чернила выше нижнего края font.HEIGHT — выравнивая
    по HEIGHT, "шт" визуально "повисало" над базовой линией числа.

    center_whole решает, ЧТО именно центрируется по (center_x, center_y):
    - False (дефолт) — только big_text, хвосты в расчёт центра не идут и
      просто пристёгиваются справа. Нужно, когда есть смысловой суффикс
      (штуки), который не должен сдвигать само число от центра — заказы
      "128" всегда точно по центру, "шт" просто дописана правее.
    - True — big_text + все хвосты вместе, как единый блок (весь текст по
      центру). Нужно для выручки: "13.5K" без суффикса — это одно число,
      выглядело бы криво, если бы только "13" стояла по центру, а ".5K"
      уезжала вправо от него."""
    big_w = text_width(big_font, big_text, big_scale)
    big_h = big_font.HEIGHT * big_scale

    total_w = big_w
    if center_whole:
        for text, font, scale in trailing:
            if text:
                total_w += gap + text_width(font, text, scale)

    x = center_x - total_w // 2
    y_big = center_y - big_h // 2

    big_ink_bottom = _ink_bottom_row(big_font, big_text)
    if big_ink_bottom < 0:
        big_ink_bottom = big_font.HEIGHT - 1
    bottom = y_big + (big_ink_bottom + 1) * big_scale

    draw_text(fb, big_font, big_text, x, y_big, color, big_scale)

    cx = x + big_w
    for text, font, scale in trailing:
        if not text:
            continue
        cx += gap
        ink_bottom = _ink_bottom_row(font, text)
        if ink_bottom < 0:
            ink_bottom = font.HEIGHT - 1
        h = (ink_bottom + 1) * scale
        y = bottom - h
        draw_text(fb, font, text, cx, y, color, scale)
        cx += text_width(font, text, scale)


def format_compact(font, value, max_width, scale=1, decimal_font=None, decimal_scale=1, max_decimals=3, min_abbrev=0):
    """Целое число как строка; если не влезает в max_width — сокращаем
    тысячи в "K", миллионы в "M". Пробуем от max_decimals цифр после точки
    и вниз до 0, пока не влезет.

    decimal_font/decimal_scale — если заданы, часть строки от точки и
    дальше меряется ЭТИМ (обычно более мелким) шрифтом при проверке
    ширины — то есть так же, как её потом реально нарисует
    draw_text_with_trailing. Без этого (decimal_font=None) вся строка
    меряется одним font/scale — тогда даже "13.5K" может ложно не
    "влезать", если считать её целиком основным (крупным) шрифтом, хотя
    реально дробная часть рисуется мельче.

    min_abbrev — сокращение вообще не рассматривается, пока value меньше
    этого порога, даже если по ширине не влезло бы (тогда просто вылезет
    за край — предполагается, что порог выставлен так, что до него
    полное число гарантированно влезает). Нужно, чтобы "999" не вдруг не
    сократилось в "1K" на пограничных по ширине значениях — предсказуемое
    поведение важнее пиксельной точности."""
    plain = "%d" % round(value)
    if value < min_abbrev or text_width(font, plain, scale) <= max_width:
        return plain

    if value < 1000000:
        unit = 1000.0
        suffix = "K"
        if round(value / unit) >= 1000:
            # 999500-999999 при округлении до тысяч дают не "999K"/"1000K",
            # а фактически уже миллион — переключаемся на "M", иначе была
            # бы бессмысленная "1000K" (и она ещё и не влезает по ширине).
            unit = 1000000.0
            suffix = "M"
    else:
        unit = 1000000.0
        suffix = "M"

    dec_font = decimal_font if decimal_font is not None else font
    dec_scale = decimal_scale if decimal_font is not None else scale

    candidate = "%d%s" % (round(value / unit), suffix)  # decimals=0, на случай если цикл ниже пустой
    for decimals in range(max_decimals, -1, -1):
        if decimals == 0:
            # ВАЖНО: пересчитать заново, а не переиспользовать candidate из
            # предыдущей (неудавшейся) итерации с точкой — иначе тут молча
            # осталась бы строка вида "654.3K" вместо настоящего отката на
            # "654K" (реальный баг, ловился на выручке 100К-999К).
            candidate = "%d%s" % (round(value / unit), suffix)
            int_part, frac_part = candidate, ""
        else:
            candidate = ("%." + str(decimals) + "f%s") % (value / unit, suffix)
            dot = candidate.index(".")
            int_part, frac_part = candidate[:dot], candidate[dot:]
        w = text_width(font, int_part, scale) + text_width(dec_font, frac_part, dec_scale)
        if w <= max_width:
            return candidate

    return candidate
