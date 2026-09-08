# Общее между макетами разных экранов — только рисование текста с целочисленным
# масштабом (framebuf не умеет масштабировать текст сам). Сама раскладка
# (координаты, что где расположено) — отдельно и жёстко под каждый размер
# экрана в layout_400x300.py / layout_200x200.py, без общего "резинового"
# макета на все размеры.
#
# ВАЖНО: встроенный в framebuf шрифт поддерживает только ASCII — кириллицу
# он не рисует, поэтому подписи временно на английском (см. lib/, шрифт с
# кириллицей — отложенная задача).

import framebuf

from display import custom_font

# Подбор кастомного пиксельного шрифта (Orbitron/Verdana, display/fonts/) по
# имени вида "orbitron_52" — общее для всех макетов, которые используют эти
# шрифты (сейчас 200x200 и 400x300): апскейл/подбор ближайшего размера не
# зависит от геометрии конкретного экрана. Раньше жило только в
# layout_200x200.py — вынесено сюда, когда те же шрифты понадобились и для
# 400x300 (иначе пришлось бы дублировать один в один).

_font_cache = {}


def import_font(module_name):
    mod = __import__("display.fonts." + module_name)
    mod = getattr(mod, "fonts")
    return getattr(mod, module_name)


def split_family_size(name):
    """"orbitron_52" -> ("orbitron", 52). Если после последнего "_" не
    число (или "_" вообще нет) — возвращает (name, None)."""
    if "_" not in name:
        return name, None
    family, _, tail = name.rpartition("_")
    try:
        return family, int(tail)
    except ValueError:
        return name, None


def available_sizes_for_family(family):
    # Числа из имён файлов display/fonts/<family>_<N>.py — тот же <N>, что
    # был размером в pt при генерации (assets/generate_*_font.py), не
    # реальная высота в пикселях (она чуть меньше, см.
    # display/fonts/available_sizes.txt) — но для сравнения "какой размер
    # ближе к запрошенному" пропорции этого номинала достаточно. Семейства
    # между собой не смешиваем — запрос под verdana не подберёт orbitron.
    import os

    sizes = []
    try:
        names = os.listdir("/display/fonts")
    except OSError:
        return sizes
    prefix, suffix = family + "_", ".py"
    for n in names:
        if n.startswith(prefix) and n.endswith(suffix):
            try:
                sizes.append(int(n[len(prefix) : -len(suffix)]))
            except ValueError:
                pass
    return sorted(sizes)


def resolve_font(name):
    """Возвращает (font_module, scale). Сначала пробует точное совпадение
    имени файла; если такого файла нет — разбирает name на семейство и
    размер ("verdana_90" -> "verdana", 90), берёт ближайший ИМЕЮЩИЙСЯ
    размер этого же семейства (не больше запрошенного — апскейлить можно,
    обрезать 1bpp картинку вниз нельзя) и доапскейливает его целым числом
    через scale в custom_font."""
    if name in _font_cache:
        return _font_cache[name]

    try:
        result = (import_font(name), 1)
    except (ImportError, AttributeError):
        result = _nearest_font(name)

    _font_cache[name] = result
    return result


def _nearest_font(name):
    family, requested = split_family_size(name)
    sizes = available_sizes_for_family(family)

    if not sizes:
        # Семейства с таким именем нет вообще (опечатка типа "verdna_20")
        # — это уже не "другой размер", а совсем другой шрифт. Откатываемся
        # на Orbitron — он гарантированно есть, раз экран вообще что-то рисует.
        print("layout_common: нет шрифтов семейства '%s' (из '%s'), беру orbitron" % (family, name))
        family = "orbitron"
        sizes = available_sizes_for_family(family)
        if not sizes:
            print("layout_common: в display/fonts/ нет вообще ни одного шрифта")
            raise ImportError("no fonts available in display/fonts/")

    if requested is None:
        print("layout_common: не понял размер в имени '%s', беру %s_%d" % (name, family, sizes[-1]))
        chosen, scale = sizes[-1], 1
    else:
        smaller_or_equal = [s for s in sizes if s <= requested]
        chosen = max(smaller_or_equal) if smaller_or_equal else min(sizes)
        scale = max(1, round(requested / chosen))
        if chosen != requested:
            print(
                "layout_common: нет шрифта '%s', беру %s_%d%s"
                % (name, family, chosen, (" с апскейлом x%d" % scale) if scale > 1 else "")
            )

    return import_font("%s_%d" % (family, chosen)), scale


def shrink_font_to_fit(name, text, max_width, extra_width=0):
    """Тот же шрифт, но кегль за кеглем меньше (без апскейла), пока text (+
    extra_width — место, уже занятое хвостом типа "K"/".5K", который сам не
    ужимается) не влезет в max_width или не кончатся размеры этого
    семейства.

    Нужно в двух местах:
    - orders.min_abbrev — число сознательно НЕ сокращается в "1.2K", даже
      если не влезает по ширине (например настроен крупный orders.font, и
      999 ещё влезает, а 1000+ уже нет);
    - выручка, когда даже сокращённое "958K" не влезает целиком (крупная
      часть + буква сокращения).
    В обоих случаях единственный выход — сжать сам шрифт, не значение."""
    family, requested = split_family_size(name)
    sizes = available_sizes_for_family(family)
    if requested is None:
        requested = sizes[-1] if sizes else None
    candidates = sorted((s for s in sizes if s <= requested), reverse=True)
    fallback = None
    for size in candidates:
        font = import_font("%s_%d" % (family, size))
        fallback = font
        if custom_font.text_width(font, text, 1) + extra_width <= max_width:
            return font, 1
    if fallback is not None:
        # Даже самый мелкий размер этого семейства не влез — рисуем им как
        # есть, обрежется по краю экрана, но это уже крайний случай.
        return fallback, 1
    return resolve_font(name)


