"""Минимальный клиент MicroPython raw REPL поверх "сырого" termios --
обходной путь на случай, если pyserial/mpremote не может открыть порт
(EINVAL на tcsetattr — конкретно ловилось на WCH CH34x/CH343 USB-serial
адаптерах на macOS, временный сбой драйвера; но mpremote в итоге тоже
отпустило без вмешательства, так что это именно fallback на крайний
случай, а не замена mpremote по умолчанию).

Как библиотека (import raw_serial as rs):
    fd = rs.open_port(rs.find_port())
    rs.enter_raw_repl(fd)
    rs.sync_dir(fd, "./firmware", "")
    rs.exit_raw_repl(fd)
    os.close(fd)

Как CLI — см. --help (python3 raw_serial.py --help). Примеры:
    python3 raw_serial.py exec "print(1+1)"
    python3 raw_serial.py push main.py main.py
    python3 raw_serial.py sync ./firmware /
    python3 raw_serial.py --port /dev/cu.usbmodem1234 sync ./firmware /

Порт можно не указывать — find_port() возьмёт единственный подходящий
/dev/cu.* (кроме системных вроде Bluetooth-Incoming-Port), если он один;
если их несколько — попросит указать явно через --port.
"""
import glob
import os
import select
import termios
import time

_IGNORED_PORT_SUBSTRINGS = ("Bluetooth", "debug-console")


def find_port():
    candidates = [
        p for p in glob.glob("/dev/cu.*") if not any(s in p for s in _IGNORED_PORT_SUBSTRINGS)
    ]
    if not candidates:
        raise RuntimeError("не нашёл ни одного serial-порта в /dev/cu.* (плата подключена?)")
    if len(candidates) > 1:
        raise RuntimeError(
            "нашёл несколько портов, укажи явно (--port / open_port(...)): %s" % ", ".join(candidates)
        )
    return candidates[0]


def open_port(path=None):
    path = path or find_port()
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(fd)
    iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
               termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
    oflag &= ~termios.OPOST
    lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    cflag &= ~(termios.CSIZE | termios.PARENB)
    cflag |= termios.CS8
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    ispeed = ospeed = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
    return fd


def write_all(fd, data):
    view = memoryview(data)
    while len(view):
        try:
            n = os.write(fd, view)
        except BlockingIOError:
            select.select([], [fd], [], 0.2)
            continue
        if n:
            view = view[n:]


def read_some(fd, timeout=0.2):
    r, _, _ = select.select([fd], [], [], timeout)
    if r:
        return os.read(fd, 4096)
    return b""


def read_until(fd, marker, timeout=15):
    """Читает, пока marker не встретится в накопленном буфере. Возвращает
    (before_and_including_marker, remainder_after_marker)."""
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        idx = buf.find(marker)
        if idx != -1:
            end = idx + len(marker)
            return buf[:end], buf[end:]
        chunk = read_some(fd, 0.2)
        if chunk:
            buf += chunk
    raise TimeoutError("не дождался %r за %ss, получено: %r" % (marker, timeout, buf))


def drain(fd, quiet_time=0.3):
    buf = b""
    while True:
        chunk = read_some(fd, quiet_time)
        if not chunk:
            break
        buf += chunk
    return buf


def enter_raw_repl(fd):
    write_all(fd, b"\r\x03\x03")
    time.sleep(0.2)
    drain(fd)
    write_all(fd, b"\r\x01")
    read_until(fd, b"raw REPL; CTRL-B to exit\r\n>")


def exit_raw_repl(fd):
    write_all(fd, b"\r\x02")
    time.sleep(0.2)
    drain(fd)


def exec_raw(fd, code, timeout=15):
    """Выполняет code в raw REPL, возвращает stdout (bytes). Бросает
    RuntimeError с текстом ошибки, если плата вернула traceback."""
    if isinstance(code, str):
        code = code.encode()
    write_all(fd, code)
    write_all(fd, b"\x04")

    buf = b""
    deadline = time.time() + timeout
    while buf.count(b"\x04") < 2 and time.time() < deadline:
        chunk = read_some(fd, 0.2)
        if chunk:
            buf += chunk
    if buf.count(b"\x04") < 2:
        raise TimeoutError("неполный ответ от платы (нет двух 0x04): %r" % buf)
    # После предыдущей команды на входе мог остаться непрочитанным эхо
    # приглашения '>' -- срезаем его перед проверкой на 'OK'.
    buf = buf.lstrip(b">")
    if not buf.startswith(b"OK"):
        raise RuntimeError("плата не подтвердила приём кода (нет 'OK' в начале ответа): %r" % buf)

    body = buf[2:]
    first = body.index(b"\x04")
    out = body[:first]
    rest = body[first + 1 :]
    second = rest.index(b"\x04")
    err = rest[:second]
    if err:
        raise RuntimeError("ошибка на плате:\n%s" % err.decode(errors="replace"))
    return out


def _ensure_remote_dirs(fd, remote_path):
    parts = remote_path.strip("/").split("/")[:-1]
    cur = ""
    for p in parts:
        cur += "/" + p
        exec_raw(fd, "import os\ntry:\n os.mkdir(%r)\nexcept OSError:\n pass\n" % cur)


