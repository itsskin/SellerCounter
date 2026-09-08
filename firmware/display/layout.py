# Диспетчер макетов — выбирает нужный точный пиксельный layout по размеру
# конкретного экрана. Никакого общего "резинового" макета на все размеры —
# каждый экран имеет свою руками подогнанную раскладку:
#   400x300 -> layout_400x300.py (WeAct 4.2")
#   200x200 -> layout_200x200.py (1.54", SSD1681)

from display import layout_200x200, layout_400x300


def get_layout(width, height):
    if width == 200 and height == 200:
        return layout_200x200
    return layout_400x300
