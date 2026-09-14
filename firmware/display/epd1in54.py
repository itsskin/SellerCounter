# Драйвер экрана 1.54" 200x200 (SPI, контроллер SSD1681). HW-подтверждён на
# двух разных физических панелях без единой правки кода — команды/протокол
# завязаны на чип, не на конкретную плату:
#  - Waveshare 1.54" e-Paper B (трёхцветная, через переходник 3-wire→4-wire
#    с отдельным PWR-пином) — исходное железо, на котором писался драйвер.
#  - WeAct Studio 1.54" Epaper Module (обычная ч/б, подключается напрямую,
#    без переходника и без отдельного PWR) — то, что физически подключено
#    сейчас (см. docs/HARDWARE.md).
#
# Трёхцветность Waveshare (суффикс "B") тут ни при чём для логики — у чипа
# SSD1681 в любом случае две отдельные RAM: BW (команда 0x24, наша картинка)
# и RED (команда 0x26). Мы цвет не используем, но RED RAM всё равно нужно
# явно обнулять на каждом обновлении — на Waveshare без этого лез мусор
# случайным красным шумом по всему полю (HW-подтверждено), на WeAct (там
# физически нет красных чернил) это просто безвредный no-op — команда чипу
# уходит в любом случае, разницы для панели без красного слоя нет.
#
# Полярность бита в BW RAM подтверждена по даташиту (не на глаз): бит=1 —
# белый пиксель, бит=0 — чёрный. Инвертируем перед отправкой, чтобы
# совпадало с конвенцией DisplayDriver (color=1 -> чернила/чёрный).
#
# Команды и порядок инициализации сверены с реальным рабочим драйвером
# (Adafruit_CircuitPython_EPD, adafruit_epd/ssd1681.py, класс Adafruit_SSD1681)
# и с оригинальным даташитом SSD1681 (Solomon Systech, Rev 0.13) — не
# собраны наугад. HW-подтверждено на реальной плате.
#
# PWR (GPIO13): был нужен только у переходника Waveshare — отдельный пин,
# включающий бустер/источники напряжения для самой панели (то, что реально
# двигает частицы e-paper); без него SPI мог отрабатывать "успешно", а на
# экране физически ничего не менялось. У WeAct-модуля такого отдельного
# пина нет (просто VCC/GND) — вся PWR-логика отсюда убрана, GPIO13 теперь
# свободен (см. docs/HARDWARE.md — при возврате на Waveshare её придётся
# вернуть).
#
# 3-wire / 4-wire SPI: и у переходника Waveshare, и у самого модуля WeAct
# есть переключатель/перемычка на это — должна стоять в положении 4-wire
# SPI. Весь код здесь рассчитан на 4-wire (отдельный пин DC), 3-wire
# (9-битный SPI без отдельного DC) этот драйвер не поддерживает.
#  - "display config" (маркировка вроде 3R / 0.47R) — это подбор резистора
#    под конкретную ревизию панели; не под все панели описание есть в
#    документации к модулю, поэтому наугад не рекомендуем — оставить как
#    было выставлено с завода и смотреть на качество картинки, либо свериться
#    с маркировкой на самой панели/шлейфе.

import time
from machine import Pin, SPI

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

from display.base import DisplayDriver

# SPI(2, ...) валит плату в хардварный ребут по watchdog (TG1WDT_SYS_RST) —
# похоже, конфликтует с Octal-PSRAM, которая на этой сборке сама использует
# SPI-шину внутри. SPI(1, ...) на тех же пинах работает нормально —
# HW-подтверждено.
PINS = {
    "sck": 12,
    "mosi": 11,
    "cs": 10,
    "dc": 9,
    "rst": 46,
    "busy": 3,
}

CMD_SW_RESET = 0x12
CMD_DRIVER_CONTROL = 0x01
CMD_DATA_MODE = 0x11
CMD_SET_RAMXPOS = 0x44
CMD_SET_RAMYPOS = 0x45
CMD_SET_RAMXCOUNT = 0x4E
CMD_SET_RAMYCOUNT = 0x4F
CMD_WRITE_BORDER = 0x3C
CMD_TEMP_CONTROL = 0x18
CMD_TEMP_WRITE = 0x1A  # Write to Temperature Register — см. show()
CMD_WRITE_BWRAM = 0x24
CMD_WRITE_REDRAM = 0x26
CMD_DISP_CTRL2 = 0x22
CMD_MASTER_ACTIVATE = 0x20
CMD_DEEP_SLEEP = 0x10

