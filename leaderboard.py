"""Premium leaderboard image for the poker club."""

import os
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(ROOT, "fonts")
W = 1200

BG_TOP = (7, 8, 11)
BG_BOTTOM = (17, 19, 26)
IVORY = (247, 243, 234)
GOLD = (216, 176, 96)
GOLD_INK = (232, 196, 122)
LINE = (92, 74, 42)

METAL = {
    "gold": [(102, 74, 32), (176, 136, 62), (255, 232, 176), (214, 170, 84), (128, 92, 40), (255, 244, 214), (168, 124, 52)],
    "silver": [(118, 124, 132), (198, 204, 212), (255, 255, 255), (168, 174, 184), (96, 102, 112)],
    "bronze": [(122, 74, 40), (196, 128, 74), (240, 198, 148), (168, 104, 60), (96, 58, 32)],
}
INK = {
    "gold": (232, 196, 122),
    "silver": (214, 220, 228),
    "bronze": (214, 156, 108),
}
KIND = ("gold", "silver", "bronze")


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def fallback_font(size, bold):
    candidates = []
    if os.name == "nt":
        candidates += [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        ]
    candidates += [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load_font(kind, size, weight):
    files = {
        "display": "Playfair.ttf",
        "brand": "Cinzel-Regular.ttf",
        "ui": "Manrope.ttf",
    }
    path = os.path.join(FONT_DIR, files[kind])
    try:
        font = ImageFont.truetype(path, size)
    except OSError:
        return fallback_font(size, weight >= 600)
    try:
        axes = font.get_variation_axes() or []
        if axes:
            axis = axes[0]
            font.set_variation_by_axes([max(axis["minimum"], min(axis["maximum"], weight))])
    except Exception:
        pass
    return font


def text_width(text, font, tracking=0):
    if not text:
        return 0
    widths = [font.getlength(ch) for ch in text]
    return sum(widths) + tracking * (len(text) - 1)


def draw_tracked(draw, xy, text, font, fill, tracking=0, anchor="mt"):
    x, y = xy
    widths = [font.getlength(ch) for ch in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    bbox = font.getbbox(text or "Ag")
    if anchor[1] == "m":
        y -= (bbox[3] + bbox[1]) / 2
    elif anchor[1] == "b":
        y -= bbox[3]
    else:
        y -= bbox[1]
    cursor = x
    for ch, width in zip(text, widths):
        draw.text((cursor, y), ch, font=font, fill=fill)
        cursor += width + tracking
    return total


def vertical_gradient(size, top, bottom):
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=lerp(top, bottom, y / max(1, height - 1)))
    return image


def vignette(image, strength=0.72):
    width, height = image.size
    small_w, small_h = max(1, width // 4), max(1, height // 4)
    mask = Image.new("L", (small_w, small_h), 0)
    pixels = mask.load()
    cx, cy = small_w / 2, small_h / 2
    max_r = (cx ** 2 + cy ** 2) ** 0.5 or 1
    for y in range(small_h):
        for x in range(small_w):
            ratio = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / max_r
            fade = min(1, max(0, (ratio - 0.25) / 0.75))
            pixels[x, y] = int(255 * fade * strength)
    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    black = Image.new("RGB", (width, height), (0, 0, 0))
    image.paste(black, (0, 0), mask)
    return image


def fill_round(base, box, radius, top, bottom):
    x0, y0, x1, y1 = [int(v) for v in box]
    width, height = max(1, x1 - x0), max(1, y1 - y0)
    panel = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(panel)
    for y in range(height):
        color = lerp(top, bottom, y / max(1, height - 1))
        draw.line([(0, y), (width, y)], fill=color + (255,))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    base.paste(panel, (x0, y0), mask)


def metal_frame(draw, box, radius, stops):
    x0, y0, x1, y1 = box
    for index, color in enumerate(stops):
        draw.rounded_rectangle(
            (x0 + index, y0 + index, x1 - index, y1 - index),
            radius=max(2, radius - index),
            outline=color,
            width=1,
        )


def diamond(draw, cx, cy, radius, fill):
    draw.polygon(
        [(cx, cy - radius), (cx + radius * 0.7, cy), (cx, cy + radius), (cx - radius * 0.7, cy)],
        fill=fill,
    )


def draw_crown(draw, cx, cy, scale, fill, jewel):
    draw.polygon(
        [
            (cx - scale, cy + scale * 0.42),
            (cx - scale, cy - scale * 0.05),
            (cx - scale * 0.5, cy + scale * 0.22),
            (cx, cy - scale * 0.72),
            (cx + scale * 0.5, cy + scale * 0.22),
            (cx + scale, cy - scale * 0.05),
            (cx + scale, cy + scale * 0.42),
        ],
        fill=fill,
    )
    draw.rectangle((cx - scale, cy + scale * 0.42, cx + scale, cy + scale * 0.68), fill=fill)
    for jx, jy in ((cx - scale * 0.72, cy - scale * 0.02), (cx, cy - scale * 0.62), (cx + scale * 0.72, cy - scale * 0.02)):
        draw.ellipse((jx - 3.5, jy - 3.5, jx + 3.5, jy + 3.5), fill=jewel)


def circle_photo(source, size):
    fitted = ImageOps.fit(source.convert("RGB"), (size * 3, size * 3), centering=(0.5, 0.34))
    mask = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, size * 3 - 2, size * 3 - 2), fill=255)
    fitted.putalpha(mask)
    return fitted.resize((size, size), Image.Resampling.LANCZOS)


