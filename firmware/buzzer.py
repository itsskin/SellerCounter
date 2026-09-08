# Пассивный зуммер (сейчас модуль MH-FMD, со встроенным транзисторным
# усилителем; раньше был голый пьезоэлемент KY-006/HW-508 — см.
# docs/HARDWARE.md) — управляется через PWM, тон задаётся частотой сигнала
# (в отличие от активного зуммера, которому достаточно просто HIGH/LOW).
#
# Файлы уведомлений лежат в /notifications/ (см. web_server.py —
# GET /api/notifications, конфиг cfg["notification_sound"]):
#   .mid — играется через umidiparser (вендорено в firmware/lib/), честная
#          посинотная мелодия.
#   .wav — 8-битный несжатый PCM (моно) стримится напрямую в PWM-скважность.
#          Это "грубый" звук в духе PC speaker/1-bit DAC — сырые байты сэмплов
#          прямо превращаются в скважность на несущей ~32кГц. Никакого
#          декодирования на лету не происходит, потому что декодировать
#          НЕЧЕГО: WAV уже содержит голые сэмплы, в этом и смысл формата —
#          в отличие от MP3, который нужно сначала распаковать (для этого
#          нет вменяемого декодера под MicroPython, физически чип это не
#          потянет в реальном времени как чистый Python-код).
#   .mp3 — НЕ поддерживается напрямую (см. выше). Конвертировать в .wav
#          один раз на компьютере:
#          ffmpeg -i file.mp3 -ar 8000 -ac 1 -acodec pcm_u8 file.wav
#
# Зуммер физически может звучать только одной нотой за раз (это просто
# генератор прямоугольного сигнала на одном пине) — поэтому и MIDI, и WAV
# воспроизведение принципиально одноголосые/однопотоковые.
#
# Про громкость (cfg["buzzer"]["volume"], 0-500%): GPIO качается логическим
# уровнем ESP32 (3.3В), и тон/MIDI уже используют скважность 50% — это
# программный потолок, выше не прыгнуть отсюда. volume для тонов может
# только УМЕНЬШАТЬ громкость (0-100%). Реально громче — вопрос питания
# самого модуля (VCC), не кода: см. docs/HARDWARE.md про MH-FMD (там уже
# есть свой транзисторный усилитель, отдельная схема на 5В не нужна, но и
# VIN на этой плате не запитан — см. заметку там же).
# Для WAV реальный запас есть: если запись тихая, volume>100% цифрово
# усиливает сэмплы (с обрезанием/искажениями на больших значениях — в духе
# общей "грубости" этого звука).
#
# Про volume_curve (cfg["buzzer"]["volume_curve"]) — как именно volume%
# превращается в скважность PWM для тонов/MIDI (на WAV не влияет, там
# честное цифровое усиление сэмплов, см. play_wav). Дело в том, что
# скважность 50% (ровно volume=100% в "linear") — особая точка: в спектре
# идеального прямоугольного сигнала при ровно 50% скважности НЕТ чётных
# гармоник (гасятся математически, см. ряд Фурье), только нечётные. Чуть
# ниже 50% (т.е. volume<100%) чётные гармоники возвращаются — и если у
# конкретного пьезо/зуммера (MH-FMD) есть резонансный пик в верхнем
# диапазоне (обычно так и есть), высокая нота может звучать ГРОМЧЕ на,
# скажем, 80%, чем на 100%, просто потому что попавшая в резонанс вернувшаяся
# гармоника перекрывает падение амплитуды. То есть "чем больше volume, тем
# громче" тут не гарантировано физикой — три кривые ниже разные компромиссы:
#   linear    — как есть, duty = 32768 * pct. Просто, но на подходе к 100%
#               попадает в "провал" (чистый тон без чётных гармоник).
#   capped    — duty никогда не доходит до чистых 50% (потолок ~45%), так
#               что во всём диапазоне 0-100% чётные гармоники присутствуют
#               всегда — субъективная громкость растёт монотоннее, ценой
#               чуть более тихого максимума.
#   quadratic — duty = 32768 * pct^2 ("аудио"-кривая, как в audio-taper
#               потенциометрах) — человеческий слух воспринимает громкость
#               примерно логарифмически, линейная шкала на слух кажется
#               "переполненной" в начале хода; квадратичная делает шаги
#               более равномерными на слух. Не решает проблему резонанса
#               выше, просто более естественная кривая сама по себе.

import struct
import time
from machine import Pin, PWM

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import micropython
import umidiparser

MIN_PWM_FREQ = 20
MAX_PWM_FREQ = 20000
WAV_PWM_CARRIER_FREQ = 32000  # несущая частота PWM для потокового WAV

