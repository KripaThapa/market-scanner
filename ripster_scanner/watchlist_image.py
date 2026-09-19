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
                tokens.append(OCRToken(row["text"].strip(), float(row["conf"])))
    except (TypeError, ValueError, KeyError) as exc:
        raise WatchlistImageError("Tesseract returned invalid word data") from exc
    return tokens
