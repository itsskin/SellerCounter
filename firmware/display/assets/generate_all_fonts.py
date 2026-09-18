"""Перегенерирует ВСЕ семейства шрифтов (Orbitron, Verdana, Pixelmix) и общий
каталог display/fonts/available_sizes.txt одним запуском. Предпочтительный
способ обновить шрифты — generate_orbitron_font.py/generate_verdana_font.py/
generate_pixelmix_font.py по отдельности каталог не трогают (см. их
докстринги), им можно пользоваться для быстрой правки одного семейства, но
каталог после этого стоит дособрать отсюда.

Запуск (на компьютере): python3 generate_all_fonts.py

default_10 (растеризован с самой платы, см. generate_default_font.py) сюда
не входит — этому скрипту не нужна подключённая плата, а generate_default_
font.py, наоборот, сам пересобирает ПОЛНЫЙ каталог (включая эти три
семейства) после себя, раз ему для default_10 плата всё равно нужна.
"""

import font_render_lib as lib
import generate_orbitron_font as orbitron
import generate_pixelmix_font as pixelmix
import generate_verdana_font as verdana

families = {}
families[orbitron.NAME_PREFIX] = lib.render_family(
    orbitron.FONT_PATH, orbitron.OUT_DIR, orbitron.NAME_PREFIX, orbitron.SIZES, orbitron.CHARSET, orbitron.SPACING
)
families[verdana.NAME_PREFIX] = lib.render_family(
    verdana.FONT_PATH, verdana.OUT_DIR, verdana.NAME_PREFIX, verdana.SIZES, verdana.CHARSET, verdana.SPACING
)
families[pixelmix.NAME_PREFIX] = lib.render_family(
    pixelmix.FONT_PATH, pixelmix.OUT_DIR, pixelmix.NAME_PREFIX, pixelmix.SIZES, pixelmix.CHARSET, pixelmix.SPACING
)

lib.write_catalog(orbitron.OUT_DIR, families)
