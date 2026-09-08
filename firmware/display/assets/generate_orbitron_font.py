"""Растеризует Orbitron (Fonts/Orbitron/Orbitron.ttf в корне проекта) в
display/fonts/orbitron_<size>.py — см. font_render_lib.py про сам формат
и почему не micropython-font-to-py.

Запуск (только этот шрифт, на компьютере): python3 generate_orbitron_font.py

Каталог display/fonts/available_sizes.txt этот скрипт НЕ трогает (он на
все семейства шрифтов разом, перезаписывать его отсюда — стереть в нём
записи про Verdana). Если нужен свежий каталог — запускай
generate_all_fonts.py, он гоняет все семейства и пишет каталог одним разом.
"""

import os

import font_render_lib as lib

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Fonts", "Orbitron", "Orbitron.ttf")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
NAME_PREFIX = "orbitron"

# advance width из font.getlength() уже включает нужный отступ до следующего
# глифа (проверено визуально) — доп. зазор не нужен, только съедает и так
# небольшой бюджет ширины зоны на маленьком экране.
SPACING = 0

# Размеры шрифта в pt для PIL. Имя модуля — "orbitron_<size>" (номинальный
# pt, не реальная высота в пикселях — она чуть меньше, см.
# available_sizes.txt после генерации). 42 и 52 — то, что уже используется
# по умолчанию в layout_200x200.py (заказы/выручка) на экране 200x200,
# остальные — на выбор через display/assets/layout.txt. 80-144 добавлены
# под экран 400x300 (layout_400x300.py) — там секции почти вдвое просторнее
# по ширине, апскейл существующих мелких размеров выглядел бы "кубиками".
SIZES = [8, 16, 20, 24, 30, 36, 42, 48, 52, 58, 64, 70, 80, 96, 112, 128, 144]

# Orbitron кириллицу не содержит вообще — обычный DEFAULT_CHARSET (цифры +
# .-KM), без букв. Подписи кириллицей (см. "шт" у заказов) рисуются
# Verdana — см. generate_verdana_font.py, у него свой, расширенный алфавит.
CHARSET = lib.DEFAULT_CHARSET


if __name__ == "__main__":
    lib.render_family(FONT_PATH, OUT_DIR, NAME_PREFIX, SIZES, CHARSET, SPACING)
    print("Каталог не обновлён — запусти generate_all_fonts.py, если менял и Orbitron, и Verdana.")
