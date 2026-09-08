# Драйвер WeAct 4.2" e-paper (400x300, SPI, контроллер SSD1683 — GDEY042T81,
# ч/б, без цвета). HW пока не тестировался на этой конкретной панели, но
# команды/последовательность не собраны наугад — сверены с рабочим
# референс-драйвером (GxEPD2, ZinggJM/GxEPD2, src/gdey/GxEPD2_420_GDEY042T81.cpp)
# и с уже HW-подтверждённым epd1in54.py (SSD1681 — очень близкий протокол,
# та же "семья" SSD16xx). Отличия от SSD1681 (1.54"), которые тут важны:
#  - Border Waveform Control (0x3C) с данными 0x01 — у SSD1681 было 0x05,
#    у SSD1683 согласно референсу нужно именно 0x01.
#  - Перед каждым Master Activate (0x20) обязателен Display Update Control 1
#    (0x21) с данными 0x40, 0x00 — у SSD1681 этой команды не было вообще;
#    без неё, по референсу, панель либо не обновляется, либо обновляется
#    неправильным режимом.
#  - Окно RAM (0x44/0x45/0x4E/0x4F) должно переустанавливаться перед КАЖДОЙ
#    записью в RAM, не только один раз при инициализации — иначе указатель
#    адреса RAM останется там, где его оставила предыдущая запись, и вторая
#    перерисовка запишет данные не с начала экрана.
#
# Как проверить/поправить на реальном железе:
#  1) сверить маркировку чипа на плате модуля с SSD1683 (обычно наклейка/
#     маркировка рядом с шлейфом);
#  2) если картинка выйдет инвертированной (чёрное/белое перепутаны) —
#     см. инверсию бита в show() ниже, как и на epd1in54.py;
#  3) пины в PINS ниже совпадают с epd1in54.py (осознанно, см.
#     docs/HARDWARE.md — чтобы физически переключать экраны без перепайки).

import time
from machine import Pin, SPI

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

from display.base import DisplayDriver

# SPI(2, ...) на этой плате (Octal-PSRAM) валит хардварный ребут по
# watchdog — HW-подтверждено на epd1in54 с теми же пинами. SPI(1, ...)
# работает нормально, используем его и здесь на всякий случай.
PINS = {
    "sck": 12,
    "mosi": 11,
    "cs": 10,
    "dc": 9,
    "rst": 46,
    "busy": 3,
}

CMD_SW_RESET = 0x12
CMD_DRIVER_OUTPUT_CTRL = 0x01
CMD_DATA_ENTRY_MODE = 0x11
CMD_SET_RAM_X = 0x44
CMD_SET_RAM_Y = 0x45
CMD_SET_RAM_X_COUNTER = 0x4E
CMD_SET_RAM_Y_COUNTER = 0x4F
CMD_BORDER_WAVEFORM = 0x3C
CMD_TEMP_CONTROL = 0x18
CMD_TEMP_WRITE = 0x1A  # Write to Temperature Register — см. show()
CMD_WRITE_RAM_BW = 0x24
CMD_DISPLAY_UPDATE_CTRL1 = 0x21
CMD_DISPLAY_UPDATE_CTRL2 = 0x22
CMD_MASTER_ACTIVATE = 0x20
CMD_DEEP_SLEEP = 0x10


