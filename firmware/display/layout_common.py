# Общее между макетами разных экранов — подбор кастомного пиксельного шрифта
# (Orbitron/Verdana) и единый layout.txt (LAYOUT, res_key, см. ниже). Сама
# раскладка (какие элементы где, что чем рисуется) — отдельно и жёстко под
# каждый размер экрана в layout_400x300.py / layout_200x200.py, без общего
# "резинового" макета на все размеры.

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


def uniform_font_for_items(name, items, max_width):
    """items — список (text, extra_width) пар (extra_width — уже занятое
    место под хвост типа "K", сам хвост в размере не участвует). Находит
    ОДИН общий размер семейства name — наибольший, при котором ВСЕ
    элементы сразу влезают в max_width (не по отдельности, кегль на
    кегль каждому свой) — иначе визуально сопоставимые числа получаются
    разного роста в зависимости от того, какие цифры внутри: у "1" глиф
    заметно уже, чем у "5"/"7", так что "13K" мог влезть в бо́льший кегль,
    чем "57K" при той же длине строки и той же ширине под неё — хотя оба
    должны выглядеть одного размера (см. "детализация по маркетплейсам",
    выручка разных площадок в соседних столбиках).

    Настроенный в layout.txt font — потолок, только пока нечем его
    превысить: когда места реально много (например часть маркетплейсов
    скрыта, столбик стал шире), общий размер может вырасти выше
    прописанного дефолта, а не остаться мелким посреди пустоты; когда
    самый широкий элемент не влезает даже в дефолт — наоборот, ужимается,
    как раньше делал shrink_font_to_fit, просто теперь единым проходом на
    весь набор, а не раздельно по каждому числу."""
    family, _ = split_family_size(name)
    sizes = sorted(available_sizes_for_family(family))
    if not sizes:
        return resolve_font(name)
    best = None
    for size in sizes:
        font = import_font("%s_%d" % (family, size))
        if all(custom_font.text_width(font, text, 1) + extra <= max_width for text, extra in items):
            best = font
        else:
            break
    if best is not None:
        return best, 1
    # Даже самый мелкий размер не влез хотя бы одному элементу — рисуем
    # им как есть, обрежется по краю у самого широкого (крайний случай).
    return import_font("%s_%d" % (family, sizes[0])), 1


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

    def cfg_bool(self, raw, key):
        """"0"/"1" -> bool, для полей show.<resolution>. Опечатка (не "0" и
        не "1") — тот же принцип, что у cfg_int: откат на дефолт этого
        конкретного поля, не крах всего экрана."""
        val = raw.get(key, self.defaults.get(key))
        if val not in ("0", "1"):
            print(
                "%s: плохое значение '%s' для %s (нужно 0 или 1) — беру дефолт %s"
                % (self.log_prefix, val, key, self.defaults[key])
            )
            val = self.defaults[key]
        return val == "1"

    def read_text(self):
        """Содержимое layout.txt как есть, с комментариями — для редактора в
        вебе (см. web_server.py /api/layout/text). Создаёт файл с дефолтами,
        если его ещё нет, как и get()."""
        try:
            with open(self.path) as f:
                return f.read()
        except OSError:
            self._write_default()
            try:
                with open(self.path) as f:
                    return f.read()
            except OSError as exc:
                print("%s: не смог создать %s (%s)" % (self.log_prefix, self.path, exc))
                return self.template

    def write_text(self, text):
        """Сохраняет content как есть — без валидации полей. Опечатка не
        ломает экран насмерть: get()/cfg_* при следующей перерисовке просто
        откатятся на дефолт для конкретного кривого поля (см. cfg_int/
        cfg_str/cfg_text выше)."""
        with open(self.path, "w") as f:
            f.write(text)


