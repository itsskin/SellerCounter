"""Растеризует ВСТРОЕННЫЙ 8x8 ASCII-шрифт MicroPython framebuf в
display/fonts/default_10.py — в том же формате (HEIGHT/SPACING/GLYPHS), что
generate_orbitron_font.py/generate_verdana_font.py генерируют из TTF.

В отличие от тех двух — тут НЕТ исходного TTF-файла: framebuf.FrameBuffer
.text() рисует встроенным, скомпилированным прямо в прошивку шрифтом,
недоступным на компьютере. Поэтому растеризация идёт НА САМОЙ ПЛАТЕ (через
raw REPL, см. tools/mpy-raw-serial) — этому скрипту нужна физически
подключённая плата, в отличие от остальных генераторов шрифтов.

Название "default_10" — под общую схему "<семейство>_<номинальный размер>"
(см. resolve_font() в display/layout_common.py), хотя реальная высота
глифов 8px — встроенный шрифт framebuf всегда ровно 8x8, не масштабируется
на этапе растеризации (масштабирование делает draw_text() через scale,
как и у Orbitron/Verdana).

Зачем вообще нужен — Orbitron на маленьких размерах (10px и ниже) визуально
разваливается (тонкие диагональные засечки геометричного шрифта), тогда как
встроенный шрифт framebuf спроектирован именно под мелкие пиксельные
надписи и остаётся чётким. Кириллицу он не умеет (компилируется в прошивку
как обычный ASCII-набор) — алфавит цифры+.-KM + латиница (для коротких
латинских подписей вроде "Oz"/"Wb"/"Ya" на экране детализации по
маркетплейсам, см. layout_400x300._draw_marketplace_breakdown), не полный
latin+cyrillic набор Verdana.

Запуск (плата должна быть подключена):
    python3 generate_default_font.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "mpy-raw-serial"))
import raw_serial as rs

import font_render_lib as lib

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
NAME = "default_10"
_LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHARSET = lib.DEFAULT_CHARSET + " " + _LATIN

# Код, выполняемый НА ПЛАТЕ — рисует каждый символ встроенным шрифтом в
# отдельный 8x8 FrameBuffer (MONO_HLSB — тот же 1bpp построчный формат,
# что и в font_render_lib.py), печатает готовый GLYPHS-литерал на stdout.
_DEVICE_CODE = """\
import framebuf
_charset = %r
_glyphs = {}
for _ch in _charset:
    _buf = bytearray(8)
    _fb = framebuf.FrameBuffer(_buf, 8, 8, framebuf.MONO_HLSB)
    _fb.fill(0)
    _fb.text(_ch, 0, 0, 1)
    _glyphs[_ch] = (8, bytes(_buf))
for _ch in _charset:
    print("    %%r: %%r," %% (_ch, _glyphs[_ch]))
""" % CHARSET


def main():
    fd = rs.open_port(rs.find_port())
    rs.enter_raw_repl(fd)
    try:
        out = rs.exec_raw(fd, _DEVICE_CODE, timeout=15).decode()
    finally:
        rs.exit_raw_repl(fd)
        os.close(fd)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, NAME + ".py")
    with open(out_path, "w") as f:
        f.write(
            "# Растеризовано из встроенного 8x8 ASCII-шрифта framebuf (не TTF — см.\n"
            "# generate_default_font.py). Не редактировать руками.\n\n"
        )
        f.write("HEIGHT = 8\n")
        f.write("SPACING = 0\n")
        f.write("GLYPHS = {\n")
        f.write(out)
        f.write("}\n")
    size = os.path.getsize(out_path)
    print("%s: %d байт" % (out_path, size))
    return size


if __name__ == "__main__":
    main()

    # Каталог (available_sizes.txt) — общий на все семейства (см.
    # write_catalog()). Пересобираем ЦЕЛИКОМ, а не дописываем руками:
    # перегенерация Orbitron/Verdana из TTF дешёвая и детерминированная
    # (те же байты на выходе), так что заодно держит каталог в одном месте
    # синхронным со всеми тремя семействами разом.
    import generate_orbitron_font as orbitron
    import generate_verdana_font as verdana

    families = {
        "default": [(10, 8)],
        orbitron.NAME_PREFIX: lib.render_family(
            orbitron.FONT_PATH, orbitron.OUT_DIR, orbitron.NAME_PREFIX, orbitron.SIZES, orbitron.CHARSET,
            orbitron.SPACING,
        ),
        verdana.NAME_PREFIX: lib.render_family(
            verdana.FONT_PATH, verdana.OUT_DIR, verdana.NAME_PREFIX, verdana.SIZES, verdana.CHARSET, verdana.SPACING
        ),
    }
    lib.write_catalog(OUT_DIR, families)