def push_file(fd, local_path, remote_path, chunk_size=1024, progress=None):
    """Заливает local_path (с компьютера) в remote_path (на плате) через
    raw REPL, кусками, закодированными в base64 (сырые байты — включая
    0x04 — по raw-REPL текстовому каналу гнать нельзя, испортит протокол)."""
    import binascii

    _ensure_remote_dirs(fd, remote_path)
    exec_raw(fd, "_f = open(%r, 'wb')\n" % remote_path)
    with open(local_path, "rb") as lf:
        data = lf.read()
    total = len(data)
    sent = 0
    for i in range(0, total, chunk_size):
        chunk = data[i : i + chunk_size]
        b64 = binascii.b2a_base64(chunk, newline=False)
        exec_raw(fd, b"import ubinascii as _ub\n_f.write(_ub.a2b_base64(" + repr(b64).encode() + b"))\n")
        sent += len(chunk)
        if progress:
            progress(sent, total)
    exec_raw(fd, "_f.close()\ndel _f\n")
    return total


def read_remote_file(fd, remote_path):
    """Читает файл с платы целиком (для проверки после push_file) —
    возвращает bytes."""
    import binascii

    out = exec_raw(
        fd,
        "import ubinascii as _ub\n"
        "with open(%r, 'rb') as _f:\n"
        " print(_ub.b2a_base64(_f.read()).decode().strip())\n" % remote_path,
    )
    return binascii.a2b_base64(out.strip())


def remote_sha256(fd, remote_path):
    """SHA256 удалённого файла (считается на самой плате через uhashlib,
    без гонять содержимое туда-сюда) -- None если файла нет."""
    out = exec_raw(
        fd,
        "import uhashlib, ubinascii\n"
        "try:\n"
        " with open(%r, 'rb') as _f:\n"
        "  _h = uhashlib.sha256()\n"
        "  while True:\n"
        "   _c = _f.read(512)\n"
        "   if not _c:\n"
        "    break\n"
        "   _h.update(_c)\n"
        "  print(ubinascii.hexlify(_h.digest()).decode())\n"
        "except OSError:\n"
        " print('MISSING')\n" % remote_path,
    )
    text = out.decode().strip()
    return None if text == "MISSING" else text


def local_sha256(local_path):
    import hashlib

    with open(local_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def sync_dir(fd, local_root, remote_root, skip_names=(".DS_Store",), skip_dirs=("__pycache__",), verbose=True):
    """Заливает local_root целиком в remote_root, пропуская файлы, чей
    SHA256 на плате уже совпадает (аналог "Up to date" у mpremote)."""
    import os as _os

    uploaded = []
    skipped = []
    for dirpath, dirnames, filenames in _os.walk(local_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        rel_dir = _os.path.relpath(dirpath, local_root)
        for fname in sorted(filenames):
            if fname in skip_names:
                continue
            local_path = _os.path.join(dirpath, fname)
            rel_path = fname if rel_dir == "." else _os.path.join(rel_dir, fname)
            remote_path = remote_root.rstrip("/") + "/" + rel_path.replace(_os.sep, "/")

            l_hash = local_sha256(local_path)
            r_hash = remote_sha256(fd, remote_path)
            if l_hash == r_hash:
                skipped.append(rel_path)
                if verbose:
                    print("up to date:", rel_path)
                continue

            push_file(fd, local_path, remote_path)
            uploaded.append(rel_path)
            if verbose:
                print("залито:", rel_path)
    return uploaded, skipped


def _cli():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="/dev/cu.* платы; если не указан — берётся единственный найденный")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_exec = sub.add_parser("exec", help="выполнить код на плате и напечатать вывод")
    p_exec.add_argument("code")

    p_push = sub.add_parser("push", help="залить один файл")
    p_push.add_argument("local")
    p_push.add_argument("remote")

    p_sync = sub.add_parser("sync", help="залить папку целиком (пропуская уже актуальные файлы)")
    p_sync.add_argument("local_dir")
    p_sync.add_argument("remote_dir")

    sub.add_parser("repl", help="интерактивный raw-exec: читает код с stdin построчно, Ctrl-D — выход")

    args = parser.parse_args()

    try:
        port = args.port or find_port()
    except RuntimeError as exc:
        print("ошибка:", exc, file=sys.stderr)
        raise SystemExit(1)

    print("порт:", port)
    fd = open_port(port)
    enter_raw_repl(fd)
    try:
        if args.cmd == "exec":
            out = exec_raw(fd, args.code)
            sys.stdout.flush()
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        elif args.cmd == "push":
            n = push_file(fd, args.local, args.remote)
            print("залито %d байт: %s -> %s" % (n, args.local, args.remote))
        elif args.cmd == "sync":
            uploaded, skipped = sync_dir(fd, args.local_dir, args.remote_dir)
            print("итого: залито %d, актуально %d" % (len(uploaded), len(skipped)))
        elif args.cmd == "repl":
            print("Вводи код построчно (пустая строка = выполнить), Ctrl-D в начале строки — выход.")
            while True:
                try:
                    line = input(">>> ")
                except EOFError:
                    break
                if not line:
                    continue
                try:
                    out = exec_raw(fd, line + "\n")
                    if out:
                        sys.stdout.buffer.write(out)
                except RuntimeError as exc:
                    print(exc, file=sys.stderr)
    finally:
        exit_raw_repl(fd)
        os.close(fd)


if __name__ == "__main__":
    _cli()