_CMD_NAMES = {
    CMD_SW_RESET: "SW_RESET",
    CMD_DRIVER_CONTROL: "DRIVER_CONTROL",
    CMD_DATA_MODE: "DATA_MODE",
    CMD_SET_RAMXPOS: "SET_RAMXPOS",
    CMD_SET_RAMYPOS: "SET_RAMYPOS",
    CMD_SET_RAMXCOUNT: "SET_RAMXCOUNT",
    CMD_SET_RAMYCOUNT: "SET_RAMYCOUNT",
    CMD_WRITE_BORDER: "WRITE_BORDER",
    CMD_TEMP_CONTROL: "TEMP_CONTROL",
    CMD_TEMP_WRITE: "TEMP_WRITE",
    CMD_WRITE_BWRAM: "WRITE_BWRAM",
    CMD_WRITE_REDRAM: "WRITE_REDRAM",
    CMD_DISP_CTRL2: "DISP_CTRL2",
    CMD_MASTER_ACTIVATE: "MASTER_ACTIVATE",
    CMD_DEEP_SLEEP: "DEEP_SLEEP",
}


class Epd1in54Display(DisplayDriver):
    width = 200
    height = 200
    debug = False  # печатать каждый шаг инициализации/обновления в терминал

    # Partial refresh (0x22=0xFC) пробовали на близком чипе (epd4in2.py,
    # SSD1683) — HW-подтверждено, что панель физически не до конца
    # "перещёлкивает" пиксели даже с частым full-циклом, призраки видны
    # сразу. Full refresh не мигает и достаточно быстрый сам по себе, так
    # что partial не даёт выигрыша, который стоил бы такой цены — оставлен
    # только full (0x22=0xF7).

    # Каждое N-ное обновление — честный full refresh (см. show()), не
    # "fast full" — чистит накопившиеся от температурного трюка призраки.
    FULL_REFRESH_EVERY = 10

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
        # См. FULL_REFRESH_EVERY выше и show() — стартует с 0, так что
        # первый show() после включения платы тоже честный (не "fast full").
        self._update_count = 0
        self._log("init: pins ok")

    def _log(self, msg):
        if self.debug:
            print("[epd1in54] " + msg)

    def _reset(self):
        self._log("hardware reset (RST низкий/высокий)")
        self._rst(0)
        time.sleep_ms(20)
        self._rst(1)
        time.sleep_ms(20)

    async def _wait_busy(self, timeout_ms=25000):
        # HW-подтверждено: полное обновление у этой панели укладывается не
        # в 8 сек (было мало) — берём с запасом, полный refresh мелких
        # e-paper панелей обычно 10-20 сек.
        #
        # await asyncio.sleep_ms(10), а не блокирующий time.sleep_ms(10) —
        # принципиально важно: это единственное место, где реально можно
        # отдать управление обратно event loop на эти ~20 секунд. Без этого
        # MicroPython asyncio (однопоточный, кооперативный) не может
        # обслуживать вообще ничего другое — например веб-сервер — пока
        # экран физически обновляется (HW-подтверждено: именно это было
        # причиной, почему веб-страница не отвечала после старта платы).
        start = time.ticks_ms()
        deadline = time.ticks_add(start, timeout_ms)
        last_log = start
        if self._busy.value() == 0:
            self._log("busy: уже свободен (BUSY=0 сразу)")
            return
        self._log("busy: жду (BUSY=1)...")
        while self._busy.value() == 1:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_log) >= 1000:
                self._log("busy: всё ещё занят, прошло %d мс" % time.ticks_diff(now, start))
                last_log = now
            if time.ticks_diff(deadline, now) <= 0:
                self._log("busy: ТАЙМАУТ — панель не отпустила BUSY за %d мс" % timeout_ms)
                raise RuntimeError("EPD busy timeout")
            await asyncio.sleep_ms(10)
        self._log("busy: освободился за %d мс" % time.ticks_diff(time.ticks_ms(), start))

    def _cmd(self, cmd, data=b""):
        name = _CMD_NAMES.get(cmd, hex(cmd))
        self._log(
            "cmd %s (0x%02X)%s"
            % (name, cmd, (" + %d байт данных" % len(data)) if data else "")
        )
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
        self._log("=== _hw_init() start ===")
        self._reset()
        await self._wait_busy()
        self._cmd(CMD_SW_RESET)
        await self._wait_busy()

        # width==height==200 у этой панели, так что неоднозначность
        # "ширина или высота" в DRIVER_CONTROL (в референсе используется
        # self._width) тут не имеет значения — оба равны 199.
        self._cmd(
            CMD_DRIVER_CONTROL,
            bytes([(self.height - 1) & 0xFF, (self.height - 1) >> 8, 0x00]),
        )
        self._cmd(CMD_DATA_MODE, bytes([0x03]))  # X-increment, Y-increment
        self._cmd(CMD_SET_RAMXPOS, bytes([0x00, self.height // 8 - 1]))
        self._cmd(
            CMD_SET_RAMYPOS,
            bytes([0x00, 0x00, (self.height - 1) & 0xFF, (self.height - 1) >> 8]),
        )
        self._cmd(CMD_WRITE_BORDER, bytes([0x05]))
        self._cmd(CMD_TEMP_CONTROL, bytes([0x80]))
        await self._wait_busy()

        self._hw_ready = True
        self._log("=== _hw_init() done ===")

    def _reset_ram_address(self):
        self._cmd(CMD_SET_RAMXCOUNT, bytes([0x00]))
        self._cmd(CMD_SET_RAMYCOUNT, bytes([0x00, 0x00]))

    async def show(self):
        self._log("=== show() start (buffer=%d байт) ===" % len(self.buffer))
        if not self._hw_ready:
            await self._hw_init()

        self._reset_ram_address()
        # HW-подтверждено: у этой панели бит=1 в BW RAM физически "белый",
        # а не "чёрный" — переворачиваем перед отправкой, чтобы совпадало
        # с конвенцией DisplayDriver (color=1 -> чернила/чёрный).
        inverted = bytes(b ^ 0xFF for b in self.buffer)
        self._cmd(CMD_WRITE_BWRAM, inverted)

        # Трёхцветная панель (B/W/R) — у RED RAM свой указатель адреса,
        # сбрасываем отдельно и пишем нули (красного нигде нет). Без этого
        # там остаётся мусор с включения платы и лезет случайным красным
        # шумом по всему полю (HW-подтверждено).
        self._reset_ram_address()
        self._cmd(CMD_WRITE_REDRAM, bytes(len(self.buffer)))

        # "Fast full update" — полноценный full refresh с укороченной
        # waveform-LUT: панели подсовывается завышенная температура через
        # Write to Temperature Register (0x1A), из-за чего она сама выбирает
        # более быстрый LUT под "тёплые" условия (0x22=0xD7 вместо 0xF7).
        # Пиксели по-прежнему полностью перещёлкиваются — это НЕ partial
        # (тот не годится, см. epd4in2.py). Значение 0x64 сверено с
        # референс-драйвером именно этой панели: GxEPD2, ZinggJM/GxEPD2,
        # src/gdey/GxEPD2_154_GDEY0154D67.cpp, ветка useFastFullUpdate в
        # _Update_Full().
        #
        # По HW-наблюдению этот трюк при частом повторении подряд оставляет
        # лёгкие призраки предыдущих кадров, несмотря на "полное"
        # перещёлкивание пикселей на бумаге. Раз в FULL_REFRESH_EVERY
        # обновлений (и первым делом после включения — self._update_count
        # стартует с 0 в __init__) пропускаем температурный трюк и
        # используем настоящий медленный LUT (0x22=0xF7), который их убирает.
        self._update_count += 1
        full = self._update_count == 1 or self._update_count % self.FULL_REFRESH_EVERY == 0
        if not full:
            self._cmd(CMD_TEMP_WRITE, bytes([0x64]))
        self._cmd(CMD_DISP_CTRL2, bytes([0xF7 if full else 0xD7]))
        self._cmd(CMD_MASTER_ACTIVATE)
        await self._wait_busy()
        self._log("=== show() done ===" + (" (full refresh)" if full else ""))
