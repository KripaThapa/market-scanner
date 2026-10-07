"""Conservative header-geometry cell extraction layered on existing row selection."""
import re
import io
import subprocess
from statistics import median
from .watchlist_levels import parse_pivots

HEADERS = ('symbol', 'news', 'support', 'resistance', 'mtf', 'game')


def header_name(text):
    """Normalize lettering only; never correct symbols, prices or body text."""
    return re.sub(r'[^a-z]', '', text.lower())


def header_matches(token, name, band):
    value = header_name(token.text)
    # One substituted letter is allowed only in a long heading, with a
    # separately recognized Pivot underneath. No substring/body matching.
    exact = value == name
    variation = (len(name) >= 7 and len(value) == len(name)
                 and sum(a != b for a, b in zip(value, name)) == 1)
    if not exact and not variation:
        return False
    if name not in {'support', 'resistance'}:
        return exact and token.confidence >= 80
    pivot = any(header_name(t.text) == 'pivot' and t.confidence >= 80
                and token.bottom <= t.center_y <= token.bottom + token.height * 3
                and token.left <= t.center_x <= token.right for t in band)
    return (exact and token.confidence >= 80) or (pivot and
        token.confidence >= (70 if exact else 80))


def header_band(tokens, first_row_top):
    """Find an ordered header band without requiring a printed Symbol heading."""
    for news in tokens:
        if header_name(news.text) != 'news' or news.top >= first_row_top or news.confidence < 80:
            continue
        band = [t for t in tokens if t.top < first_row_top and
                abs(t.center_y - news.center_y) <= max(news.height, t.height) * 2]
        headings = [news]
        for name in ('support', 'resistance', 'game'):
            matches = [t for t in band if header_matches(t, name, band)]
            if len(matches) != 1:
                break
            headings.append(matches[0])
        if len(headings) == 4 and all(a.right < b.left for a, b in zip(headings, headings[1:])):
            return band, headings
    return None


def column_boundaries(tokens, first_row_top, image_path=None):
    if image_path:
        detected = image_column_boundaries(tokens, first_row_top, image_path)
        if detected:
            return detected
    # Require a complete, ordered header band above actual stock rows. Never
    # guess column roles from the contents of a stock's Game Plan.
    for symbol in tokens:
        if symbol.text.strip().lower() not in {'symbol', 'symbols', 'ticker'} or symbol.top >= first_row_top:
            continue
        band = [t for t in tokens if t.top < first_row_top and
                abs(t.center_y - symbol.center_y) <= max(symbol.height, t.height) * 2]
        headers = []
        for key in HEADERS:
            matches = [t for t in band if header_matches(t, key, band)
                       or (key == 'symbol' and t.text.lower() in {'symbols', 'ticker'})]
            if len(matches) != 1 or matches[0].confidence < 80:
                break
            headers.append(matches[0])
        if len(headers) != 6 or any(a.right >= b.left for a, b in zip(headers, headers[1:])):
            continue
        # Header starts delimit the columns. Text centers crossing a header
        # boundary are flagged below rather than assigned an actionable price.
        return [t.left for t in headers]
    return None


