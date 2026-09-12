import socket
import time

try:
    import _thread
except ImportError:  # pragma: no cover — на симуляторе/хосте может не быть
    _thread = None

# Кэш DNS-резолвинга — {(host, port): addrinfo}. Без него каждый ОДИНОЧНЫЙ
# HTTP-запрос (то есть каждый опрос каждого маркетплейса, раз в
# poll_interval_sec) заново дёргал socket.getaddrinfo(), а это ЕДИНСТВЕННЫЙ
# сетевой вызов во всём модуле, для которого нет вообще никакой защиты от
# таймаута (в отличие от connect/TLS-handshake/чтения ответа — там везде
# settimeout честно выставлен, см. request() ниже). Если DNS у хоста
# зависнет (плохие условия сети, кривой ответ, что угодно на уровне
# lwIP-резолвера) — блокируется ВЕСЬ однопоточный event loop НАВСЕГДА, а с
# ним веб-сервер и даже подкормка watchdog, потому что вообще всё в проекте
# крутится в одном потоке/loop. Кэш резолвит каждый хост максимум один раз
# за время работы платы вместо одного раза на КАЖДЫЙ опрос — резко снижает,
# как часто вообще можно попасть в этот риск.
_dns_cache = {}


def _resolve(host, port, timeout_sec):
    """getaddrinfo с жёстким верхним пределом по времени — в отличие от
    голого socket.getaddrinfo(), который ничем не ограничен и может
    заблокировать поток навсегда (см. комментарий у _dns_cache выше).

    ESP32-S3 двухъядерный — реальный резолвинг гоняем в отдельном потоке
    (_thread, второе ядро), а тут просто ждём результат с явным дедлайном.
    Если резолвинг не уложился — поток может продолжать висеть в фоне сам
    по себе (не страшно, второе ядро не блокирует основной луп), а мы
    честно бросаем исключение и идём дальше, вместо того чтобы зависнуть
    вместе с ним.
    """
    cache_key = (host, port)
    cached = _dns_cache.get(cache_key)
    if cached is not None:
        return cached

    if _thread is None:
        # Нет потоков (например симулятор на хосте) — работаем как раньше,
        # без защиты от таймаута, лучше так, чем совсем не резолвить.
        ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
        _dns_cache[cache_key] = ai
        return ai

    result = [None]
    error = [None]
    done = [False]

    def _worker():
        try:
            result[0] = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
        except Exception as exc:
            error[0] = exc
        finally:
            done[0] = True

    _thread.start_new_thread(_worker, ())

    deadline = time.ticks_add(time.ticks_ms(), int(timeout_sec * 1000))
    while not done[0]:
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise OSError(
                "DNS resolution of %s timed out after %.1fs" % (host, timeout_sec)
            )
        time.sleep_ms(20)

    if error[0] is not None:
        raise error[0]

    _dns_cache[cache_key] = result[0]
    return result[0]


