# Минимальный генератор QR-кода для платы: ТОЛЬКО версия 2 (25x25 модулей),
# коррекция ошибок M, байтовый режим. Вмещает до 26 байт — хватает на
# "http://255.255.255.255/" (23 байта). Без внешних библиотек, только то, что есть
# в MicroPython. Одинаковый размер для любого IP — раскладка экрана не плавает.
#
# Проверяется на компьютере против эталонной библиотеки segno (tools/test_qr.py):
# матрицы совпадают модуль в модуль для каждой из 8 масок.
#
# Использование:
#   import qr
#   mods = qr.make("http://192.168.0.111/")      # bytearray 25*25, 1 = тёмный модуль
#   qr.draw(fb, mods, x0, y0, scale)              # рисует тёмные модули на FrameBuffer

SIZE = 25
_DATA_CW = 28   # слов данных для v2-M
_EC_CW = 16     # слов коррекции для v2-M
MAX_BYTES = 26

_EXP = None
_LOG = None


def _init_gf():
    global _EXP, _LOG
    if _EXP is not None:
        return
    exp = bytearray(512)
    log = bytearray(256)
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    _EXP = exp
    _LOG = log


def _rs_generator(degree):
    gen = [1]
    for i in range(degree):
        nxt = [0] * (len(gen) + 1)
        for j in range(len(gen)):
            c = gen[j]
            nxt[j] ^= c
            if c:
                nxt[j + 1] ^= _EXP[_LOG[c] + i]
        gen = nxt
    return gen


def _rs_remainder(data, degree):
    gen = _rs_generator(degree)
    res = [0] * degree
    for b in data:
        factor = b ^ res[0]
        res = res[1:] + [0]
        if factor:
            lf = _LOG[factor]
            for i in range(degree):
                c = gen[i + 1]
                if c:
                    res[i] ^= _EXP[lf + _LOG[c]]
    return res