def image_column_boundaries(tokens, first_row_top, image_path):
    """Use printed header cell borders, including blank Symbol and vertical MTF.

    Require known headings plus visible ordered borders. No pixel coordinates
    or screenshot dimensions are hard-coded, and unavailable geometry falls back
    to literal-only parsing rather than assigning numbers to guessed columns.
    """
    try:
        from PIL import Image
        found = header_band(tokens, first_row_top)
        if found:
            band, headings = found
            news = headings[0]
            with Image.open(image_path) as original:
                image = original.convert('RGB')
                padding = max(t.height for t in headings) * 0.6
                top = max(0, int(min(t.top for t in headings) - padding))
                bottom = min(image.height - 1, first_row_top - 1,
                             int(max(t.bottom for t in band) + padding))
                if bottom <= top:
                    return None
                ys = list(range(top, bottom + 1, max(1, (bottom-top)//30)))
                dark = [x for x in range(image.width) if sum(max(image.getpixel((x,y))) < 65
                         for y in ys) >= len(ys) * 0.95]
            runs = []
            for x in dark:
                if not runs or x > runs[-1][-1] + 1:
                    runs.append([x])
                else:
                    runs[-1].append(x)
            # Broad blank dark header cells contribute their edge, not a fake
            # column center. Narrow continuous dark strokes are printed borders.
            edges = sorted({edge for run in runs for edge in (
                [(run[0]+run[-1])/2] if len(run) <= padding else [run[0],run[-1]+1])})
            support, resistance, game = headings[1:]
            def between(left, right):
                return [x for x in edges if left < x < right]
            news_edges = between(0, news.left)
            support_edges = between(news.right, support.left)
            resistance_edges = between(support.right, resistance.left)
            mtf_edges = between(resistance.right, game.left)
            if not news_edges or len(support_edges)!=1 or len(resistance_edges)!=1 or len(mtf_edges)!=2:
                return None
            # Keep the narrow intermediate cell distinct. Its boolean stays
            # unknown if the vertical MTF heading cannot be verified.
            mtf_text = ''.join(t.text for t in sorted(band,key=lambda t:t.top)
                if mtf_edges[0] < t.center_x < mtf_edges[1]).upper()
            if mtf_edges[1] - mtf_edges[0] >= (mtf_edges[0] - resistance_edges[0]) / 2:
                return None
            return {'starts': [0, news_edges[-1], support_edges[0], resistance_edges[0], *mtf_edges],
                    'mtf_verified': mtf_text == 'MTF'}
    except (ImportError, OSError, ValueError):
        return None
    return None


def extract_cells(tokens, boundaries, pivot_cells=None, blank_cells=None):
    fields = {'columns_detected': bool(boundaries), 'news': None, 'support_pivots': [],
              'resistance_pivots': [], 'mtf': None, 'game_plan': None, 'review_warnings': []}
    if not boundaries:
        fields['literal_reliable'] = all(80 <= t.confidence <= 100 for t in tokens)
        fields['review_warnings'].append('Table columns unavailable; only literal price instructions can be monitored.')
        return fields
    mtf_verified = True
    if isinstance(boundaries, dict):
        mtf_verified = boundaries['mtf_verified']
        boundaries = boundaries['starts']
        if not mtf_verified:
            fields['review_warnings'].append('MTF header OCR uncertain; original cell text retained without a boolean value.')
    cells = {key: [] for key in HEADERS}
    for token in tokens:
        index = max((i for i, x in enumerate(boundaries) if token.center_x >= x), default=0)
        cells[HEADERS[index]].append(token)
    for key, cell in cells.items():
        lines = []
        line_tolerance = median([t.height for t in cell]) * .65 if cell else 0
        for token in sorted(cell, key=lambda t: t.center_y):
            if not lines or token.center_y - lines[-1][0].center_y > line_tolerance:
                lines.append([token])
            else:
                lines[-1].append(token)
        text = ' '.join(t.text for line in lines for t in sorted(line,key=lambda t:t.left)).strip()
        # Confidence is checked per optional cell. A bad cell never rejects the
        # whole validated stock row or blocks activation of other stocks.
        reliable = all(80 <= t.confidence <= 100 and not any(
            t.left < boundary < t.right for boundary in boundaries[1:]) for t in cell)
        if not cell and blank_cells is not None and key not in blank_cells and key in {'news','support','resistance','game'}:
            reliable = False
            fields['review_warnings'].append(f'{key}: OCR returned no text but blank cell is unverified; review original image.')
        if not reliable:
            fields['review_warnings'].append(f'{key}: low-confidence OCR; no conditions extracted.')
        if key in {'support', 'resistance'}:
            has_cell = pivot_cells is None or key in pivot_cells
            values = parse_pivots(text) if reliable and has_cell else ()
            fields[f'{key}_cell'] = text or None
            fields[f'{key}_pivots'] = [str(value) for value in values]
            if not has_cell:
                fields['review_warnings'].append(f'{key}: separate pivot cell unavailable in this row; no levels extracted.')
            elif reliable and not text:
                fields[f'{key}_cell'] = ''
            if text and not values and text not in {'-', '—', 'N/A'} and reliable:
                fields['review_warnings'].append(f'{key}: unusable pivot cell; review original image.')
        elif key == 'mtf':
            fields['mtf_text'] = text or None
            if reliable and mtf_verified and re.fullmatch(r'(?:yes|true|x|✓|✔)', text, re.I):
                fields['mtf'] = True
            elif reliable and mtf_verified and re.fullmatch(r'(?:no|false|-|—)', text, re.I):
                fields['mtf'] = False
        elif key in {'news', 'game'}:
            if pivot_cells is not None and key not in pivot_cells:
                reliable = False
                fields['review_warnings'].append(f'{key}: separate column cell unavailable in this row; review original image.')
            fields['game_plan' if key == 'game' else 'news'] = text if reliable else None
            if key == 'game' and not reliable:
                fields['game_plan_reliable'] = False
    return fields


def image_row_bounds(image_path, columns, groups):
    """Locate horizontal cell rules around each symbol, excluding headline bands.

    Read geometry once. Without two enclosing rules use non-overlapping
    midpoints between adjacent symbol groups, never a guessed pivot column.
    """
    centers = [median(t.center_y for t in group) for group in groups]
    bounds = []
    for i, group in enumerate(groups):
        height = median(t.height for t in group)
        top = (centers[i-1] + centers[i])/2 if i else min(t.top for t in group)-height
        bottom = (centers[i] + centers[i+1])/2 if i+1 < len(groups) else max(t.bottom for t in group)+height
        bounds.append((int(top), int(bottom)))
    if not image_path or not columns:
        return bounds
    starts = columns['starts'] if isinstance(columns, dict) else columns
    try:
        from PIL import Image
        with Image.open(image_path) as original:
            image = original.convert('RGB')
            ends = list(starts[1:]) + [image.width-1]
            # Interior sample points: vertical rules themselves are not evidence
            # of a horizontal boundary. MTF is too narrow and is excluded.
            xs = [round((starts[i]+ends[i])/2) for i in (0,1,2,3,5)]
            rules = [y for y in range(image.height) if
                     sum(max(image.getpixel((x,y))) < 20 for x in xs) >= 4]
            for i, group in enumerate(groups):
                above = [y for y in rules if y < min(t.top for t in group)]
                below = [y for y in rules if y > max(t.bottom for t in group)]
                if above and below:
                    top, bottom = max(above)+1, min(below)
                    if (i == 0 or top > centers[i-1]) and (i+1 == len(groups) or bottom < centers[i+1]):
                        bounds[i] = (top,bottom)
    except (ImportError, OSError, ValueError):
        pass
    return bounds


def image_blank_cells(image_path, columns, bounds):
    """Missing OCR is not proof of a blank cell; require a uniform interior."""
    result = [set() for _ in bounds]
    if not image_path or not columns:
        return [None for _ in bounds]
    starts = columns['starts'] if isinstance(columns, dict) else columns
    try:
        from PIL import Image
        with Image.open(image_path) as original:
            image = original.convert('RGB')
            ends = list(starts[1:]) + [image.width-1]
            for row, (top,bottom) in enumerate(bounds):
                inset = max(2, round((bottom-top)*.08))
                for key,index in (('news',1),('support',2),('resistance',3),('game',5)):
                    box = (round(starts[index])+inset, top+inset,
                           round(ends[index])-inset, bottom-inset)
                    if box[2] > box[0] and box[3] > box[1]:
                        extrema = image.crop(box).getextrema()
                        if all(high-low <= 40 for low,high in extrema):
                            result[row].add(key)
    except (ImportError, OSError, ValueError):
        pass  # Unknown stays unavailable rather than being called blank.
    return result


def row_pivot_cells(image_path, columns, top, bottom):
    """Merged prose rows are not numeric pivot cells even if OCR finds digits."""
    starts = columns['starts'] if isinstance(columns, dict) else columns
    try:
        from PIL import Image
        with Image.open(image_path) as original:
            image = original.convert('RGB')
            ys = list(range(max(0,top),min(image.height,bottom),max(1,(bottom-top)//20)))
            def border(x):
                x = round(x)
                return bool(ys) and sum(min(max(image.getpixel((offset,y)))
                    for offset in range(max(0,x-2),min(image.width,x+3))) < 20
                    for y in ys) >= len(ys)*.9
            return {key for key,index in (('support',2),('resistance',3),('mtf',4))
                    if border(starts[index]) and border(starts[index+1])} | (
                        {'game'} if border(starts[5]) else set()) | (
                        {'news'} if border(starts[2]) else set())
    except (ImportError, OSError, ValueError):
        return set()  # No image evidence is not proof of a printed pivot cell.


def extract_pivot_tokens(image_path, columns, top, bottom):
    """Two bounded column OCR passes recover colored pivot ink missed by sparse OCR.

    OCR remains unrestricted text: malformed/nonnumeric cells still fail the
    strict pivot parser. No character-to-number or price corrections are made.
    """
    from dataclasses import replace
    from .watchlist_image import tokens_from_tsv
    starts = columns['starts'] if isinstance(columns, dict) else columns
    result = []
    try:
        from PIL import Image, ImageChops
        with Image.open(image_path) as image:
            for index in (2, 3):
                left, right = int(starts[index]) + 3, int(starts[index+1]) - 3
                crop = image.crop((left, max(0,top), right, min(image.height,bottom))).convert('RGB')
                red, green, blue = crop.split()
                # Bright pivot ink on dark cells -> black text on white. Body
                # notes and symbol extraction are never replaced by this pass.
                ink = ImageChops.lighter(ImageChops.lighter(red,green),blue).point(
                    lambda value: 0 if value >= 120 else 255)
                buffer = io.BytesIO()
                ink.save(buffer,format='PNG')
                output = subprocess.run(['tesseract','stdin','stdout','-l','eng','--psm','6','tsv'],
                    input=buffer.getvalue(), capture_output=True, check=True, timeout=20)
                result.extend(replace(t,left=t.left+left,top=t.top+max(0,top))
                              for t in tokens_from_tsv(output.stdout.decode()))
    except (ImportError, OSError, ValueError, subprocess.SubprocessError, UnicodeError):
        pass  # Optional field failure retains the original row and valid symbols.
    return result
