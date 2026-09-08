import framebuf


class DisplayDriver:
    """Общий интерфейс для реального e-paper и для симулятора.

    Буфер — 1bpp, framebuf.MONO_HLSB (по 8 пикселей на байт, MSB первый,
    построчно). Это же представление напрямую пишется на панель SSD16xx-типа
    и напрямую конвертируется в 1-битный BMP для превью без экрана.
    color=1 всегда означает "чернила"/чёрный, color=0 — фон/белый.

    width/height — атрибуты класса, задаются в подклассе под конкретную
    физическую панель (см. display/epd4in2.py — 400x300,
    display/epd1in54.py — 200x200). База по умолчанию — 400x300, этим
    пользуется display/framebuf_sim.py, когда конкретный размер не важен.
    """

    width = 400
    height = 300

    def __init__(self, width=None, height=None):
        # width/height можно переопределить на инстансе (используется
        # SimDisplay, чтобы симулировать превью под разные физические
        # панели одним и тем же классом) — по умолчанию берутся из класса.
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height
        row_bytes = (self.width + 7) // 8
        self.buffer = bytearray(row_bytes * self.height)
        self.fb = framebuf.FrameBuffer(self.buffer, self.width, self.height, framebuf.MONO_HLSB)

    async def show(self):
        """Вывести текущий self.buffer на устройство (панель или файл).

        async — потому что у реального e-paper это долгая (~20с) операция
        с busy-wait, и ей нужно уметь отдавать управление event loop
        (await asyncio.sleep_ms), чтобы не блокировать веб-сервер целиком.
        У SimDisplay тело быстрое и синхронное, но сигнатура та же — чтобы
        вызывающий код (main.py, stats_engine.py) не завязывался на то,
        какой конкретно драйвер активен."""
        raise NotImplementedError

    def sleep(self):
        """Перевести панель в режим низкого энергопотребления, если применимо."""
        pass