def _codewords(raw):
    """Данные + коррекция (44 слова, один блок)."""
    if len(raw) > MAX_BYTES:
        raise ValueError("text too long for QR v2-M")
    bits = []

    def put(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    put(4, 4)               # режим: байты
    put(len(raw), 8)        # длина (для версий 1..9 — 8 бит)
    for b in raw:
        put(b, 8)
    cap = _DATA_CW * 8
    put(0, min(4, cap - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    data = bytearray(_DATA_CW)
    for i in range(cap):
        if bits[i]:
            data[i >> 3] |= 0x80 >> (i & 7)
    ec = _rs_remainder(data, _EC_CW)
    return bytes(data) + bytes(ec)


def _set(m, fn, x, y, dark):
    m[y * SIZE + x] = 1 if dark else 0
    fn[y * SIZE + x] = 1


def _draw_format(m, fn, mask):
    data = mask  # уровень M кодируется как 00, поэтому (00 << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = ((data << 10) | rem) ^ 0x5412

    def bit(i):
        return (bits >> i) & 1

    for i in range(0, 6):
        _set(m, fn, 8, i, bit(i))
    _set(m, fn, 8, 7, bit(6))
    _set(m, fn, 8, 8, bit(7))
    _set(m, fn, 7, 8, bit(8))
    for i in range(9, 15):
        _set(m, fn, 14 - i, 8, bit(i))
    for i in range(0, 8):
        _set(m, fn, SIZE - 1 - i, 8, bit(i))
    for i in range(8, 15):
        _set(m, fn, 8, SIZE - 15 + i, bit(i))
    _set(m, fn, 8, SIZE - 8, 1)   # «тёмный модуль» — всегда 1


def _draw_function(m, fn):
    for i in range(SIZE):
        _set(m, fn, 6, i, i % 2 == 0)
        _set(m, fn, i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (SIZE - 4, 3), (3, SIZE - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x = cx + dx
                y = cy + dy
                if 0 <= x < SIZE and 0 <= y < SIZE:
                    d = max(abs(dx), abs(dy))
                    _set(m, fn, x, y, d != 2 and d != 4)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            _set(m, fn, 18 + dx, 18 + dy, max(abs(dx), abs(dy)) != 1)
    _draw_format(m, fn, 0)   # только занять место, потом перерисуем с настоящей маской


def _place_data(m, fn, cw):
    total = len(cw) * 8
    i = 0
    right = SIZE - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(SIZE):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = SIZE - 1 - vert if upward else vert
                if not fn[y * SIZE + x] and i < total:
                    m[y * SIZE + x] = (cw[i >> 3] >> (7 - (i & 7))) & 1
                    i += 1
        right -= 2


def _apply_mask(m, fn, mask):
    for y in range(SIZE):
        for x in range(SIZE):
            if fn[y * SIZE + x]:
                continue
            if mask == 0:
                inv = (x + y) % 2 == 0
            elif mask == 1:
                inv = y % 2 == 0
            elif mask == 2:
                inv = x % 3 == 0
            elif mask == 3:
                inv = (x + y) % 3 == 0
            elif mask == 4:
                inv = (x // 3 + y // 2) % 2 == 0
            elif mask == 5:
                inv = x * y % 2 + x * y % 3 == 0
            elif mask == 6:
                inv = (x * y % 2 + x * y % 3) % 2 == 0
            else:
                inv = ((x + y) % 2 + x * y % 3) % 2 == 0
            if inv:
                m[y * SIZE + x] ^= 1


_PAT_A = (1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0)
_PAT_B = (0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1)


def _penalty(m):
    score = 0
    lines = []
    for y in range(SIZE):
        lines.append([m[y * SIZE + x] for x in range(SIZE)])
    for x in range(SIZE):
        lines.append([m[y * SIZE + x] for y in range(SIZE)])
    for ln in lines:
        run = 1
        for i in range(1, SIZE):
            if ln[i] == ln[i - 1]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
        for i in range(SIZE - 10):
            seg = tuple(ln[i:i + 11])
            if seg == _PAT_A or seg == _PAT_B:
                score += 40
    for y in range(SIZE - 1):
        for x in range(SIZE - 1):
            c = m[y * SIZE + x]
            if c == m[y * SIZE + x + 1] and c == m[(y + 1) * SIZE + x] and c == m[(y + 1) * SIZE + x + 1]:
                score += 3
    dark = sum(m)
    # steps — на сколько «шагов по 5%» доля тёмных отличается от 50%
    steps = (abs(dark * 100 - SIZE * SIZE * 50) + SIZE * SIZE * 5 - 1) // (SIZE * SIZE * 5) - 1
    if steps < 0:
        steps = 0
    score += steps * 10
    return score


def make(text, mask=None):
    """text (str) -> bytearray(25*25), 1 = тёмный модуль. mask=None — выбрать
    лучшую из 8 (по штрафам), иначе взять указанную (нужно для тестов)."""
    _init_gf()
    cw = _codewords(text.encode())
    base = bytearray(SIZE * SIZE)
    fn = bytearray(SIZE * SIZE)
    _draw_function(base, fn)
    _place_data(base, fn, cw)
    masks = range(8) if mask is None else (mask,)
    best = None
    best_score = None
    for k in masks:
        m = bytearray(base)
        _apply_mask(m, fn, k)
        _draw_format(m, bytearray(fn), k)
        if mask is not None:
            return m
        s = _penalty(m)
        if best is None or s < best_score:
            best = m
            best_score = s
    return best


def draw(fb, mods, x0, y0, scale, color=1):
    """Рисует тёмные модули на framebuf.FrameBuffer; светлые не трогает."""
    for y in range(SIZE):
        row = y * SIZE
        for x in range(SIZE):
            if mods[row + x]:
                fb.fill_rect(x0 + x * scale, y0 + y * scale, scale, scale, color)