class _LineBufferedSocket:
    """Обёртка вокруг сокета, дающая надёжный readline() поверх read().

    На некоторых портах MicroPython родной readline() TLS-сокета
    (SSLSocket) периодически некорректно разбирает ответы с длинными
    заголовками/множеством Set-Cookie (например, у Yandex Market) —
    статус-строка парсилась в мусорное число вместо настоящего кода.
    read()/readinto() при этом всегда работали верно, так что здесь
    readline() реализован поверх них вручную, с локальным буфером.
    """

    def __init__(self, sock):
        self._sock = sock
        self._buf = bytearray()

    def _fill(self, target_len):
        while len(self._buf) < target_len:
            chunk = self._sock.read(512)
            if not chunk:
                break
            self._buf.extend(chunk)

    def readline(self):
        # bytearray на некоторых портах MicroPython не поддерживает
        # del ba[:n] (item deletion) — используем пересоздание среза
        # (ba = ba[n:]) вместо удаления на месте, это работает везде.
        #
        # ВАЖНО: читаем маленькими порциями и проверяем на "\n" после
        # КАЖДОГО чтения, а не гребём с запасом ("+512"). Раньше именно
        # это вызывало зависания на некоторых серверах (Yandex Market):
        # если реальных данных в потоке оставалось меньше, чем "с запасом"
        # просили у _fill(), последний read() блокировался в ожидании
        # байт, которых просто больше не будет, а сервер не спешит рвать
        # соединение — хотя нужная строка уже давно лежала в буфере.
        while True:
            idx = self._buf.find(b"\n")
            if idx != -1:
                line = bytes(self._buf[: idx + 1])
                self._buf = self._buf[idx + 1 :]
                return line
            chunk = self._sock.read(256)
            if not chunk:
                line = bytes(self._buf)
                self._buf = bytearray()
                return line
            self._buf.extend(chunk)

    def read(self, n=-1):
        if n is None or n < 0:
            data = bytes(self._buf)
            self._buf = bytearray()
            more = self._sock.read(-1)
            if more:
                data += more
            return data
        self._fill(n)
        data = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return data

    def readinto(self, b):
        want = len(b)
        self._fill(want)
        n = min(want, len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n

    def write(self, data):
        return self._sock.write(data)

    def close(self):
        self._sock.close()


class BodyStream:
    def __init__(self, sock, remaining):
        self._sock = sock
        self._chunk = remaining < 0
        self._remaining = remaining

    def read(self, n=-1):
        buf = bytearray(n if n >= 0 else 256)
        if n >= 0:
            got = self.readinto(buf)
            return buf[:got] if got else b""
        result = b""
        while True:
            got = self.readinto(buf)
            if not got:
                return result
            result += buf[:got]

    def readinto(self, buf):
        s = self._sock
        if self._remaining <= 0:
            if self._remaining == 0:
                return 0
            self._remaining = int(s.readline().split(b";")[0], 16)
            if self._remaining == 0:
                while True:
                    l = s.readline()
                    if not l or l == b"\r\n":
                        return 0
        if len(buf) > self._remaining:
            buf = memoryview(buf)[: self._remaining]
        got = s.readinto(buf)
        if not got:
            raise ValueError("Connection closed before body complete")
        self._remaining -= got
        if self._remaining == 0 and self._chunk:
            s.readline()
            self._remaining = -1
        return got

    def close(self):
        self._sock.close()


class Response:
    def __init__(self, f):
        self.raw = f
        self.encoding = "utf-8"
        self._cached = None

    def close(self):
        if self.raw:
            self.raw.close()
            self.raw = None
        self._cached = None

    @property
    def content(self):
        if self._cached is None:
            try:
                self._cached = self.raw.read()
            finally:
                self.raw.close()
                self.raw = None
        return self._cached

    @property
    def text(self):
        return str(self.content, self.encoding)

    def json(self):
        import json

        return json.loads(self.content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def request(
    method,
    url,
    data=None,
    json=None,
    headers=None,
    stream=None,
    auth=None,
    timeout=None,
    parse_headers=True,
):
    if headers is None:
        headers = {}
    else:
        headers = headers.copy()

    redirect = None  # redirection url, None means no redirection
    chunked_data = data and getattr(data, "__next__", None) and not getattr(data, "__len__", None)

    if auth is not None:
        import binascii

        username, password = auth
        formatted = b"{}:{}".format(username, password)
        formatted = str(binascii.b2a_base64(formatted)[:-1], "ascii")
        headers["Authorization"] = "Basic {}".format(formatted)

    try:
        proto, dummy, host, path = url.split("/", 3)
    except ValueError:
        proto, dummy, host = url.split("/", 2)
        path = ""
    if proto == "http:":
        port = 80
    elif proto == "https:":
        import tls

        port = 443
    else:
        raise ValueError("Unsupported protocol: " + proto)

    if "?" in host:
        host, _path = host.split("?", 1)
        path = "?" + _path + path

    if "#" in host:
        host, _path = host.split("#", 1)
        path = "#" + _path + path

    if ":" in host:
        host, port = host.split(":", 1)
        port = int(port)

    ai = _resolve(host, port, timeout if timeout is not None else 15)

    resp_d = None
    if parse_headers is not False:
        resp_d = {}

    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])

    if timeout is not None:
        # Note: settimeout is not supported on all platforms, will raise
        # an AttributeError if not available.
        s.settimeout(timeout)

    try:
        try:
            s.connect(ai[-1])
        except OSError:
            # Закэшированный IP мог протухнуть (сервер сменил адрес, старый
            # backend за DNS-балансировщиком выключили и т.п.) — выкидываем
            # его из кэша, чтобы СЛЕДУЮЩАЯ попытка резолвила заново, а не
            # долбилась в тот же самый мёртвый адрес до конца работы платы.
            _dns_cache.pop((host, port), None)
            raise
        if proto == "https:":
            context = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
            context.verify_mode = tls.CERT_NONE
            s = context.wrap_socket(s, server_hostname=host)
            if timeout is not None:
                # wrap_socket() возвращает новый объект — таймаут, поставленный
                # до этого на raw-сокете, не всегда переживает обёртку в TLS
                # на некоторых портах MicroPython. Ставим ещё раз явно, иначе
                # чтение ответа может зависнуть навсегда без исключения.
                try:
                    s.settimeout(timeout)
                except AttributeError:
                    pass
        s = _LineBufferedSocket(s)
        s.write(b"%s /%s HTTP/1.1\r\n" % (method, path))

        if "Host" not in headers:
            headers["Host"] = host

        if json is not None:
            assert data is None
            from json import dumps

            data = dumps(json)

            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"

        if data:
            if chunked_data:
                if "Transfer-Encoding" not in headers and "Content-Length" not in headers:
                    headers["Transfer-Encoding"] = "chunked"
            else:
                if isinstance(data, str):
                    data = bytes(data, "utf-8")
                if "Content-Length" not in headers:
                    headers["Content-Length"] = str(len(data))

        if "Connection" not in headers:
            headers["Connection"] = "close"

        # Iterate over keys to avoid tuple alloc
        for k in headers:
            s.write(k)
            s.write(b": ")
            s.write(headers[k])
            s.write(b"\r\n")

        s.write(b"\r\n")

        if data:
            if chunked_data:
                if headers.get("Transfer-Encoding", None) == "chunked":
                    for chunk in data:
                        s.write(b"%x\r\n" % len(chunk))
                        s.write(chunk)
                        s.write(b"\r\n")
                    s.write("0\r\n\r\n")
                else:
                    for chunk in data:
                        s.write(chunk)
            else:
                s.write(data)

        l = s.readline()
        # print(l)
        l = l.split(None, 2)
        if len(l) < 2:
            # Invalid response
            raise ValueError("HTTP error: BadStatusLine:\n%s" % l)
        status = int(l[1])
        reason = ""
        if len(l) > 2:
            reason = l[2].rstrip()
        remaining = None
        chunked = False
        while True:
            l = s.readline()
            if not l or l == b"\r\n":
                break
            # print(l)
            if l.startswith(b"Transfer-Encoding:"):
                if b"chunked" in l:
                    chunked = True
            elif l.startswith(b"Location:") and not 200 <= status <= 299:
                if status in [301, 302, 303, 307, 308]:
                    redirect = str(l[10:-2], "utf-8")
                    if redirect.startswith("/"):
                        redirect = proto + "//" + host + ":" + str(port) + redirect
                else:
                    raise NotImplementedError("Redirect %d not yet supported" % status)
            if parse_headers is False:
                pass
            elif parse_headers is True:
                l = str(l, "utf-8")
                k, v = l.split(":", 1)
                v = v.strip()
                resp_d[k] = v
                if k.lower() == "content-length":
                    remaining = int(v)
            else:
                parse_headers(l, resp_d)
    except:
        # Голый except (не except OSError) — HW-подтверждено: сервер
        # (наблюдалось на реальном трафике) иногда шлёт нестандартный
        # ответ, из-за которого разбор статус-строки/заголовков падает с
        # ValueError (int(l[1]), l.split(":", 1) без двоеточия и т.п.) —
        # это НЕ OSError, старый except OSError его не ловил, сокет
        # оставался открытым навсегда. ESP32 держит очень маленький пул
        # сокетов (HW-подтверждено: исчерпывался всего за ~6 утечек) —
        # достаточно было редких кривых ответов, чтобы за несколько минут
        # съесть все сокеты и уронить веб-сервер (ему уже нечем было
        # принимать новые подключения), хотя сама плата и опрос
        # маркетплейсов продолжали работать.
        s.close()
        raise

    if redirect:
        s.close()
        # Use the host specified in the redirect URL, as it may not be the same as the original URL.
        headers.pop("Host", None)
        if status in [301, 302, 303]:
            return request("GET", redirect, None, None, headers, stream)
        else:
            return request(method, redirect, data, json, headers, stream)
    else:
        if chunked:
            resp = Response(BodyStream(s, -1))
        elif remaining is not None:
            resp = Response(BodyStream(s, remaining))
        else:
            resp = Response(s)
        resp.status_code = status
        resp.reason = reason
        if resp_d is not None:
            resp.headers = resp_d
        return resp


def head(url, **kw):
    return request("HEAD", url, **kw)


def get(url, **kw):
    return request("GET", url, **kw)


def post(url, **kw):
    return request("POST", url, **kw)


def put(url, **kw):
    return request("PUT", url, **kw)


def patch(url, **kw):
    return request("PATCH", url, **kw)


def delete(url, **kw):
    return request("DELETE", url, **kw)
