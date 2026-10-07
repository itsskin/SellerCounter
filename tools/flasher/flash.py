"""Прошивальщик SellerCounter: пустая плата ESP32-S3 -> рабочее устройство одной командой.

Запускать не напрямую, а через кнопку-лаунчер рядом (двойной клик):
    macOS    — «Прошить плату.command»
    Windows  — «Прошить плату.bat»
    Linux    — flash.sh

Что делает (сам, без ручных установок — нужен только Python 3.8+ и интернет
в первый раз):
  1. Проверяет окружение и докачивает всё недостающее: создаёт свою папку
     .venv рядом, ставит туда esptool и pyserial (системный Python не
     трогает), находит/скачивает образ MicroPython, находит папку firmware/
     (нет — скачивает с GitHub).
  2. Ищет плату по USB (WCH CH34x/CH343, CP210x, FTDI, родной USB ESP32-S3).
  3. Стирает flash и прошивает MicroPython (Octal PSRAM, ESP32_GENERIC_S3).
  4. Заливает firmware/ на плату по raw REPL, каждый файл — с проверкой
     sha256 и повтором при сбое.
  5. Перезагружает плату. Дальше — обычная настройка через Wi-Fi-точку
     SellerCounter-Setup (пароль 12345678) и страницу 192.168.4.1.

Ключи:
  --check          только проверить окружение и плату, ничего не менять
  --files-only     не трогать MicroPython и данные, только обновить файлы прошивки
  --image FILE     вместо MicroPython-образа записать готовый «золотой» образ
                   целиком (по адресу 0x0) и ничего больше не заливать
  --port PORT      указать порт вручную
  --yes            не спрашивать подтверждений
"""

import argparse
import hashlib
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
VENV_DIR = os.path.join(HERE, ".venv")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".sellercounter-flasher")

# Официальный образ MicroPython для ESP32-S3 с Octal PSRAM (N16R8).
MPY_URL = "https://micropython.org/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin"
MPY_FILENAME = MPY_URL.rsplit("/", 1)[1]
# sha256 официального образа (проверяется после скачивания).
MPY_SHA256 = "ab24eadfe3ef0e6ee38834d730e648def7cd82f3fa51ee0bbc59c29a6e1bd176"

REPO_ZIP_URL = "https://github.com/itsskin/SellerCounter/archive/refs/heads/main.zip"
PIP_PACKAGES = ["esptool>=4.7", "pyserial>=3.5", "certifi"]

# Файлы из firmware/, которые на плату не нужны (инструменты для компьютера).
SKIP_NAMES = (".DS_Store",)
SKIP_DIRS = ("__pycache__",)
SKIP_PREFIXES = ("display/assets/generate_", "display/assets/font_render_lib.py",
                 "display/assets/convert_bg_")

# USB VID известных USB-UART мостов и родного USB ESP32-S3.
KNOWN_VIDS = {0x1A86: "WCH CH34x/CH343", 0x10C4: "Silicon Labs CP210x",
              0x0403: "FTDI", 0x303A: "Espressif (родной USB)"}


def say(msg=""):
    print(msg, flush=True)


def step(n, total, title):
    say("")
    say("[%d/%d] %s" % (n, total, title))


def ok(msg):
    say("   ✓ " + msg)


def fail(msg, hint=None):
    say("   ✗ " + msg)
    if hint:
        for line in hint.strip().splitlines():
            say("     " + line)
    raise SystemExit(1)


# ───────────────────────── 1. окружение ─────────────────────────

def venv_python():
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return os.path.join(VENV_DIR, *sub.split("/"))


def in_our_venv():
    return os.path.abspath(sys.prefix) == os.path.abspath(VENV_DIR)