def split_compact(text):
    """Разбивает "13.5K"/"158K"/"13500" на (крупная часть, мелкий хвост) —
    хвост это всё начиная с первого не-цифрового символа: точка десятичных
    ("13" / ".5K") или сразу буква сокращения без точки ("158" / "K").
    Хвост рисуется мелким decimal_font — иначе "K"/"M" в "158K" выходит тем
    же крупным кеглем, что и сами цифры, и не читается как "тысячи", а
    выглядит как ещё один разряд числа."""
    for i, ch in enumerate(text):
        if not ch.isdigit():
            return text[:i], text[i:]
    return text, ""


class LayoutTxtConfig:
    """Текстовый key=value конфиг положения/шрифтов на экране
    (assets/layout.txt) — общая механика для всех макетов, которые её
    используют (сейчас 200x200 и 400x300): создание файла с дефолтами при
    первом запуске, дозапись недостающих полей в уже существующий файл
    (deep-merge для текстового формата — правка руками не может сломать
    экран насмерть, просто конкретное кривое поле откатится к дефолту),
    типизированное чтение полей. Раньше жила только в layout_200x200.py как
    россыпь модульных функций — вынесена сюда, когда тот же layout.txt
    понадобился и для 400x300.

    path — путь к файлу на плате. defaults — {key: str(default_value)}.
    template — текст файла с плейсхолдерами "{key}" (не str.format —
    точки в именах полей вроде "revenue.x" ломают его атрибутный синтаксис,
    поэтому обычная текстовая замена). log_prefix — что писать в консоль
    (обычно имя модуля-макета, "layout_400x300" и т.п.)."""

    def __init__(self, path, defaults, template, log_prefix):
        self.path = path
        self.defaults = defaults
        self.template = template
        self.log_prefix = log_prefix

    def _write_default(self):
        text = self.template
        for key, val in self.defaults.items():
            text = text.replace("{%s}" % key, val)
        try:
            with open(self.path, "w") as f:
                f.write(text)
        except OSError as exc:
            print("%s: не смог создать %s (%s)" % (self.log_prefix, self.path, exc))

    def _parse(self):
        values = {}
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if not line or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip()
        except OSError:
            return None
        return values

    def _append_missing(self, raw, missing_keys):
        lines = ["", "# Автодобавлено (новая версия прошивки добавила эти поля):"]
        for key in missing_keys:
            val = self.defaults[key]
            raw[key] = val
            lines.append("%s = %s" % (key, val))
        try:
            with open(self.path, "a") as f:
                f.write("\n".join(lines) + "\n")
            print("%s: дописал в layout.txt новые поля: %s" % (self.log_prefix, ", ".join(missing_keys)))
        except OSError as exc:
            print("%s: не смог дописать %s (%s)" % (self.log_prefix, self.path, exc))

    def get(self):
        """Читает layout.txt; создаёт с дефолтами, если файла нет; дописывает
        недостающие поля, если файл уже есть, но устарел."""
        raw = self._parse()
        if raw is None:
            self._write_default()
            return dict(self.defaults)

        missing = [k for k in self.defaults if k not in raw]
        if missing:
            self._append_missing(raw, missing)
        return raw

    def cfg_int(self, raw, key):
        try:
            return int(raw.get(key, self.defaults[key]))
        except (ValueError, TypeError):
            print(
                "%s: плохое значение '%s' для %s — беру дефолт %s"
                % (self.log_prefix, raw.get(key), key, self.defaults[key])
            )
            return int(self.defaults[key])

    def cfg_str(self, raw, key):
        """Для полей, где пустая строка не имеет смысла (имя шрифта) — если
        значение пустое или поля вообще нет, берём дефолт."""
        val = raw.get(key)
        return val if val else self.defaults[key]

    def cfg_text(self, raw, key):
        """Для полей, где пустая строка — осмысленное значение (например
        "суффикса нет"), а не опечатка. Дефолт берётся, только если поля
        нет вообще (старый layout.txt до миграции), а не когда оно явно
        пустое."""
        if key in raw:
            return raw[key]
        return self.defaults[key]


def draw_scaled_text(fb, text, x, y, scale=1, color=1):
    """Рисует текст встроенным 8x8 шрифтом с целочисленным масштабом —
    в framebuf нет нативного увеличения текста."""
    if scale <= 1:
        fb.text(text, x, y, color)
        return
    glyph_w = len(text) * 8
    tmp_buf = bytearray((glyph_w + 7) // 8 * 8)
    tmp = framebuf.FrameBuffer(tmp_buf, glyph_w, 8, framebuf.MONO_HLSB)
    tmp.fill(0)
    tmp.text(text, 0, 0, 1)
    for ty in range(8):
        for tx in range(glyph_w):
            if tmp.pixel(tx, ty):
                fb.fill_rect(x + tx * scale, y + ty * scale, scale, scale, color)


def scaled_text_width(text, scale=1):
    return len(text) * 8 * scale


def draw_scaled_text_centered(fb, text, center_x, y, scale=1, color=1):
    """Как draw_scaled_text, но x подбирается так, чтобы текст был
    отцентрирован по горизонтали вокруг center_x (сама координата y — верх
    текста, как и в draw_scaled_text, без вертикального центрирования)."""
    x = center_x - scaled_text_width(text, scale) // 2
    draw_scaled_text(fb, text, x, y, scale, color)
