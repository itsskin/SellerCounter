"""Перегенерирует ВСЕ семейства шрифтов (Orbitron, Verdana) и общий каталог
display/fonts/available_sizes.txt одним запуском. Предпочтительный способ
обновить шрифты — generate_orbitron_font.py/generate_verdana_font.py по
отдельности каталог не трогают (см. их докстринги), им можно пользоваться
для быстрой правки одного семейства, но каталог после этого стоит
дособрать отсюда.

Запуск (на компьютере): python3 generate_all_fonts.py
"""

import font_render_lib as lib
import generate_orbitron_font as orbitron
import generate_verdana_font as verdana

families = {}
families[orbitron.NAME_PREFIX] = lib.render_family(
    orbitron.FONT_PATH, orbitron.OUT_DIR, orbitron.NAME_PREFIX, orbitron.SIZES, orbitron.CHARSET, orbitron.SPACING
)
families[verdana.NAME_PREFIX] = lib.render_family(
    verdana.FONT_PATH, verdana.OUT_DIR, verdana.NAME_PREFIX, verdana.SIZES, verdana.CHARSET, verdana.SPACING
)

lib.write_catalog(orbitron.OUT_DIR, families)
