"""Растеризует Orbitron Bold (Fonts/Orbitron/Orbitron Bold.otf) в
display/fonts/orbitronbold_<size>.py — см. font_render_lib.py про формат.
Имя семейства "orbitronbold" (без "_"), чтобы не путаться с orbitron_<size>
в resolve_font() — он делит имя по последнему "_".

Запуск (только этот шрифт): python3 generate_orbitronbold_font.py
Каталог available_sizes.txt этот скрипт НЕ трогает — см. generate_all_fonts.py.
"""

import os

import font_render_lib as lib

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Fonts", "Orbitron", "Orbitron Bold.otf")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
NAME_PREFIX = "orbitronbold"

SPACING = 0

SIZES = [14, 25, 45, 70]

# Как у обычного Orbitron — только цифры и .-KM, букв нет.
CHARSET = lib.DEFAULT_CHARSET


if __name__ == "__main__":
    lib.render_family(FONT_PATH, OUT_DIR, NAME_PREFIX, SIZES, CHARSET, SPACING)
