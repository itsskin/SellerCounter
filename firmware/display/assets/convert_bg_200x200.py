"""Конвертирует seller_m8_v1.1_200x200.png (готовый макет от пользователя,
с пустым местом под выручку/заказы) в bg_200x200.bin — статичный фон для
layout_200x200.py. Картинка не редактируется, только пакуется в 1bpp
MONO_HLSB как есть (белый фон -> 0, чёрные пиксели макета -> 1).

Запуск (один раз, на компьютере, не на плате):
    python3 convert_bg_200x200.py

Источник картинки — ../../../seller_m8_v1.1_200x200.png (корень проекта).
"""

import os

from PIL import Image

W = H = 200
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
SRC = os.path.join(PROJECT_ROOT, "seller_m8_v1.1_200x200 (2).png")
OUT_BIN = os.path.join(os.path.dirname(__file__), "bg_200x200.bin")
# ВАЖНО: превью нарочно не кладём в firmware/display/assets/ — эта папка
# целиком заливается на плату, а с недавних пор всё, что там лежит с
# расширением .png, прошивка пытается превратить в новый фон экрана (см.
# check_new_background() в layout_200x200.py). Превью в 1-битном режиме
# PIL ей не по зубам (нужно 8 бит/канал) — теряется время на ошибку в
# логе на ровном месте. Кладём превью в корень проекта, вне заливаемого дерева.
OUT_PREVIEW = os.path.join(PROJECT_ROOT, "bg_200x200_preview.png")

im = Image.open(SRC).convert("RGBA")
assert im.size == (W, H), "ожидал 200x200, получил %r" % (im.size,)

# Композитим на белый фон (на случай прозрачности) и переводим в градации
# серого, затем в ч/б по порогу — макет и так практически чисто чёрно-белый.
bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
comp = Image.alpha_composite(bg, im).convert("L")

row_bytes = (W + 7) // 8
buf = bytearray(row_bytes * H)
px = comp.load()
THRESHOLD = 128
for y in range(H):
    for x in range(W):
        if px[x, y] < THRESHOLD:  # тёмный пиксель исходной картинки
            idx = y * row_bytes + x // 8
            bit = 7 - (x % 8)
            buf[idx] |= 1 << bit

with open(OUT_BIN, "wb") as f:
    f.write(bytes(buf))

# Превью для проверки глазами, что бит-паковка не исказила картинку.
preview = Image.new("1", (W, H), 1)
ppx = preview.load()
for y in range(H):
    for x in range(W):
        idx = y * row_bytes + x // 8
        bit = 7 - (x % 8)
        if buf[idx] & (1 << bit):
            ppx[x, y] = 0
preview.save(OUT_PREVIEW)

print("bg_200x200.bin:", len(buf), "байт; превью:", OUT_PREVIEW)