VOLUME_CURVES = ("linear", "capped", "quadratic")
DEFAULT_VOLUME_CURVE = "linear"


def _note_to_freq(note):
    return 440.0 * (2 ** ((note - 69) / 12.0))


class Buzzer:
    def __init__(self, pin_num, enabled=True, volume=100, volume_curve=DEFAULT_VOLUME_CURVE):
        self.pin_num = pin_num
        self.enabled = enabled
        self.volume = volume  # 0-500%, см. пояснение в шапке файла
        self.volume_curve = volume_curve if volume_curve in VOLUME_CURVES else DEFAULT_VOLUME_CURVE
        # ОДИН PWM-канал на весь срок жизни платы — раньше каждый
        # beep()/play_midi()/play_wav() создавал PWM(Pin(...)) заново и
        # deinit()'ил его в конце. HW-подтверждено: шипение через зуммер
        # слышно ПОСЛЕ каждого звука независимо от Wi-Fi и экрана (играли
        # мелодию через чистый serial-exec без единого пакета Wi-Fi рядом —
        # шипело всё равно) — то есть источник не внешняя наводка, а сам
        # цикл пересоздания/разрушения PWM-объекта на каждый звук. Держим
        # канал постоянно живым и просто глушим duty_u16(0) между звуками —
        # LEDC при duty=0 продолжает АКТИВНО держать пин на LOW (не
        # отпускает его), и никакой пересборки объекта/пина между звуками
        # больше нет.
        self._pwm = PWM(Pin(pin_num), freq=440)
        self._pwm.duty_u16(0)
        # play_midi() — асинхронный и отдаёт управление между нотами
        # (await), так что второй вызов play_notification() (реальная
        # продажа во время ручного "Тест", или два быстрых клика по "Тест"
        # подряд) может стартовать, пока первый ещё не доиграл — оба будут
        # дёргать freq()/duty_u16() ОДНОГО общего self._pwm вперемешку,
        # получится звуковая каша (HW-подтверждено на старой версии с
        # отдельными PWM-объектами на частых повторных нажатиях "Тест", тот
        # же риск остаётся и с общим каналом). Лок сериализует все вызовы
        # play_notification() — второй ждёт, пока первый доиграет, вместо
        # того чтобы стартовать поверх.
        self._playback_lock = asyncio.Lock()

    def _tone_duty(self):
        # 50% скважности (32768) — физический максимум громкости тона при
        # 3.3В. volume>100 для тонов эффекта не даёт, только 0-100 уменьшают.
        # Как именно pct переходит в duty — см. VOLUME_CURVES в шапке файла.
        pct = max(0, min(100, self.volume)) / 100.0
        if self.volume_curve == "quadratic":
            pct = pct * pct
        elif self.volume_curve == "capped":
            pct = pct * 0.9  # никогда не доходит до "провальных" чистых 50%
        return int(32768 * pct)

    def beep(self, freq=2000, duration_ms=150):
        if not self.enabled:
            return
        self._pwm.freq(freq)
        try:
            self._pwm.duty_u16(self._tone_duty())
            time.sleep_ms(duration_ms)
        finally:
            # HW-подтверждено: без try/finally прерывание ровно в этом окне
            # (например Ctrl-C от raw-REPL сессии во время диагностики)
            # оставляет PWM играть без остановки, пока плату не
            # перезагрузишь руками — duty_u16(0) тут обязателен.
            self._pwm.duty_u16(0)

    def startup_chime(self):
        for freq in (1500, 2000, 2600):
            self.beep(freq, 70)
            time.sleep_ms(30)

    async def play_notification(self, filename):
        """Играет файл уведомления — .mid или .wav, определяется по
        расширению. Используется и для реального алерта о продаже, и для
        кнопки "тест" в веб-интерфейсе.

        Под локом (см. _playback_lock в __init__) — если вызвали, пока уже
        что-то играет, просто дождётся своей очереди, а не полезет поверх."""
        if not self.enabled:
            return
        async with self._playback_lock:
            lower = filename.lower()
            if lower.endswith(".mid") or lower.endswith(".midi"):
                await self.play_midi(filename)
            elif lower.endswith(".wav"):
                self.play_wav(filename)
            else:
                print("buzzer: unsupported notification file %r (нужен .mid или .wav)" % filename)

    async def play_midi(self, filename, transpose=0):
        """Асинхронно проигрывает MIDI-файл — не блокирует остальные
        асинхронные задачи (веб-сервер, опрос маркетплейсов) между нотами.
        Если ноты в файле накладываются — играем как монофонический
        синтезатор: стек зажатых нот, звучит верхушка стека."""
        if not self.enabled:
            return

        pwm = self._pwm
        pwm.duty_u16(0)
        held_notes = []

        def note_on(note):
            held_notes.append(note)
            freq = int(round(_note_to_freq(note + transpose)))
            freq = max(MIN_PWM_FREQ, min(freq, MAX_PWM_FREQ))
            pwm.freq(freq)
            pwm.duty_u16(self._tone_duty())

        def note_off(note):
            if note in held_notes:
                held_notes.remove(note)
            if held_notes:
                freq = int(round(_note_to_freq(held_notes[-1] + transpose)))
                pwm.freq(max(MIN_PWM_FREQ, min(freq, MAX_PWM_FREQ)))
                pwm.duty_u16(self._tone_duty())
            else:
                pwm.duty_u16(0)

        try:
            midi = umidiparser.MidiFile(filename)
            async for event in midi.play():
                if event.status == umidiparser.NOTE_ON and event.velocity > 0:
                    note_on(event.note)
                elif event.status == umidiparser.NOTE_OFF or (
                    event.status == umidiparser.NOTE_ON and event.velocity == 0
                ):
                    note_off(event.note)
        except Exception as exc:
            print("buzzer: play_midi(%s) failed: %s" % (filename, exc))
        finally:
            pwm.duty_u16(0)

    def play_wav(self, filename, chunk_size=512):
        """Синхронно (блокирующе) стримит 8-битный моно WAV в PWM. Короткие
        файлы уведомлений (доли секунды) — блокировка на это время
        приемлема, как и сама грубость звука, это осознанный трейдофф ради
        простоты и надёжности тайминга каждого сэмпла."""
        if not self.enabled:
            return
        try:
            with open(filename, "rb") as f:
                sample_rate, data_size = _read_wav_header(f)
                pwm = self._pwm
                pwm.freq(WAV_PWM_CARRIER_FREQ)
                sample_period_us = max(1, int(1_000_000 / sample_rate))
                buf = bytearray(chunk_size)
                mv = memoryview(buf)
                remaining = data_size
                # Q8 fixed-point (volume=100 -> gain_q8=256=1.0x), чтобы не
                # тащить float в @micropython.native функцию.
                gain_q8 = int(max(0, self.volume) / 100.0 * 256)
                try:
                    while remaining > 0:
                        want = min(chunk_size, remaining)
                        n = f.readinto(mv[:want])
                        if not n:
                            break
                        remaining -= n
                        _stream_samples(pwm, buf, n, sample_period_us, gain_q8)
                finally:
                    pwm.duty_u16(0)
        except Exception as exc:
            print("buzzer: play_wav(%s) failed: %s" % (filename, exc))