class Epd4in2Display(DisplayDriver):
    width = 400
    height = 300

    # Partial refresh (Display Update Control 2 = 0xFC) пробовали — HW-
    # подтверждено именно на этой панели, что она физически не до конца
    # "перещёлкивает" пиксели даже с частым full-циклом (раз в 3 кадра):
    # призраки предыдущих кадров остаются видны сразу. Full refresh тут и
    # так быстрый (~3.3с, HW-замерено) и не мигает, так что partial не даёт
    # выигрыша, который стоил бы такой цены — оставлен только full.

    def __init__(self):
        super().__init__()
        self._spi = SPI(
            1,
            baudrate=4_000_000,
            polarity=0,
            phase=0,
            sck=Pin(PINS["sck"]),
            mosi=Pin(PINS["mosi"]),
        )
        self._cs = Pin(PINS["cs"], Pin.OUT, value=1)
        self._dc = Pin(PINS["dc"], Pin.OUT, value=0)
        self._rst = Pin(PINS["rst"], Pin.OUT, value=1)
        self._busy = Pin(PINS["busy"], Pin.IN)
        self._hw_ready = False

    def _reset(self):
        self._rst(0)
        time.sleep_ms(20)
        self._rst(1)
        time.sleep_ms(20)

    async def _wait_busy(self, timeout_ms=25000):
        # HW-подтверждено на epd1in54: 8 сек мало для полного refresh
        # e-paper, берём с запасом (см. epd1in54.py). await asyncio.sleep_ms
        # вместо time.sleep_ms — чтобы на время refresh (~20с) event loop
        # мог обслуживать веб-сервер, а не блокироваться целиком (см.
        # подробное объяснение в epd1in54.py._wait_busy).
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while self._busy.value() == 1:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise RuntimeError("EPD busy timeout")
            await asyncio.sleep_ms(10)

    def _cmd(self, cmd, data=b""):
        self._dc(0)
        self._cs(0)
        self._spi.write(bytes([cmd]))
        self._cs(1)
        if data:
            self._dc(1)
            self._cs(0)
            self._spi.write(data)
            self._cs(1)

    async def _hw_init(self):
        self._reset()
        await self._wait_busy()
        self._cmd(CMD_SW_RESET)
        await self._wait_busy()
        self._cmd(
            CMD_DRIVER_OUTPUT_CTRL,
            bytes([(self.height - 1) & 0xFF, ((self.height - 1) >> 8) & 0xFF, 0x00]),
        )
        self._cmd(CMD_BORDER_WAVEFORM, bytes([0x01]))
        self._cmd(CMD_TEMP_CONTROL, bytes([0x80]))
        self._cmd(CMD_DATA_ENTRY_MODE, bytes([0x03]))
        self._hw_ready = True

    def _set_window(self, x0, y0, x1, y1):
        # Переустанавливаем окно/адрес RAM перед каждой записью (вызывается
        # из show(), не только из _hw_init) — иначе указатель адреса
        # останется там, где его оставила предыдущая запись, и следующая
        # перерисовка попадёт не в начало экрана.
        self._cmd(CMD_SET_RAM_X, bytes([x0 // 8, x1 // 8]))
        self._cmd(CMD_SET_RAM_Y, bytes([y0 & 0xFF, y0 >> 8, y1 & 0xFF, y1 >> 8]))
        self._cmd(CMD_SET_RAM_X_COUNTER, bytes([x0 // 8]))
        self._cmd(CMD_SET_RAM_Y_COUNTER, bytes([y0 & 0xFF, y0 >> 8]))

    async def show(self):
        if not self._hw_ready:
            await self._hw_init()

        self._set_window(0, 0, self.width - 1, self.height - 1)
        # HW не подтверждено (панели пока не было в руках) — если картинка
        # выйдет инвертированной (чёрное/белое перепутаны), убрать эту
        # инверсию (как и на epd1in54.py, где она понадобилась по
        # даташиту SSD1681; SSD1683 — близкий протокол, но не факт что
        # идентичная полярность бита).
        inverted = bytes(b ^ 0xFF for b in self.buffer)
        self._cmd(CMD_WRITE_RAM_BW, inverted)
        self._cmd(CMD_DISPLAY_UPDATE_CTRL1, bytes([0x40, 0x00]))
        # "Fast full update" — НЕ partial (тот не годится, см. коммент у
        # класса выше), а полноценный full refresh, просто с укороченной
        # waveform-LUT: панели подсовывается завышенная температура через
        # Write to Temperature Register (0x1A), из-за чего она сама выбирает
        # более быстрый LUT под "тёплые" условия (0x22=0xD7 вместо 0xF7).
        # Пиксели по-прежнему полностью перещёлкиваются, в отличие от
        # partial — значение 0x6E сверено с референс-драйвером именно этой
        # панели: GxEPD2, ZinggJM/GxEPD2,
        # src/gdey/GxEPD2_420_GDEY042T81.cpp, ветка _use_fast_update в
        # _Update_Full().
        self._cmd(CMD_TEMP_WRITE, bytes([0x6E]))
        self._cmd(CMD_DISPLAY_UPDATE_CTRL2, bytes([0xD7]))
        self._cmd(CMD_MASTER_ACTIVATE)
        await self._wait_busy()

    def sleep(self):
        self._cmd(CMD_DEEP_SLEEP, bytes([0x01]))
