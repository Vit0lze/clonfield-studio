"""Character sheet: one picture of a character becomes a labelled sheet of views (turnaround, expressions) made with Qwen Image 2.1's edit mode.

The recipe is the Studio's own (no third-party workflow is used): each view is a separate edit of the SAME reference with a prompt that names
what must not change (face, hair, outfit, colours, proportions) and the single thing that does (the angle or the expression), the "baseline +
delta" idea. The seed is shared by every view so the rolls are comparable. The reference is padded to the generation canvas, never cropped,
so a full-body figure keeps its head and feet.

The prompts, the padding and the sheet are pure CPU code and are tested with real images. Whether the model actually keeps the character on
model across views is NOT measured (BLOQUEADO_GPU): treat the output as a draft to review.
"""

from PIL import Image, ImageDraw, ImageFont, ImageOps

BACKGROUND = (232, 232, 234)
KEEP = ("Keep the same character exactly: face, hair, skin, outfit, colours, accessories and body proportions unchanged. "
        "Plain light grey studio background, even lighting, the whole figure in frame.")

TURNAROUND = [
    ("front", "Frente", "Show this character facing the camera, standing straight, arms relaxed at the sides."),
    ("three_quarter", "3/4", "Show this character turned three-quarters to the left, standing in a neutral pose."),
    ("side", "Perfil", "Show this character in full side profile facing left, standing in a neutral pose."),
    ("back", "Costas", "Show this character from directly behind, standing in a neutral pose."),
]
EXPRESSIONS = [
    ("happy", "Alegre", "Show the same character from the chest up, facing the camera, with a warm, open smile."),
    ("sad", "Triste", "Show the same character from the chest up, facing the camera, with a sad expression and lowered eyes."),
    ("angry", "Bravo", "Show the same character from the chest up, facing the camera, with an angry, frowning expression."),
    ("surprised", "Surpreso", "Show the same character from the chest up, facing the camera, with wide eyes and an open mouth in surprise."),
]
SETS = {
    "turnaround": ("Giro de personagem (4 ângulos)", TURNAROUND),
    "expressions": ("Expressões (4)", EXPRESSIONS),
    "full": ("Completo (4 ângulos + 4 expressões)", TURNAROUND + EXPRESSIONS),
}
SIZES = {"Vertical · 768 × 1152": (768, 1152), "Vertical · 1024 × 1536": (1024, 1536), "Quadrado · 1024 × 1024": (1024, 1024)}
CELL_HEIGHT = 480
GAP, LABEL = 14, 34
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf")


def views(set_key):
    if set_key not in SETS:
        raise ValueError("Escolha o conjunto de vistas.")
    return SETS[set_key][1]


def prompt_for(view, notes=""):
    """The edit instruction for one view. `notes` are details the user wants preserved, appended to the baseline."""
    text = f"{view[2]} {KEEP}"
    notes = " ".join((notes or "").split())
    return text + (f" Also keep: {notes[:300]}." if notes else "")


def fit(image, size):
    """The reference on a canvas of `size` (width, height), scaled to fit and centred on the studio grey: padded, never cropped."""
    picture = ImageOps.exif_transpose(image).convert("RGB")
    width, height = size
    scale = min(width / picture.width, height / picture.height)
    resized = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, BACKGROUND)
    canvas.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return canvas


def _font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def sheet(pictures, columns=4):
    """`pictures`: [(label, path)] in order. A grid with the label under each picture. Returns an RGB image."""
    if not pictures:
        raise ValueError("Nenhuma vista para montar.")
    cells = []
    for label, path in pictures:
        with Image.open(path) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
        scale = CELL_HEIGHT / picture.height
        cells.append((label, picture.resize((max(64, round(picture.width * scale)), CELL_HEIGHT), Image.Resampling.LANCZOS)))
    columns = max(1, min(columns, len(cells)))
    rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
    cell_width = max(cell.width for _, cell in cells)
    width = columns * cell_width + (columns + 1) * GAP
    height = len(rows) * (CELL_HEIGHT + LABEL) + (len(rows) + 1) * GAP
    canvas = Image.new("RGB", (width, height), (24, 24, 27))
    draw, font = ImageDraw.Draw(canvas), _font(20)
    for r, row in enumerate(rows):
        for c, (label, cell) in enumerate(row):
            x = GAP + c * (cell_width + GAP) + (cell_width - cell.width) // 2
            y = GAP + r * (CELL_HEIGHT + LABEL + GAP)
            canvas.paste(cell, (x, y))
            draw.text((GAP + c * (cell_width + GAP) + cell_width / 2, y + CELL_HEIGHT + 6), label, fill=(236, 236, 240), font=font, anchor="mt")
    return canvas
