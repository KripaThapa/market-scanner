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

    reader = csv.DictReader(io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE)
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
