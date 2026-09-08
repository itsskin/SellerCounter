# Программная замена экрана: реального WeAct 4.2" пока нет, поэтому кадр не
# выводится на SPI, а сохраняется как 1-битный BMP на флеш. Смотреть его
# можно через веб-интерфейс: GET /api/display/preview.bmp

from display.base import DisplayDriver

PREVIEW_PATH = "/display_last.bmp"


class SimDisplay(DisplayDriver):
    async def show(self):
        _write_bmp(self.buffer, self.width, self.height, PREVIEW_PATH)

    def sleep(self):
        pass


def to_bmp_bytes(buf, width, height):
    """Кодирует буфер (как есть, из любого DisplayDriver) в 1-битный BMP.
    Используется и для файла-превью (SimDisplay), и веб-сервером — чтобы
    отдавать live-превью текущего кадра даже когда активен реальный
    драйвер epd4in2 (у него на панели то же самое, что и в буфере)."""
    row_bytes_src = (width + 7) // 8
    row_bytes_dst = ((width + 31) // 32) * 4
    pad = bytes(row_bytes_dst - row_bytes_src)
    pixel_data_size = row_bytes_dst * height
    out = bytearray(_bmp_header(width, height, pixel_data_size))
    for row in range(height):
        start = row * row_bytes_src
        out += buf[start:start + row_bytes_src]
        if pad:
            out += pad
    return bytes(out)


def _write_bmp(buf, width, height, path):
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(to_bmp_bytes(buf, width, height))

    try:
        import os
        os.remove(path)
    except OSError:
        pass
    import os
    os.rename(tmp_path, path)


def _bmp_header(width, height, pixel_data_size):
    # BITMAPFILEHEADER (14) + BITMAPINFOHEADER (40) + палитра из 2 цветов (8)
    data_offset = 14 + 40 + 8
    file_size = data_offset + pixel_data_size

    h = bytearray()
    h += b"BM"
    h += file_size.to_bytes(4, "little")
    h += (0).to_bytes(4, "little")
    h += data_offset.to_bytes(4, "little")

    h += (40).to_bytes(4, "little")
    h += width.to_bytes(4, "little")
    # Отрицательная высота = хранение строк сверху вниз (как в нашем буфере),
    # без переворота при записи.
    h += ((-height) & 0xFFFFFFFF).to_bytes(4, "little")
    h += (1).to_bytes(2, "little")   # planes
    h += (1).to_bytes(2, "little")   # bitcount = 1bpp
    h += (0).to_bytes(4, "little")   # compression = BI_RGB
    h += pixel_data_size.to_bytes(4, "little")
    h += (2835).to_bytes(4, "little")  # ~72dpi
    h += (2835).to_bytes(4, "little")
    h += (2).to_bytes(4, "little")   # colors used
    h += (0).to_bytes(4, "little")   # important colors

    # Палитра: index0=белый (бит 0), index1=чёрный (бит 1) — совпадает с
    # конвенцией DisplayDriver (color=1 -> чернила).
    h += bytes([255, 255, 255, 0])
    h += bytes([0, 0, 0, 0])
    return h
