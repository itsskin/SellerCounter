# mpy-raw-serial

Минимальный клиент MicroPython raw REPL на чистом Python (`termios` +
`os.open`/`select`), без зависимости от `pyserial`/`mpremote`.

## Зачем

Обходной путь на случай, если `pyserial` (а с ним и `mpremote`, Thonny и
любой другой инструмент на его основе) не может открыть порт — конкретно
ловилась `termios.error: (22, 'Invalid argument')` на `tcsetattr` с
USB-serial адаптером на чипе WCH (CH34x/CH343) на macOS. Судя по всему —
временный сбой драйвера, а не постоянный баг pyserial: после нескольких
физических переподключений USB и/или прямой настройки termios в обход
pyserial всё само отпустило, и `mpremote` дальше работал нормально.

Так что по умолчанию продолжай пользоваться `mpremote`/Thonny — они
быстрее. Этот инструмент — на случай, если они снова откажутся открывать
порт с той же ошибкой.

Лежит в `tools/` (не в `firmware/`) специально — эта папка никогда не
заливается на плату, `tools/` вообще не про прошивку, а про инструменты
разработки.

## Использование

Запускать из корня проекта (`SellerCounter/`), пути к прошивке — от него:

```bash
python3 tools/mpy-raw-serial/raw_serial.py exec "print(1+1)"
python3 tools/mpy-raw-serial/raw_serial.py push firmware/main.py main.py
python3 tools/mpy-raw-serial/raw_serial.py sync firmware /
python3 tools/mpy-raw-serial/raw_serial.py repl
python3 tools/mpy-raw-serial/raw_serial.py --port /dev/cu.usbmodem1234 sync firmware /
```

Порт можно не указывать — если в `/dev/cu.*` (кроме Bluetooth/debug-console)
всего один кандидат, возьмётся он.

Как библиотека:

```python
import raw_serial as rs

fd = rs.open_port(rs.find_port())
rs.enter_raw_repl(fd)
rs.sync_dir(fd, "./firmware", "")   # заливает всё, что реально изменилось
                                     # (сверка по SHA256, как "Up to date" у mpremote)
rs.exit_raw_repl(fd)
import os; os.close(fd)
```

## Как диагностировать похожую проблему заново

1. `stty -f /dev/cu.XXX 115200 raw -echo` — если проходит без ошибки, а
   `pyserial`/`mpremote` всё равно падают на `tcsetattr` — дело именно в
   pyserial, не в порте/драйвере.
2. Ручная настройка termios в Python напрямую (см. `open_port()` в этом
   файле) — если она проходит там, где `pyserial` падает, значит порт и
   драйвер живы, просто pyserial что-то делает не так при открытии.
3. Если и это не помогает — физически отключи-подключи USB-кабель.
