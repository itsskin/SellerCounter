"""Растеризует Verdana (Fonts/Verdana/Verdana.ttf в корне проекта) в
display/fonts/verdana_<size>.py — см. font_render_lib.py про сам формат и
почему не micropython-font-to-py.

Запуск (только этот шрифт, на компьютере): python3 generate_verdana_font.py

Каталог display/fonts/available_sizes.txt этот скрипт НЕ трогает — см.
generate_all_fonts.py, если нужно обновить каталог для всех семейств разом.
"""

import os

import font_render_lib as lib

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Fonts", "Verdana", "Verdana.ttf")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
NAME_PREFIX = "verdana"

SPACING = 0

# Verdana заметно шире Orbitron при том же pt — размеры подобраны так,
# чтобы реальная высота цифр (см. вывод скрипта / available_sizes.txt)
# получилась в похожем диапазоне, что и у Orbitron (~8-50px). 64-80 — под
# подписи/суффиксы на экране 400x300 (там всё крупнее, см. также
# generate_orbitron_font.py).
SIZES = [8, 14, 15, 18, 20, 24, 28, 32, 36, 40, 46, 52, 58, 64, 72, 80]

# Свой (не DEFAULT_CHARSET) алфавит: Orbitron кириллицу вообще не содержит
# (см. его generate_orbitron_font.py), так что подписи вроде "шт" рисуются
# Verdana — единственным шрифтом в проекте с кириллицей.
#
# Раньше тут были только буквы "шт" (под конкретную подпись заказов) — но
# с тех пор как текст метки стал настраиваемым полем в layout.txt
# (fbs_label.text и т.п.), шрифт должен уметь нарисовать любую разумную
# фразу на русском или английском, а не только заранее известный набор
# символов. Полный алфавит (заглавные+строчные, кириллица+латиница) плюс
# пробел — без этого draw_text() молча пропускает отсутствующие символы
# (см. custom_font.py), и метка выходит обрубленной до одной-двух букв,
# которые случайно совпали с DEFAULT_CHARSET (HW-подтверждено: "Собрать
# FBS" рисовалась как одна буква "т").
_LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
CHARSET = lib.DEFAULT_CHARSET + " " + _LATIN + _CYRILLIC


if __name__ == "__main__":
    lib.render_family(FONT_PATH, OUT_DIR, NAME_PREFIX, SIZES, CHARSET, SPACING)
    print("Каталог не обновлён — запусти generate_all_fonts.py, если менял и Orbitron, и Verdana.")