# Один общий layout.txt на ОБА экрана (раньше был свой файл под каждое
# разрешение — layout_200x200.py/layout_400x300.py дублировали структуру и
# DEFAULTS/TEMPLATE почти один в один). Теперь у каждого элемента (revenue/
# orders/clock/ip/fbs_label):
#   <element>.name           — человекочитаемое название, одно на оба экрана
#   <element>.show.<res>     — рисовать ли элемент вообще, отдельно на каждом
#                               разрешении ("0"/"1")
#   <element>.<field>.<res>  — сама геометрия/шрифт/текст, отдельно на
#                               каждом разрешении
# <res> — "200x200" или "400x300" (RESOLUTIONS ниже). Так оба макета
# редактируются в одном текстовом поле веб-интерфейса разом (см.
# web_server.py /api/layout/text) — правишь оба экрана, не переключаясь
# между файлами.
RESOLUTIONS = ("200x200", "400x300")

ASSETS_DIR = "/display/assets"
LAYOUT_TXT_PATH = ASSETS_DIR + "/layout.txt"

DEFAULTS = {
    "revenue.name": "Выручка",
    "revenue.show.200x200": "1",
    "revenue.show.400x300": "1",
    "revenue.x.200x200": "100",
    "revenue.x.400x300": "200",
    "revenue.y.200x200": "73",
    "revenue.y.400x300": "95",
    "revenue.font.200x200": "orbitron_52",
    "revenue.font.400x300": "orbitron_128",
    "revenue.max_width.200x200": "176",
    # 380 — по факту хватает на "1xxx" (371px в orbitron_128, у "1" узкий
    # глиф) без сокращения в "1.8K"; другие ведущие цифры ("2000"+) шире
    # (~410-430px) и физически не влезли бы в 400px экран без сокращения
    # даже с бОльшим запасом — так что выше поднимать особо некуда.
    "revenue.max_width.400x300": "380",
    # Когда выручка сокращается до вида "12.3K"/"1.2M" (см. format_compact),
    # часть от точки и дальше рисуется этим, более мелким шрифтом — для
    # визуального разделения целой части и сокращения, как копейки на
    # ценнике.
    "revenue.decimal_font.200x200": "orbitron_36",
    "revenue.decimal_font.400x300": "orbitron_70",

    "orders.name": "Заказы",
    "orders.show.200x200": "1",
    "orders.show.400x300": "1",
    "orders.x.200x200": "100",
    "orders.x.400x300": "200",
    "orders.y.200x200": "126",
    "orders.y.400x300": "205",
    "orders.font.200x200": "orbitron_42",
    "orders.font.400x300": "orbitron_96",
    "orders.max_width.200x200": "176",
    "orders.max_width.400x300": "320",
    "orders.decimal_font.200x200": "orbitron_24",
    "orders.decimal_font.400x300": "orbitron_52",
    # Подпись после числа заказов (например "шт") — маленькими буквами,
    # отдельным шрифтом. Orbitron кириллицу не умеет вообще, поэтому тут
    # обязательно verdana_*, а не orbitron_*. Пусто — подпись не рисуется.
    "orders.suffix.200x200": "",
    "orders.suffix.400x300": "шт",
    "orders.suffix_font.200x200": "verdana_15",
    "orders.suffix_font.400x300": "verdana_28",

    "clock.name": "Дата",
    # На 400x300 по умолчанию выключено — там своё место занято IP (см.
    # ip.* ниже); включи clock.show.400x300, если хочешь дату и там тоже.
    "clock.show.200x200": "1",
    "clock.show.400x300": "0",
    "clock.x.200x200": "100",
    "clock.x.400x300": "200",
    "clock.y.200x200": "10",
    "clock.y.400x300": "10",
    "clock.font.200x200": "orbitron_20",
    "clock.font.400x300": "orbitron_20",

    "ip.name": "IP-адрес",
    # На 200x200 по умолчанию выключено — экран маленький, места под ещё
    # одну строку обычно нет; включи ip.show.200x200, если нужно.
    "ip.show.200x200": "0",
    "ip.show.400x300": "1",
    "ip.x.200x200": "100",
    "ip.x.400x300": "200",
    "ip.y.200x200": "190",
    "ip.y.400x300": "282",
    "ip.font.200x200": "orbitron_20",
    "ip.font.400x300": "orbitron_20",

    "fbs_label.name": 'Напоминание "Собрать FBS"',
    # Кроме этого флага, напоминание всё равно рисуется, только когда
    # реально есть несобранный FBS-заказ И включён общий чекбокс в разделе
    # "Маркетплейсы" веб-интерфейса (cfg["display"]["show_fbs_reminder"]) —
    # оба этих условия остаются в силе, show.* тут третий, самый жёсткий
    # выключатель именно для этого экрана.
    "fbs_label.show.200x200": "1",
    "fbs_label.show.400x300": "1",
    "fbs_label.x.200x200": "100",
    "fbs_label.x.400x300": "200",
    "fbs_label.y.200x200": "165",
    "fbs_label.y.400x300": "260",
    "fbs_label.font.200x200": "verdana_15",
    "fbs_label.font.400x300": "verdana_28",
    "fbs_label.text.200x200": "Собрать FBS",
    "fbs_label.text.400x300": "Собрать FBS",

    # Экран "детализация по маркетплейсам" — ТОЛЬКО 400x300 (см.
    # cfg["display"]["show_marketplace_breakdown"], display/layout_400x300
    # ._draw_marketplace_breakdown()), поэтому поля тут БЕЗ суффикса
    # разрешения (в отличие от всех элементов выше) — на 200x200 у этого
    # режима вообще нет реализации. Включается/выключается через чекбокс в
    # веб-интерфейсе, не через layout.txt — тут только позиционирование.
    #
    # Маркетплейсы — СТОЛБИКАМИ рядом друг с другом (1-3 штуки, по числу
    # подключённых и видимых), не строками друг под другом: делят
    # area_width поровну и центрируются в area_x..area_x+area_width — так
    # при отключении одного из трёх оставшиеся два (или один) не жмутся в
    # левую треть экрана, а красиво распределяются по всей ширине области.
    # Внутри КАЖДОГО столбика — вертикальный стек, как на общем экране:
    # подпись сверху, выручка выше центра, заказы ниже (та же y-раскладка
    # что revenue.y/orders.y у общего вида, только чуть компактнее и общая
    # на все столбики — не x, а y тут ФИКСИРОВАННЫЙ, отдельный на каждый
    # столбик только x).
    "mp_row.name": "Детализация по маркетплейсам",
    # default_10 — растеризован из встроенного 8x8-шрифта framebuf (см.
    # generate_default_font.py), умеет латиницу (Orbitron — нет вообще,
    # только цифры+.-KM) и остаётся чётким на мелких размерах, где Orbitron
    # уже разваливается.
    "mp_row.label_font": "default_10",
    # Выручка — крупно, с округлением до целых K/M (без ".8K", только
    # "2K") — так остаётся широкий запас по ширине даже под большой
    # шрифт в узком столбике. decimal_font тут почти не используется
    # (max_decimals=0 в коде), но нужен на случай, если даже "2K" не влезет
    # и придётся ужимать шрифт с хвостом-буквой отдельно.
    "mp_row.revenue_font": "orbitron_70",
    "mp_row.revenue_decimal_font": "orbitron_36",
    # Заказы — заметно мельче выручки (это дополнительная цифра, не
    # главная).
    "mp_row.orders_font": "orbitron_36",
    "mp_row.orders_decimal_font": "orbitron_20",
    # Ширина столбика = area_width / (число видимых маркетплейсов) — та же
    # формула для позиции И для бюджета ширины под число (см.
    # _draw_marketplace_breakdown — пробовали разделить их, кончилось
    # наложением текста соседних столбиков друг на друга при 1-2
    # столбиках). column_margin — отступ с обеих сторон вместе, вычитается
    # из этой ширины под сам текст. При 1-2 видимых маркетплейсах столбик
    # автоматически шире — и место, и число крупнее (см. uniform_font_for_
    # items) — при 3 остаётся как было изначально.
    "mp_row.column_margin": "10",
    "mp_row.area_x": "5",
    "mp_row.area_width": "390",
    # Подпись — высоко над числами; выручка сразу под ней, вплотную.
    "mp_row.label_y": "20",
    "mp_row.revenue_y": "58",
    "mp_row.orders_y": "225",
}

