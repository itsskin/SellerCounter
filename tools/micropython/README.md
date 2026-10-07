# MicroPython для ESP32-S3 N16R8 (Octal PSRAM)

`ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin` — официальный образ с https://micropython.org/download/ESP32_GENERIC_S3/ (вариант `SPIRAM_OCT`, v1.29.0, 2026-08-24).
sha256: `ab24eadfe3ef0e6ee38834d730e648def7cd82f3fa51ee0bbc59c29a6e1bd176`

Нужен прошивальщику (`tools/flasher/`); если файла нет рядом, прошивальщик скачает его сам.
Вне OTA, на плату не заливается.

Вручную: `esptool --chip esp32s3 --port ПОРТ erase_flash`, затем
`esptool --chip esp32s3 --port ПОРТ --baud 460800 write_flash -z 0x0 ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin`.