def money(value):
    try:
        amount = int(value)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,} грн".replace(",", " ")


def ru_word(value, one, few, many):
    number = abs(int(value))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not (12 <= number % 100 <= 14):
        return few
    return many


def plural(value, one, few, many):
    return f"{int(value)} {ru_word(value, one, few, many)}"


def fit_font(kind, text, max_width, size, weight, minimum=18):
    while size > minimum and load_font(kind, size, weight).getlength(text) > max_width:
        size -= 2
    return load_font(kind, size, weight)


def glow(base, cx, cy, radius, color):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    layers = 16
    for step in range(layers, 0, -1):
        radius_step = int(radius * step / layers)
        alpha = int(6 + 22 * (1 - step / layers))
        draw.ellipse(
            (cx - radius_step, cy - radius_step * 0.72, cx + radius_step, cy + radius_step * 0.72),
            fill=color + (alpha,),
        )
    return Image.alpha_composite(base, overlay)


def shadow(base, box, radius):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x0, y0, x1, y1 = box
    for step in range(14, 0, -1):
        draw.rounded_rectangle(
            (x0 - step + 2, y0 + 8 - step // 3, x1 + step + 2, y1 + 16 + step // 2),
            radius=radius + step,
            fill=(0, 0, 0, 14),
        )
    return Image.alpha_composite(base, overlay)


def paste_disc(base, center, diameter, ring, photo, letters, initial_fill, disc_fill):
    draw = ImageDraw.Draw(base)
    cx, cy = center
    radius = diameter / 2
    ring_w = 7 if diameter > 120 else 5
    draw.ellipse(
        (cx - radius - ring_w, cy - radius - ring_w, cx + radius + ring_w, cy + radius + ring_w),
        fill=ring,
    )
    draw.ellipse(
        (cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2),
        fill=(8, 9, 12),
    )
    if photo is not None:
        rendered = circle_photo(photo, int(diameter))
        base.paste(rendered, (int(cx - radius), int(cy - radius)), rendered)
        return
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=disc_fill)
    size = 42 if diameter > 120 else 28
    font = load_font("display", size, 650)
    draw.text((cx, cy), letters, font=font, fill=initial_fill, anchor="mm")


def initials(name):
    parts = [part for part in name.replace("_", " ").split() if part]
    letters = "".join(part[0] for part in parts[:2]).upper()
    return letters or "?"


