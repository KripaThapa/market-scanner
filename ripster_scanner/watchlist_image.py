"""Local screenshot OCR. No strategy or annotation interpretation."""

import csv
from dataclasses import dataclass
import io
from pathlib import Path
import subprocess


class WatchlistImageError(ValueError):
    """An image cannot be read or processed by the OCR engine."""


@dataclass(frozen=True)
class OCRToken:
    text: str
    confidence: float
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    block_num: int = 0
    par_num: int = 0
    line_num: int = 0
    word_num: int = 0

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    @property
    def center_x(self):
        return self.left + self.width / 2

    @property
    def center_y(self):
        return self.top + self.height / 2


def extract_image_tokens(image_path: str | Path) -> list[OCRToken]:
    """Read an image with Tesseract's English sparse-text OCR and TSV output."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise WatchlistImageError(f"Watchlist image does not exist or is not a file: {path}")
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "eng", "--psm", "11", "tsv"],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except FileNotFoundError as exc:
        raise WatchlistImageError(
            "Tesseract is not installed. Install tesseract with English language data; see README.md."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WatchlistImageError("Watchlist OCR timed out after 60 seconds") from exc
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise WatchlistImageError(
            f"Cannot OCR image {path}. Check image readability and Tesseract English language data."
        ) from exc

    tokens = tokens_from_tsv(result.stdout)
    # Sparse-text OCR can miss dark text on the colored header and vertical MTF.
    # A bounded header-only pass preserves the established body/symbol OCR.
    headings = [t for t in tokens if t.text.lower() in {'news', 'support', 'game'}]
    first = {}
    for token in headings:
        first.setdefault(token.text.lower(), token)
    if len(first) == 3 and max(t.top for t in first.values()) - min(t.top for t in first.values()) < max(t.height for t in first.values()) * 2:
        try:
            from PIL import Image, ImageChops, ImageDraw
            with Image.open(path) as image:
                height = max(t.height for t in first.values())
                top = max(0, int(min(t.top for t in first.values()) - height * 0.65))
                bottom = min(image.height, int(max(t.bottom for t in first.values()) + height * 1.5))
                buffer = io.BytesIO()
                cropped = image.crop((0, top, image.width, bottom)).convert('RGB')
                red, green, blue = cropped.split()
                # Black header lettering on saturated colored cells: maximum
                # channel separates ink from the background without touching body OCR.
                ink = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
                    lambda value: 255 if value >= 100 else 0)
                draw = ImageDraw.Draw(ink)
                ys = list(range(ink.height))
                borders = [x for x in range(ink.width) if sum(ink.getpixel((x,y)) == 0
                    for y in ys) >= len(ys) * .95]
                for x in borders:
                    draw.line((x,0,x,ink.height), fill=255)
                ink.save(buffer, format='PNG')
            header = subprocess.run(['tesseract','stdin','stdout','-l','eng','--psm','6','tsv'],
                input=buffer.getvalue(), capture_output=True, check=True, timeout=15)
            from dataclasses import replace
            extra = [replace(t, top=t.top + top) for t in tokens_from_tsv(header.stdout.decode())]
            names = {t.text.lower().strip(':.') for t in extra if t.confidence >= 80}
            if {'news','support','resistance','game'} <= names:
                tokens = [t for t in tokens if not top <= t.center_y < bottom] + extra
        except (ImportError, OSError, ValueError, subprocess.SubprocessError, UnicodeError):
            pass  # Optional header failure never makes symbol activation fragile.
    return tokens


def tokens_from_tsv(output):
    reader = csv.DictReader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE)
    if not {"level", "text", "conf"} <= set(reader.fieldnames or []):
        raise WatchlistImageError("Tesseract returned invalid TSV output")
    tokens = []
    try:
        for row in reader:
            if row["level"] == "5" and row["text"] and row["text"].strip():
                def integer(name):
                    return int(row.get(name) or 0)
                tokens.append(OCRToken(
                    row["text"].strip(), float(row["conf"]),
                    integer("left"), integer("top"), integer("width"), integer("height"),
                    integer("block_num"), integer("par_num"), integer("line_num"), integer("word_num"),
                ))
    except (TypeError, ValueError, KeyError) as exc:
        raise WatchlistImageError("Tesseract returned invalid word data") from exc
    return tokens