LAYOUT_TXT_TEMPLATE = """\
# Расположение текста на экранах SellerCounter — ОДИН файл на оба
# разрешения (200x200 и 400x300), значения у каждого поля указаны для
# обоих сразу. Правь и сохраняй — подхватится на следующей перерисовке,
# перезапускать плату не нужно. Опечатка в отдельном поле не ломает экран
# — просто для этого поля вернётся значение по умолчанию.
#
# <элемент>.name — просто название для человека, ни на что не влияет.
# <элемент>.show.<разрешение> — рисовать ли элемент вообще на этом экране
#   ("0" или "1").
# x / y — центр текста в пикселях (0,0 — левый верхний угол экрана).
# font — <семейство>_<размер> из display/fonts/, без ".py" (сейчас есть
#   orbitron_* и verdana_*; полный список размеров — см.
#   display/fonts/available_sizes.txt). Размера с точным числом нет —
#   возьмётся ближайший меньший из того же семейства и увеличится до
#   нужного (апскейл, чуть "кубиками", но разборчиво).
# max_width — если число по ширине не влезает в столько пикселей, оно
#   сокращается ("12345" -> "12.3K", "1234567" -> "1.2M").
# decimal_font — часть после точки у сокращённого числа рисуется этим,
#   обычно более мелким шрифтом (как копейки на ценнике).
# orders.suffix — подпись после числа заказов (например "шт"). Пусто —
#   не рисуется. suffix_font обязательно verdana_* (Orbitron кириллицу не
#   умеет вообще).
# ip.font — IP-адрес состоит только из цифр и точек, так что тут годится и
#   orbitron_*, и verdana_*.
# fbs_label — см. комментарий у fbs_label.show выше по смыслу поля.

revenue.name = {revenue.name}
revenue.show.200x200 = {revenue.show.200x200}
revenue.x.200x200 = {revenue.x.200x200}
revenue.y.200x200 = {revenue.y.200x200}
revenue.font.200x200 = {revenue.font.200x200}
revenue.max_width.200x200 = {revenue.max_width.200x200}
revenue.decimal_font.200x200 = {revenue.decimal_font.200x200}
revenue.show.400x300 = {revenue.show.400x300}
revenue.x.400x300 = {revenue.x.400x300}
revenue.y.400x300 = {revenue.y.400x300}
revenue.font.400x300 = {revenue.font.400x300}
revenue.max_width.400x300 = {revenue.max_width.400x300}
revenue.decimal_font.400x300 = {revenue.decimal_font.400x300}

orders.name = {orders.name}
orders.show.200x200 = {orders.show.200x200}
orders.x.200x200 = {orders.x.200x200}
orders.y.200x200 = {orders.y.200x200}
orders.font.200x200 = {orders.font.200x200}
orders.max_width.200x200 = {orders.max_width.200x200}
orders.decimal_font.200x200 = {orders.decimal_font.200x200}
orders.suffix.200x200 = {orders.suffix.200x200}
orders.suffix_font.200x200 = {orders.suffix_font.200x200}
orders.show.400x300 = {orders.show.400x300}
orders.x.400x300 = {orders.x.400x300}
orders.y.400x300 = {orders.y.400x300}
orders.font.400x300 = {orders.font.400x300}
orders.max_width.400x300 = {orders.max_width.400x300}
orders.decimal_font.400x300 = {orders.decimal_font.400x300}
orders.suffix.400x300 = {orders.suffix.400x300}
orders.suffix_font.400x300 = {orders.suffix_font.400x300}

clock.name = {clock.name}
clock.show.200x200 = {clock.show.200x200}
clock.x.200x200 = {clock.x.200x200}
clock.y.200x200 = {clock.y.200x200}
clock.font.200x200 = {clock.font.200x200}
clock.show.400x300 = {clock.show.400x300}
clock.x.400x300 = {clock.x.400x300}
clock.y.400x300 = {clock.y.400x300}
clock.font.400x300 = {clock.font.400x300}

ip.name = {ip.name}
ip.show.200x200 = {ip.show.200x200}
ip.x.200x200 = {ip.x.200x200}
ip.y.200x200 = {ip.y.200x200}
ip.font.200x200 = {ip.font.200x200}
ip.show.400x300 = {ip.show.400x300}
ip.x.400x300 = {ip.x.400x300}
ip.y.400x300 = {ip.y.400x300}
ip.font.400x300 = {ip.font.400x300}

fbs_label.name = {fbs_label.name}
fbs_label.show.200x200 = {fbs_label.show.200x200}
fbs_label.x.200x200 = {fbs_label.x.200x200}
fbs_label.y.200x200 = {fbs_label.y.200x200}
fbs_label.font.200x200 = {fbs_label.font.200x200}
fbs_label.text.200x200 = {fbs_label.text.200x200}
fbs_label.show.400x300 = {fbs_label.show.400x300}
fbs_label.x.400x300 = {fbs_label.x.400x300}
fbs_label.y.400x300 = {fbs_label.y.400x300}
fbs_label.font.400x300 = {fbs_label.font.400x300}
fbs_label.text.400x300 = {fbs_label.text.400x300}

# "Детализация по маркетплейсам" — включается чекбоксом в веб-интерфейсе
# (раздел "Маркетплейсы"), не тут (там же — порядок столбиков, стрелками
# вверх/вниз, и тестовые поля для ручного превью без реальных заказов).
# Поля ниже — только 400x300, БЕЗ суффикса разрешения. Маркетплейсы —
# столбиками рядом (1-3 штуки, по числу подключённых и видимых — см.
# галочки "Отображать на экране детализации" у каждого): делят area_width
# поровну и центрируются в area_x..area_x+area_width. Внутри КАЖДОГО
# столбика — сверху вниз подпись ("Oz"/"Wb"/"Ya"), выручка (крупно,
# округляется до целых K/M — revenue_font), заказы (мельче — orders_font);
# label_y/revenue_y/orders_y — ОБЩАЯ на все столбики высота каждой строки
# (у столбиков отличается только x). column_margin — отступ под текст с
# обеих сторон столбика вместе (бюджет = ширина_столбика - column_margin);
# при 1-2 видимых маркетплейсах столбик шире, и выручка растёт крупнее
# настроенного revenue_font, используя освободившееся место — все
# видимые столбики сразу одним общим размером (не каждый по своей
# ширине — иначе визуально разные числа получались бы разного роста).
mp_row.name = {mp_row.name}
mp_row.label_font = {mp_row.label_font}
mp_row.revenue_font = {mp_row.revenue_font}
mp_row.revenue_decimal_font = {mp_row.revenue_decimal_font}
mp_row.orders_font = {mp_row.orders_font}
mp_row.orders_decimal_font = {mp_row.orders_decimal_font}
mp_row.column_margin = {mp_row.column_margin}
mp_row.area_x = {mp_row.area_x}
mp_row.area_width = {mp_row.area_width}
mp_row.label_y = {mp_row.label_y}
mp_row.revenue_y = {mp_row.revenue_y}
mp_row.orders_y = {mp_row.orders_y}
"""

LAYOUT = LayoutTxtConfig(LAYOUT_TXT_PATH, DEFAULTS, LAYOUT_TXT_TEMPLATE, "layout")


def res_key(element, field, resolution):
    """"revenue", "x", "200x200" -> "revenue.x.200x200" — составной ключ
    per-разрешение поля в общем layout.txt (см. LAYOUT выше)."""
    return "%s.%s.%s" % (element, field, resolution)
