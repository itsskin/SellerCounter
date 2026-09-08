import network
import time

AP_IP = "192.168.4.1"


def start_ap(ssid, password):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    if password:
        ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA2_PSK)
    else:
        ap.config(essid=ssid, authmode=network.AUTH_OPEN)
    return ap


def stop_ap():
    ap = network.WLAN(network.AP_IF)
    if ap.active():
        ap.active(False)


def connect_sta(ssid, password, timeout_sec=20):
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if sta.isconnected():
        return sta
    try:
        sta.connect(ssid, password)
    except OSError as exc:
        # ESP32 иногда оставляет Wi-Fi радио в битом состоянии после
        # прерванного/софтового ребута ("Wifi Internal State Error") —
        # переинициализация интерфейса и повтор обычно чинят это без
        # полного power cycle.
        print("wifi_manager: connect() raised %s, reinitializing and retrying" % exc)
        sta.active(False)
        time.sleep_ms(300)
        sta.active(True)
        time.sleep_ms(200)
        sta.connect(ssid, password)

    deadline = time.time() + timeout_sec
    while not sta.isconnected():
        if time.time() > deadline:
            return None
        time.sleep_ms(300)
    return sta


def is_sta_connected():
    sta = network.WLAN(network.STA_IF)
    return sta.active() and sta.isconnected()


def get_sta_ip():
    sta = network.WLAN(network.STA_IF)
    if sta.active() and sta.isconnected():
        return sta.ifconfig()[0]
    return None


def get_ip():
    ip = get_sta_ip()
    if ip:
        return ip
    ap = network.WLAN(network.AP_IF)
    if ap.active():
        return ap.ifconfig()[0]
    return None
