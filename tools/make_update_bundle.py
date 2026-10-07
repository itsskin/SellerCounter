"""Собирает файл обновления для установки через веб-интерфейс платы
(раздел «Обновление прошивки» → «Установить из файла»), на случай когда
GitHub недоступен. Состав файлов — тот же, что у OTA (см. gen_ota_manifest.py:
без display/assets/ и notifications/, то есть данные пользователя не трогаются).

Запуск (из корня проекта, после того как версия в firmware/VERSION поднята):
    python3 tools/make_update_bundle.py            # -> dist/UBIX-update-v<версия>.scupd
    python3 tools/make_update_bundle.py out.scupd

Формат: b"SCUPD1\\n" + 4 байта (big-endian) длины JSON + JSON
{"version": N, "files": [{"path", "size", "sha256"}, ...]} + содержимое
файлов подряд в том же порядке. Разбирает его JavaScript в браузере
(firmware/www/app.js), на плату файлы уходят по одному с проверкой sha256.
"""

import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_ota_manifest as gom  # noqa: E402

MAGIC = b"SCUPD1\n"


def main():
    with open(gom.VERSION_PATH) as f:
        version = int(f.read().strip())

    entries, blobs = [], []
    for root, dirs, names in os.walk(gom.FIRMWARE_DIR):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, gom.FIRMWARE_DIR).replace(os.sep, "/")
            if not gom._should_include(rel):
                continue
            with open(abs_path, "rb") as f:
                data = f.read()
            entries.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            blobs.append(data)

    head = json.dumps({"version": version, "files": entries}, ensure_ascii=False).encode("utf-8")
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        gom.FIRMWARE_DIR, "..", "dist", "UBIX-update-v%d.scupd" % version)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(MAGIC + struct.pack(">I", len(head)) + head)
        for b in blobs:
            f.write(b)
    print("%s: версия %d, %d файлов, %d КБ" % (out, version, len(entries), os.path.getsize(out) // 1024))


if __name__ == "__main__":
    main()
