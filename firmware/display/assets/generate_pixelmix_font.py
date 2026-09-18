"""Растеризует Pixelmix (Fonts/pixelmix.ttf в корне проекта) в
display/fonts/pixelmix_<size>.py — см. font_render_lib.py про сам формат
и почему не micropython-font-to-py.

Запуск (только этот шрифт, на компьютере): python3 generate_pixelmix_font.py

Каталог display/fonts/available_sizes.txt этот скрипт НЕ трогает (он на
все семейства шрифтов разом) — если нужен свежий каталог, запускай
generate_all_fonts.py.
"""

import os

import font_render_lib as lib

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Fonts", "pixelmix.ttf")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
NAME_PREFIX = "pixelmix"

SPACING = 0

# 7 — по запросу (мельче, чем самый мелкий Orbitron — orbitron_12/9px —
# и, в отличие от него, Pixelmix специально нарисован пиксельным под
# мелкие размеры, а не геометрический шрифт, ужатый до предела). 8 —
# следующий шаг, тоже по запросу.
SIZES = [7, 8]

# Pixelmix кириллицу не содержит вообще (проверено по cmap шрифта) —
# только латиница + DEFAULT_CHARSET (цифры/.-KM), как у Orbitron/default_10.
# Кириллические подписи ("шт" и т.п.) по-прежнему только Verdana.
_LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHARSET = lib.DEFAULT_CHARSET + " " + _LATIN


if __name__ == "__main__":
    lib.render_family(FONT_PATH, OUT_DIR, NAME_PREFIX, SIZES, CHARSET, SPACING)
    print("Каталог не обновлён — запусти generate_all_fonts.py, если нужен свежий available_sizes.txt.")
