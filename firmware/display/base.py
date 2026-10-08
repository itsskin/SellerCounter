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

    # Частичное обновление (см. epd1in54.py/epd4in2.py): меняются только
    # изменившиеся пиксели, без мигания всего экрана. У симулятора смысла не
    # имеет, но атрибут общий, чтобы main.py/web_server.py не проверяли тип.
    partial_update = False

    def set_partial(self, enabled):
        self.partial_update = bool(enabled)

    # Длительность и вид последнего show() — для веб-интерфейса (/api/state),
    # чтобы можно было сверить скорость обновления без секундомера.
    last_show_ms = None
    last_show_kind = None

    def _inverted_buffer(self):
        """Буфер с инвертированными битами (то, что ждёт RAM панели). Через
        большое целое число — в C, раз в ~100 быстрее, чем побайтовый цикл на
        MicroPython (для 400x300 это были бы сотни мс на каждый кадр)."""
        buf = self.buffer
        n = len(buf)
        v = int.from_bytes(buf, "big") ^ ((1 << (8 * n)) - 1)
        return v.to_bytes(n, "big")

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
