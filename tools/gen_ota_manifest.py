"""Генерирует firmware/ota_manifest.json — список файлов прошивки с их
sha256, которые OTA-модуль на плате (firmware/ota.py) должен скачивать и
проверять при обновлении.

Запуск (на компьютере, перед коммитом/пушем очередного релиза):
    python3 tools/gen_ota_manifest.py

Версия — просто счётчик в firmware/VERSION (целое число, текстом). Каждый
раз, когда хочешь, чтобы устройства увидели обновление, увеличь число в
этом файле на 1 перед запуском генератора и закоммить оба файла вместе
с самими изменениями кода.

Исключено из манифеста (не OTA-управляемое, никогда не перезаписывается
обновлением):
  - display/assets/ целиком — bg_*.bin и layout*.txt это ДАННЫЕ
    пользователя (свой фон, свои координаты текста), а generate_*.py/
    font_render_lib.py вообще не используются на плате, это инструменты
    для генерации шрифтов на компьютере.
  - notifications/ целиком — пользователь может добавить свои мелодии.
"""

import hashlib
import json
import os

FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "firmware")
VERSION_PATH = os.path.join(FIRMWARE_DIR, "VERSION")
MANIFEST_PATH = os.path.join(FIRMWARE_DIR, "ota_manifest.json")

EXCLUDE_PREFIXES = ("display/assets/", "notifications/")
EXCLUDE_NAMES = ("ota_manifest.json", "VERSION")


def _should_include(rel_path):
    if rel_path.endswith(".pyc") or "__pycache__" in rel_path:
        return False
    if os.path.basename(rel_path) in EXCLUDE_NAMES:
        return False
    for prefix in EXCLUDE_PREFIXES:
        if rel_path.startswith(prefix):
            return False
    return True


def main():
    with open(VERSION_PATH) as f:
        version = int(f.read().strip())

    files = {}
    for root, dirs, names in os.walk(FIRMWARE_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, FIRMWARE_DIR).replace(os.sep, "/")
            if not _should_include(rel_path):
                continue
            with open(abs_path, "rb") as f:
                data = f.read()
            files[rel_path] = hashlib.sha256(data).hexdigest()

    manifest = {"version": version, "files": files}
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")

    print("ota_manifest.json: версия %d, %d файлов" % (version, len(files)))


if __name__ == "__main__":
    main()
