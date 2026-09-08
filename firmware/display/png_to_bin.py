# Мини-декодер PNG прямо на устройстве — конвертирует PNG в 1bpp
# MONO_HLSB-совместимые байты (bit=1 -> тёмный пиксель), без PIL/freetype
# (их на MicroPython нет). Раньше конвертация делалась офлайн на компьютере
# (см. assets/convert_bg_200x200.py) — теперь можно просто закинуть .png в
# display/assets/ на самой плате, см. check_new_background() в
# layout_200x200.py.
#
# Поддержано: PNG без интерлейса (Adam7 не реализован — большинство
# редакторов по умолчанию сохраняют без него), 8 бит/канал, color type
# 0 (grayscale), 2 (RGB), 3 (palette + опционально tRNS), 4 (grayscale+alpha),
# 6 (RGBA). Распаковка zlib — через встроенный модуль `deflate`
# (MICROPY_PY_DEFLATE, есть в стандартных сборках ESP32 из последних лет).
#
# Не пытается быть универсальным PNG-декодером — ровно то, что нужно для
# простых чёрно-белых макетов экрана.

import io

try:
    import deflate
except ImportError:
    deflate = None

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def decode_to_1bpp(path, threshold=128):
    """Возвращает (width, height, bytearray) — 1bpp построчно, MSB первый,
    как ожидает framebuf.MONO_HLSB. Бросает ValueError с понятным текстом,
    если PNG не поддержан (интерлейс, экзотичный формат и т.п.)."""
    if deflate is None:
        raise ValueError(
            "в этой прошивке нет модуля 'deflate' — не могу распаковать PNG "
            "(нужна сборка MicroPython с MICROPY_PY_DEFLATE)"
        )

    with open(path, "rb") as f:
        data = f.read()

    if data[:8] != _SIGNATURE:
        raise ValueError("не похоже на PNG (нет сигнатуры)")

    width = height = bit_depth = color_type = interlace = None
    palette = None
    trns = None
    idat = bytearray()

    pos = 8
    n = len(data)
    while pos + 8 <= n:
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 8 + length + 4  # + 4 байта CRC, не проверяем

        if ctype == b"IHDR":
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = chunk[8]
            color_type = chunk[9]
            interlace = chunk[12]
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break

    if width is None:
        raise ValueError("не нашёл чанк IHDR")
    if interlace:
        raise ValueError("interlaced PNG не поддержан — пересохрани картинку без интерлейса")
    if bit_depth != 8:
        raise ValueError("поддержаны только 8 бит/канал, тут %d" % bit_depth)

    channels = _CHANNELS_BY_COLOR_TYPE.get(color_type)
    if channels is None:
        raise ValueError("неизвестный color type %d" % color_type)

    raw = deflate.DeflateIO(io.BytesIO(bytes(idat)), deflate.ZLIB).read()

    row_bytes = width * channels
    out_row_bytes = (width + 7) // 8
    out = bytearray(out_row_bytes * height)

    prev_row = bytearray(row_bytes)
    idx = 0
    for y in range(height):
        filter_type = raw[idx]
        idx += 1
        row = bytearray(raw[idx : idx + row_bytes])
        idx += row_bytes
        _unfilter(row, prev_row, filter_type, channels)
        _write_row_1bpp(out, y * out_row_bytes, row, width, channels, color_type, palette, trns, threshold)
        prev_row = row

    return width, height, out


def _unfilter(row, prev_row, ftype, channels):
    n = len(row)
    if ftype == 0:
        return
    if ftype == 1:  # Sub
        for i in range(channels, n):
            row[i] = (row[i] + row[i - channels]) & 0xFF
    elif ftype == 2:  # Up
        for i in range(n):
            row[i] = (row[i] + prev_row[i]) & 0xFF
    elif ftype == 3:  # Average
        for i in range(n):
            a = row[i - channels] if i >= channels else 0
            row[i] = (row[i] + (a + prev_row[i]) // 2) & 0xFF
    elif ftype == 4:  # Paeth
        for i in range(n):
            a = row[i - channels] if i >= channels else 0
            c = prev_row[i - channels] if i >= channels else 0
            row[i] = (row[i] + _paeth(a, prev_row[i], c)) & 0xFF
    else:
        raise ValueError("неизвестный filter type %d" % ftype)


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _write_row_1bpp(out, out_offset, row, width, channels, color_type, palette, trns, threshold):
    for x in range(width):
        o = x * channels
        if color_type == 0:  # grayscale
            gray = row[o]
        elif color_type == 4:  # grayscale + alpha
            gray, a = row[o], row[o + 1]
            if a < 255:
                gray = (gray * a + 255 * (255 - a)) // 255
        elif color_type == 2:  # RGB
            gray = (row[o] * 299 + row[o + 1] * 587 + row[o + 2] * 114) // 1000
        elif color_type == 6:  # RGBA
            r, g, b, a = row[o], row[o + 1], row[o + 2], row[o + 3]
            if a < 255:
                r = (r * a + 255 * (255 - a)) // 255
                g = (g * a + 255 * (255 - a)) // 255
                b = (b * a + 255 * (255 - a)) // 255
            gray = (r * 299 + g * 587 + b * 114) // 1000
        else:  # 3 -- palette
            pi = row[o]
            r = palette[pi * 3]
            g = palette[pi * 3 + 1]
            b = palette[pi * 3 + 2]
            a = trns[pi] if trns and pi < len(trns) else 255
            if a < 255:
                r = (r * a + 255 * (255 - a)) // 255
                g = (g * a + 255 * (255 - a)) // 255
                b = (b * a + 255 * (255 - a)) // 255
            gray = (r * 299 + g * 587 + b * 114) // 1000

        if gray < threshold:
            out[out_offset + x // 8] |= 1 << (7 - (x % 8))