def bootstrap():
    """Если не в своём venv — создаёт его, ставит зависимости и перезапускает
    себя оттуда. Возвращает только когда мы уже внутри venv."""
    if sys.version_info < (3, 8):
        fail("Нужен Python 3.8 или новее, найден %s" % sys.version.split()[0],
             "Скачай с https://www.python.org/downloads/ и запусти кнопку заново.")
    ok("Python %s" % sys.version.split()[0])

    if in_our_venv():
        return

    if not os.path.exists(venv_python()):
        say("   … создаю свою папку с инструментами (.venv), один раз")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        except (subprocess.CalledProcessError, OSError):
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            fail("Не удалось создать .venv",
                 "На Linux (Debian/Ubuntu) поставь модуль: sudo apt install python3-venv")
    ok(".venv готов")

    probe = [venv_python(), "-c", "import esptool, serial, certifi"]
    if subprocess.call(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        say("   … скачиваю esptool и pyserial (нужен интернет, один раз)")
        cmd = [venv_python(), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"] + PIP_PACKAGES
        if subprocess.call(cmd) != 0:
            fail("Не получилось поставить esptool/pyserial",
                 "Проверь интернет и запусти кнопку заново.")
    ok("esptool и pyserial установлены")

    sys.stdout.flush()
    code = subprocess.call([venv_python(), os.path.abspath(__file__)] + sys.argv[1:])
    raise SystemExit(code)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "SellerCounter-flasher"})
    # Свои корневые сертификаты (certifi): у Python с python.org на macOS
    # системного хранилища нет, и HTTPS без этого падает с CERTIFICATE_VERIFY_FAILED.
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    print("\r   … %d%% (%d КБ)" % (got * 100 // total, got // 1024), end="", flush=True)
        print()
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        fail("Не удалось скачать %s: %s" % (url, exc), "Проверь интернет и запусти кнопку заново.")
    os.replace(tmp, dest)


def find_micropython_image():
    """Образ MicroPython: сначала рядом в репозитории (tools/micropython/),
    потом в кэше, иначе скачивает."""
    for folder in (os.path.join(REPO_ROOT, "tools", "micropython"), CACHE_DIR):
        path = os.path.join(folder, MPY_FILENAME)
        if os.path.exists(path):
            break
    else:
        path = os.path.join(CACHE_DIR, MPY_FILENAME)
        say("   … скачиваю MicroPython %s" % MPY_FILENAME)
        download(MPY_URL, path)

    digest = sha256_file(path)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        magic = f.read(1)
    if magic != b"\xe9" or size < 500_000:
        os.remove(path) if path.startswith(CACHE_DIR) else None
        fail("Файл %s не похож на образ ESP32 (повреждён при скачивании?)" % path,
             "Он удалён из кэша — запусти кнопку заново.")
    if MPY_SHA256 and digest != MPY_SHA256:
        os.remove(path) if path.startswith(CACHE_DIR) else None
        fail("Контрольная сумма образа не совпала (%s…)" % digest[:12],
             "Файл удалён из кэша — запусти кнопку заново.")
    ok("образ MicroPython: %s (%d КБ, sha256 %s…%s)" % (
        MPY_FILENAME, size // 1024, digest[:8], "" if MPY_SHA256 else " — не закреплена в скрипте"))
    return path


def find_firmware_dir(workdir):
    local = os.path.join(REPO_ROOT, "firmware")
    if os.path.exists(os.path.join(local, "main.py")):
        ok("прошивка: %s" % local)
        return local
    say("   … папки firmware/ рядом нет, скачиваю с GitHub")
    zpath = os.path.join(workdir, "repo.zip")
    download(REPO_ZIP_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(workdir)
    for name in os.listdir(workdir):
        cand = os.path.join(workdir, name, "firmware")
        if os.path.exists(os.path.join(cand, "main.py")):
            ok("прошивка скачана с GitHub")
            return cand
    fail("В скачанном архиве нет firmware/main.py")


# ───────────────────────── 2. порт ─────────────────────────

def list_candidate_ports():
    from serial.tools import list_ports
    found = []
    for p in list_ports.comports():
        if p.vid in KNOWN_VIDS:
            found.append(p)
    # macOS показывает каждый порт дважды (cu.* и tty.*) — оставляем cu.*
    cu = [p for p in found if "/cu." in p.device]
    if cu:
        found = cu
    return found


def pick_port(forced, assume_yes):
    if forced:
        ok("порт задан вручную: %s" % forced)
        return forced
    ports = list_candidate_ports()
    if not ports:
        fail("Плата не найдена по USB",
             "1) Вставь плату кабелем, который умеет передавать данные (не только зарядку).\n"
             "2) Если плата с чипом WCH CH340/CH343, поставь драйвер: https://www.wch-ic.com/downloads/category/30.html\n"
             "   (на Windows и macOS он обычно нужен; на Linux уже есть).\n"
             "3) Если всё равно не видно: зажми BOOT, воткни USB, отпусти BOOT.")
    if len(ports) == 1:
        p = ports[0]
        ok("плата: %s (%s)" % (p.device, KNOWN_VIDS[p.vid]))
        return p.device
    say("   Найдено несколько устройств:")
    for i, p in enumerate(ports, 1):
        say("     %d) %s — %s" % (i, p.device, KNOWN_VIDS[p.vid]))
    if assume_yes:
        fail("Несколько портов, а --yes не позволяет выбрать", "Укажи --port явно.")
    while True:
        ans = input("   Номер платы: ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(ports):
            return ports[int(ans) - 1].device


def wait_port(prefer, timeout=20):
    """После прошивки родной USB может переподключиться под другим именем."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = [p.device for p in list_candidate_ports()]
        if prefer in names:
            return prefer
        if names:
            return names[0]
        time.sleep(0.5)
    fail("Плата не появилась на USB после прошивки", "Переткни кабель и запусти кнопку с ключом --files-only.")


# ───────────────────────── 3. esptool ─────────────────────────

def run_esptool(port, *args):
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", port] + list(args)
    return subprocess.call(cmd)


def esptool_help(code):
    fail("esptool завершился с ошибкой (код %d)" % code,
         "Частые причины:\n"
         "• плата не вошла в режим прошивки — зажми BOOT, коротко нажми RESET (или воткни USB с зажатой BOOT), отпусти BOOT и повтори;\n"
         "• кабель только для зарядки или порт занят другой программой (Thonny, монитор порта) — закрой её;\n"
         "• не стоит драйвер WCH CH340/CH343.")


def check_board(port):
    out = subprocess.run([sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", port, "flash_id"],
                         capture_output=True, text=True)
    text = out.stdout + out.stderr
    if out.returncode != 0:
        say(text.strip()[-600:])
        esptool_help(out.returncode)
    info = [l.strip() for l in text.splitlines()
            if any(k in l for k in ("Chip is", "Detected flash size", "PSRAM", "Embedded"))]
    for l in info:
        ok(l)
    if not any("16MB" in l for l in info):
        say("   ! Объём flash не 16 МБ — убедись, что это плата N16R8 (прошивка рассчитана на неё).")


# ───────────────────────── 4. raw REPL ─────────────────────────

class RawRepl:
    def __init__(self, port):
        import serial
        self.ser = serial.Serial(port, 115200, timeout=0.2, write_timeout=5)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_until(self, marker, timeout):
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
                if marker in buf:
                    return buf
        raise TimeoutError("не дождался %r, получено: %r" % (marker, buf[-200:]))

    def enter(self, attempts=6):
        last = None
        for _ in range(attempts):
            try:
                self.ser.write(b"\r\x03\x03")
                time.sleep(0.3)
                self.ser.reset_input_buffer()
                self.ser.write(b"\r\x01")
                self._read_until(b"raw REPL; CTRL-B to exit\r\n>", 5)
                return
            except (TimeoutError, OSError) as exc:
                last = exc
                time.sleep(1)
        raise RuntimeError("не удалось войти в raw REPL: %s" % last)

    def exec(self, code, timeout=15):
        if isinstance(code, str):
            code = code.encode()
        self.ser.write(code + b"\x04")
        buf = b""
        deadline = time.time() + timeout
        while buf.count(b"\x04") < 2 and time.time() < deadline:
            buf += self.ser.read(4096)
        if buf.count(b"\x04") < 2:
            raise TimeoutError("неполный ответ платы: %r" % buf[-200:])
        buf = buf.lstrip(b">")
        if not buf.startswith(b"OK"):
            raise RuntimeError("плата не подтвердила код: %r" % buf[:200])
        body = buf[2:]
        out, rest = body.split(b"\x04", 1)
        err = rest.split(b"\x04", 1)[0]
        if err:
            raise RuntimeError("ошибка на плате:\n" + err.decode(errors="replace"))
        return out

    def mkdirs(self, remote_path):
        cur = ""
        for part in remote_path.strip("/").split("/")[:-1]:
            cur += "/" + part
            self.exec("import os\ntry:\n os.mkdir(%r)\nexcept OSError:\n pass\n" % cur)

    def remote_sha256(self, remote_path):
        out = self.exec(
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
            " print('MISSING')\n" % remote_path, timeout=20)
        text = out.decode().strip()
        return None if text == "MISSING" else text

    def push(self, data, remote_path, chunk=1024):
        import binascii
        self.mkdirs(remote_path)
        self.exec("import ubinascii as _ub\n_f = open(%r, 'wb')\n" % remote_path)
        for i in range(0, len(data), chunk):
            b64 = binascii.b2a_base64(data[i:i + chunk], newline=False)
            self.exec(b"_f.write(_ub.a2b_base64(" + repr(b64).encode() + b"))\n")
        self.exec("_f.close()\ndel _f\n")

    def push_verified(self, local_path, remote_path, retries=4):
        with open(local_path, "rb") as f:
            data = f.read()
        want = hashlib.sha256(data).hexdigest()
        for attempt in range(1, retries + 1):
            try:
                self.push(data, remote_path)
                if self.remote_sha256(remote_path) == want:
                    return
                say("     … контрольная сумма не совпала, повтор %d/%d" % (attempt, retries))
            except (TimeoutError, RuntimeError) as exc:
                say("     … сбой (%s), повтор %d/%d" % (str(exc).splitlines()[0][:60], attempt, retries))
                try:
                    self.enter()
                except RuntimeError:
                    pass
        raise RuntimeError("не удалось залить %s" % remote_path)


def collect_files(fw_dir):
    files = []
    for dirpath, dirnames, filenames in os.walk(fw_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name in SKIP_NAMES or name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, fw_dir).replace(os.sep, "/")
            if rel.startswith(SKIP_PREFIXES):
                continue
            files.append((full, rel))
    return files


def upload_firmware(port, fw_dir, skip_same):
    files = collect_files(fw_dir)
    repl = RawRepl(port)
    try:
        # после перезагрузки плате нужно пару секунд, чтобы загрузиться и создать файловую систему
        repl.enter(attempts=10)
        ok("связь с платой есть, заливаю %d файлов" % len(files))
        done = skipped = 0
        started = time.time()
        for i, (full, rel) in enumerate(files, 1):
            remote = "/" + rel
            if skip_same and repl.remote_sha256(remote) == sha256_file(full):
                skipped += 1
                continue
            repl.push_verified(full, remote)
            done += 1
            print("\r   … %d/%d  %s%s" % (i, len(files), rel, " " * 20), end="", flush=True)
        print()
        ok("залито %d, уже актуальных %d (%d с)" % (done, skipped, time.time() - started))
        try:
            repl.exec("import machine\nmachine.reset()\n", timeout=2)
        except Exception:
            pass  # плата ушла в перезагрузку — ответа не будет, это нормально
    finally:
        repl.close()


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--files-only", action="store_true")
    ap.add_argument("--image")
    ap.add_argument("--port")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    if not in_our_venv():
        say("=== Прошивальщик SellerCounter ===")
        say("")
        say("Проверяю, что всё нужное есть…")
    bootstrap()  # вне venv: готовит его и перезапускает нас внутри

    total = 4 if not args.files_only and not args.image else 3
    workdir = tempfile.mkdtemp(prefix="sc-flasher-")
    try:
        step(1, total, "Готовлю файлы")
        image = None
        fw_dir = None
        if args.image:
            image = os.path.abspath(args.image)
            if not os.path.exists(image):
                fail("Образ не найден: %s" % image)
            ok("золотой образ: %s (%d МБ)" % (image, os.path.getsize(image) >> 20))
        else:
            if not args.files_only:
                image = find_micropython_image()
            fw_dir = find_firmware_dir(workdir)

        step(2, total, "Ищу плату")
        port = pick_port(args.port, args.yes)
        if not args.files_only:
            check_board(port)
        if args.check:
            say("")
            say("Проверка пройдена: всё готово к прошивке.")
            return

        if not args.files_only:
            say("")
            say("ВНИМАНИЕ: flash платы будет полностью стёрт — пропадут Wi-Fi, ключи API и настройки.")
            if not args.yes:
                input("Нажми Enter, чтобы продолжить (Ctrl+C — отмена)… ")
            step(3, total, "Прошиваю %s" % ("золотой образ" if args.image else "MicroPython"))
            code = run_esptool(port, "--baud", "460800", "erase_flash") if not args.image else 0
            if code:
                esptool_help(code)
            code = run_esptool(port, "--baud", "460800", "write_flash", "-z", "0x0", image)
            if code:
                esptool_help(code)
            ok("образ записан")
            if args.image:
                say("")
                say("Готово. Плата перезагрузится сама.")
                return
            say("   … жду загрузки MicroPython")
            time.sleep(4)
            port = wait_port(port)

        step(total, total, "Заливаю прошивку SellerCounter")
        upload_firmware(port, fw_dir, skip_same=args.files_only)
    except KeyboardInterrupt:
        say("\nОтменено.")
        raise SystemExit(130)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    say("")
    say("═══ Готово! ═══")
    say("Плата перезагружается. Дальше:")
    say("  1. В Wi-Fi телефона/компьютера выбери сеть  SellerCounter-Setup  (пароль 12345678).")
    say("  2. Открой в браузере  http://192.168.4.1  и введи данные своей Wi-Fi сети и ключи маркетплейсов.")


if __name__ == "__main__":
    main()