def _read_wav_header(f):
    """Разбирает RIFF/WAVE-заголовок, возвращает (sample_rate, data_size) и
    оставляет файл открытым сразу на начале сэмплов чанка 'data'.
    Поддерживается только 8-битный несжатый PCM моно (см. подсказку по
    конвертации в шапке файла)."""
    riff = f.read(12)
    if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")

    channels = None
    sample_rate = None
    bits_per_sample = None
    while True:
        header = f.read(8)
        if len(header) < 8:
            raise ValueError("unexpected end of WAV file (no data chunk)")
        chunk_id = header[0:4]
        chunk_size = struct.unpack("<I", header[4:8])[0]
        if chunk_id == b"fmt ":
            fmt = f.read(chunk_size)
            audio_format, channels, sample_rate, _, _, bits_per_sample = struct.unpack(
                "<HHIIHH", fmt[:16]
            )
            if audio_format != 1:
                raise ValueError("only uncompressed PCM WAV is supported")
        elif chunk_id == b"data":
            if channels is None:
                raise ValueError("data chunk before fmt chunk")
            if channels != 1 or bits_per_sample != 8:
                raise ValueError(
                    "нужен 8-битный МОНО WAV, а тут %d канал(ов) %d бит — "
                    "сконвертируй: ffmpeg -i in.mp3 -ar 8000 -ac 1 -acodec pcm_u8 out.wav"
                    % (channels, bits_per_sample)
                )
            return sample_rate, chunk_size
        else:
            f.seek(chunk_size, 1)


@micropython.native
def _stream_samples(pwm, buf, n, sample_period_us, gain_q8):
    for i in range(n):
        centered = buf[i] - 128
        scaled = (centered * gain_q8) >> 8
        if scaled > 127:
            scaled = 127
        elif scaled < -128:
            scaled = -128
        pwm.duty_u16((scaled + 128) << 8)
        time.sleep_us(sample_period_us)
