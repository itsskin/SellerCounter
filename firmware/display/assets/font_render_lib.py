"""Общая логика растеризации TTF в компактные модули с 1bpp-битмапами
глифов — свой формат, не micropython-font-to-py (тот тянет freetype-py на
этапе генерации, а нам хватает PIL). Используется generate_orbitron_font.py
и generate_verdana_font.py — каждый только указывает свой .ttf, набор
символов и диапазон размеров, сама растеризация и запись файлов тут одна.

На устройство сам .ttf никогда не уезжает — только готовые пиксели для
нужных символов (так же, как и с фоном, см. convert_bg_200x200.py).

Все глифы растеризуются на общей базовой линии (anchor="ls"), чтобы цифры
разной формы ("1" и "8") не "плавали" по вертикали относительно друг друга.
"""

import os

from PIL import Image, ImageDraw, ImageFont

# Общий набор символов для всех шрифтов проекта: цифры + точка/дефис (даты
# вида "05-12-2026", отрицательные значения) + K/M (сокращения "12.3K"/
# "1.2M"). Один и тот же алфавит на все семейства — проще держать в голове,
# какие символы вообще можно вывести любым из шрифтов.
DEFAULT_CHARSET = "0123456789.-KM"


def render_variant(font_path, size, out_dir, name_prefix, charset, spacing=0):
    name = "%s_%d" % (name_prefix, size)
    font = ImageFont.truetype(font_path, size)
    ascent, descent = font.getmetrics()
    canvas_h = ascent + descent

    # Канва (ascent+descent) намного выше реальных чернил цифр — если взять
    # её как HEIGHT как есть, центрирование по центру канвы уедет от центра
    # реальных цифр (пустого места сверху много). Поэтому первым проходом
    # находим общий (по всем глифам) диапазон непустых строк и обрезаем по
    # нему — базовая линия (relative alignment) при этом сохраняется, потому
    # что обрезка одинаковая для всех глифов.
    raw = {}
    top_min = None
    bottom_max = None
    for ch in charset:
        adv = int(round(font.getlength(ch)))
        width = max(adv, 1)
        canvas = Image.new("L", (width + 8, canvas_h), 255)
        d = ImageDraw.Draw(canvas)
        d.text((0, ascent), ch, font=font, fill=0, anchor="ls")
        px = canvas.load()
        rows_with_ink = [y for y in range(canvas_h) if any(px[x, y] < 128 for x in range(width))]
        if rows_with_ink:
            top_min = min(top_min, rows_with_ink[0]) if top_min is not None else rows_with_ink[0]
            bottom_max = max(bottom_max, rows_with_ink[-1]) if bottom_max is not None else rows_with_ink[-1]
        raw[ch] = (width, canvas, px)

    height = bottom_max - top_min + 1

    glyphs = {}
    for ch, (width, canvas, px) in raw.items():
        row_bytes = (width + 7) // 8
        buf = bytearray(row_bytes * height)
        for y in range(height):
            src_y = top_min + y
            for x in range(width):
                if px[x, src_y] < 128:
                    idx = y * row_bytes + x // 8
                    bit = 7 - (x % 8)
                    buf[idx] |= 1 << bit
        glyphs[ch] = (width, bytes(buf))

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, name + ".py")
    with open(out_path, "w") as f:
        f.write(
            "# Автосгенерировано из %s (размер %d, символы %r). "
            "Не редактировать руками.\n\n" % (os.path.basename(font_path), size, charset)
        )
        f.write("HEIGHT = %d\n" % height)
        f.write("SPACING = %d\n" % spacing)
        f.write("GLYPHS = {\n")
        for ch, (width, data) in glyphs.items():
            f.write("    %r: (%d, %r),\n" % (ch, width, data))
        f.write("}\n")
    print("%s: %d байт, высота %dpx" % (out_path, os.path.getsize(out_path), height))
    return height


def render_family(font_path, out_dir, name_prefix, sizes, charset, spacing=0):
    """Растеризует весь диапазон sizes, возвращает [(size, реальная высота)]."""
    result = []
    for size in sizes:
        h = render_variant(font_path, size, out_dir, name_prefix, charset, spacing)
        result.append((size, h))
    return result


def write_catalog(out_dir, families):
    """families — {name_prefix: [(size, height), ...]}. Один общий каталог
    на все семейства шрифтов в display/fonts/."""
    catalog_path = os.path.join(out_dir, "available_sizes.txt")
    with open(catalog_path, "w") as f:
        f.write(
            "Доступные шрифты/размеры в display/fonts/<name>_<N>.py.\n"
            "Не грузится на устройство как данные — просто справка для правки\n"
            "display/assets/layout.txt (поле font).\n\n"
        )
        for prefix, sizes_and_heights in families.items():
            f.write("%s:\n" % prefix)
            f.write("  имя файла          реальная высота цифр на экране\n")
            for size, h in sizes_and_heights:
                f.write("  %s_%-8d %dpx\n" % (prefix, size, h))
            f.write("\n")
        f.write(
            "Если в layout.txt указать размер, которого нет у данного семейства —\n"
            "плата возьмёт ближайший меньший ИЗ ЭТОГО СЕМЕЙСТВА и увеличит его до\n"
            "нужного целым числом (апскейл, картинка становится 'кубиками', но\n"
            "разборчиво). Уменьшать так нельзя — только увеличивать. Смешивать\n"
            "семейства при подборе ближайшего размера нельзя (значит, если для\n"
            "verdana_90 нет размера крупнее самого большого verdana_*, orbitron_*\n"
            "вместо него не возьмётся).\n"
        )
    print("каталог размеров:", catalog_path)