def load_photo(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as source:
            oriented = ImageOps.exif_transpose(source)
            return oriented.convert("RGB")
    except (OSError, ValueError):
        return None


def render_leaderboard(players, photos):
    ranking = sorted(
        players.items(),
        key=lambda item: (
            int(item[1].get("points", 0) or 0),
            int(item[1].get("wins", 0) or 0),
            int(item[1].get("money", 0) or 0),
            item[0],
        ),
        reverse=True,
    )
    podium = ranking[:3]
    rest = ranking[3:]
    row_h = 102
    header_h = 188
    if len(podium) >= 3:
        podium_h = 78 + 548
    elif podium:
        podium_h = 40 + 560
    else:
        podium_h = 180
    list_h = (64 + len(rest) * row_h) if rest else 10
    height = header_h + podium_h + list_h + 86
    image = vignette(vertical_gradient((W, height), BG_TOP, BG_BOTTOM), 0.62).convert("RGBA")
    draw = ImageDraw.Draw(image)

    brand = load_font("brand", 22, 600)
    title = load_font("display", 58, 680)
    count_font = load_font("display", 42, 650)
    count_label = load_font("ui", 16, 500)
    diamond(draw, 68, 86, 6, GOLD)
    draw_tracked(draw, (88, 78), "POKER LEAGUE", brand, GOLD, tracking=5, anchor="lt")
    draw.text((56, 98), "Общий рейтинг", font=title, fill=IVORY, anchor="lt")
    draw.text((W - 56, 78), str(len(ranking)), font=count_font, fill=GOLD_INK, anchor="rt")
    draw_tracked(draw, (W - 56, 128), "ИГРОКОВ", count_label, (150, 156, 168), tracking=3, anchor="rt")
    draw.line((56, 172, W - 56, 172), fill=LINE, width=1)
    diamond(draw, W // 2, 172, 5, GOLD)

    if not podium:
        empty = load_font("display", 36, 600)
        draw.text((W // 2, header_h + 80), "Пока нет игроков", font=empty, fill=(150, 156, 168), anchor="mm")
    else:
        image = paint_podium(image, podium, header_h + 16, photos)
        draw = ImageDraw.Draw(image)

    if rest:
        list_top = header_h + podium_h + 8
        label = load_font("ui", 15, 650)
        label_text = "ОСТАЛЬНЫЕ ИГРОКИ"
        width = text_width(label_text, label, 3)
        mid = W // 2
        y = list_top + 18
        draw.line((56, y, mid - width / 2 - 18, y), fill=LINE, width=1)
        draw_tracked(draw, (mid, y), label_text, label, (176, 160, 120), tracking=3, anchor="mm")
        draw.line((mid + width / 2 + 18, y, W - 56, y), fill=LINE, width=1)
        y = list_top + 42
        for index, item in enumerate(rest, 4):
            image = paint_row(image, item, index, y, photos)
            y += row_h
        draw = ImageDraw.Draw(image)

    foot = load_font("ui", 16, 500)
    draw = ImageDraw.Draw(image)
    draw.text(
        (W // 2, height - 40),
        "Рейтинг обновляется из статистики игроков",
        font=foot,
        fill=(154, 160, 172),
        anchor="mm",
    )
    return image.convert("RGB")


def paint_podium(image, podium, top, photos):
    count = len(podium)
    if count >= 3:
        center_w, center_h = 424, 560
        side_w, side_h = 300, 438
        gap = 22
        total = side_w + center_w + side_w + gap * 2
        left = (W - total) // 2
        specs = [
            (1, left, top + 104, side_w, side_h),
            (0, left + side_w + gap, top, center_w, center_h),
            (2, left + side_w + gap + center_w + gap, top + 104, side_w, side_h),
        ]
    elif count == 1:
        center_w, center_h = 400, 520
        specs = [(0, (W - center_w) // 2, top + 10, center_w, center_h)]
    else:
        center_w, center_h = 400, 520
        side_w, side_h = 330, 470
        total = side_w + center_w + 28
        left = (W - total) // 2
        specs = [
            (1, left, top + 60, side_w, side_h),
            (0, left + side_w + 28, top, center_w, center_h),
        ]

    for place, x, y, w, h in sorted(specs, key=lambda spec: spec[0] == 0):
        image = shadow(image, (x, y, x + w, y + h), 32 if place == 0 else 26)
    for place, x, y, w, h in specs:
        if place == 0:
            image = glow(image, x + w / 2, y + 150, 250, (196, 146, 58))
    for place, x, y, w, h in sorted(specs, key=lambda spec: spec[0] == 0):
        image = paint_card(image, podium[place], place, (x, y, w, h), photos.get(podium[place][0]))
    return image


def paint_card(image, item, place, box, photo):
    name, data = item
    x, y, w, h = box
    kind = KIND[place]
    ink = INK[kind]
    if place == 0:
        top_c, bot_c = (46, 36, 22), (16, 14, 12)
        radius = 34
    elif place == 1:
        top_c, bot_c = (30, 33, 40), (14, 15, 18)
        radius = 30
    else:
        top_c, bot_c = (40, 28, 20), (14, 12, 11)
        radius = 30
    fill_round(image, (x, y, x + w, y + h), radius, top_c, bot_c)
    draw = ImageDraw.Draw(image)
    metal_frame(draw, (x, y, x + w, y + h), radius, METAL[kind])
    inset = 12
    draw.rounded_rectangle(
        (x + inset, y + inset, x + w - inset, y + h - inset),
        radius=radius - 10,
        outline=tuple(max(0, c - 40) for c in ink),
        width=1,
    )
    cx = x + w / 2
    cursor = y + (30 if place == 0 else 24)
    if place == 0:
        draw_crown(draw, cx, cursor + 8, 16, GOLD_INK, (255, 244, 214))
        for dx in (-w / 2 + 28, w / 2 - 28):
            diamond(draw, cx + dx, y + 28, 5, GOLD_INK)
        cursor += 36
    label = load_font("ui", 16 if place == 0 else 14, 700)
    draw_tracked(draw, (cx, cursor), f"{place + 1} МЕСТО", label, ink, tracking=3.5, anchor="mt")
    cursor += 26
    diameter = 168 if place == 0 else 112
    paste_disc(
        image,
        (cx, cursor + diameter / 2),
        diameter,
        ink,
        photo,
        initials(name),
        ink,
        (24, 26, 32),
    )
    cursor += diameter + 18
    draw = ImageDraw.Draw(image)
    name_size = 36 if place == 0 else 28
    name_font = fit_font("display", name, w - 48, name_size, 650, minimum=20)
    draw.text((cx, cursor), name, font=name_font, fill=IVORY, anchor="mt")
    cursor += name_font.size + 10
    points = int(data.get("points", 0) or 0)
    point_font = load_font("display", 58 if place == 0 else 44, 700)
    draw.text((cx, cursor), str(points), font=point_font, fill=ink, anchor="mt")
    cursor += (64 if place == 0 else 50)
    unit = load_font("ui", 13, 700)
    draw_tracked(draw, (cx, cursor), ru_word(points, "ОЧКО", "ОЧКА", "ОЧКОВ"), unit, ink, tracking=3, anchor="mt")
    cursor += 28
    draw.line((cx - 46, cursor, cx + 46, cursor), fill=tuple(max(0, c - 50) for c in ink), width=1)
    cursor += 14
    meta = load_font("ui", 16, 550)
    wins = int(data.get("wins", 0) or 0)
    games = int(data.get("games", 0) or 0)
    draw.text(
        (cx, cursor),
        f"{plural(wins, 'победа', 'победы', 'побед')}   ·   {plural(games, 'игра', 'игры', 'игр')}",
        font=meta,
        fill=(186, 190, 198),
        anchor="mt",
    )
    cursor += 34
    chip = money(data.get("money", 0))
    chip_font = load_font("ui", 16, 650)
    chip_w = text_width(chip, chip_font) + 36
    chip_h = 34
    draw.rounded_rectangle(
        (cx - chip_w / 2, cursor, cx + chip_w / 2, cursor + chip_h),
        radius=17,
        outline=ink,
        width=1,
    )
    draw.text((cx, cursor + chip_h / 2), chip, font=chip_font, fill=(236, 230, 216), anchor="mm")
    return image


def paint_row(image, item, place, y, photos):
    name, data = item
    x0, x1 = 48, W - 48
    h = 88
    fill_round(image, (x0, y, x1, y + h), 22, (20, 22, 28), (12, 13, 17))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x0, y, x1, y + h), radius=22, outline=(54, 46, 32), width=1)
    badge_font = load_font("ui", 18, 700)
    draw.rounded_rectangle((x0 + 16, y + 26, x0 + 70, y + 62), radius=12, fill=(30, 32, 40))
    draw.text((x0 + 43, y + 44), f"{place:02d}", font=badge_font, fill=(176, 164, 128), anchor="mm")
    paste_disc(
        image,
        (x0 + 112, y + h / 2),
        58,
        (120, 104, 70),
        photos.get(name),
        initials(name),
        (232, 220, 190),
        (32, 34, 42),
    )
    draw = ImageDraw.Draw(image)
    points_value = int(data.get("points", 0) or 0)
    wins = int(data.get("wins", 0) or 0)
    games = int(data.get("games", 0) or 0)
    points_font = load_font("ui", 26, 750)
    unit_font = load_font("ui", 15, 600)
    money_font = load_font("ui", 18, 650)
    meta_font = load_font("ui", 16, 500)
    cash = money(data.get("money", 0))
    unit_word = ru_word(points_value, "очко", "очка", "очков")
    cash_w = money_font.getlength(cash)
    unit_w = unit_font.getlength(unit_word)
    points_w = points_font.getlength(str(points_value))
    right = x1 - 22
    cash_left = right - cash_w
    unit_left = cash_left - 28 - unit_w
    points_left = unit_left - 8 - points_w
    name_font = fit_font("ui", name, points_left - (x0 + 156) - 16, 26, 700, minimum=18)
    draw.text((x0 + 156, y + 22), name, font=name_font, fill=(245, 242, 234), anchor="lt")
    draw.text(
        (x0 + 156, y + 54),
        f"{plural(wins, 'победа', 'победы', 'побед')}  ·  {plural(games, 'игра', 'игры', 'игр')}",
        font=meta_font,
        fill=(168, 174, 186),
        anchor="lt",
    )
    draw.text((points_left, y + 24), str(points_value), font=points_font, fill=GOLD_INK, anchor="lt")
    draw.text((unit_left, y + 32), unit_word, font=unit_font, fill=(196, 176, 128), anchor="lt")
    draw.text((right, y + 28), cash, font=money_font, fill=(236, 230, 216), anchor="rt")
    return image


def create_leaderboard_image(players, photos_dir="player_photos"):
    photos = {}
    for name in players:
        photo = load_photo(os.path.join(photos_dir, f"{name}.jpg"))
        if photo is not None:
            photos[name] = photo
    image = render_leaderboard(players, photos)
    fd, path = tempfile.mkstemp(prefix="poker_leaderboard_", suffix=".png")
    os.close(fd)
    image.save(path, format="PNG", optimize=True)
    return path
