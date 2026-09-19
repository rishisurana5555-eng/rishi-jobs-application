"""
Rishi Jobs - Placement Services Agreement generator.

Fills the placeholders of the original template PDF (templates/contract_template.pdf)
without touching its design: the page background (logo, header, borders), fonts,
font sizes, margins, line spacing and table styling are all kept. Only the text
lines that change (or have to move down because a paragraph above grew) are
removed and re-typeset in the same Helvetica font, justified exactly like the
original.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from datetime import date

import pymupdf as fitz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "contract_template.pdf")

PLACEHOLDER_COLOR = 0xB00020      # red used for [PLACEHOLDERS] in the template
BLACK = (0, 0, 0)
LINE_GAP = 15.0                   # template leading (pt)
BOTTOM_LIMIT = 785.0              # lowest baseline allowed above the "Page N" footer
MIN_PARA_GAP = 17.0               # tightest paragraph spacing allowed when compressing

# --------------------------------------------------------------------------- #
# Business options
# --------------------------------------------------------------------------- #
PAYMENT_DAYS = {
    7: "Seven (07)",
    10: "Ten (10)",
    15: "Fifteen (15)",
    30: "Thirty (30)",
}

REPLACEMENT_DAYS = {
    60: "Sixty (60)",
    90: "Ninety (90)",
}

FEE_TYPES = {
    "tiered_10": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |10% above ₹ 12,00,000 CTC",
    "tiered_11": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |11% above ₹ 12,00,000 CTC",
    "tiered_12": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |12% above ₹ 12,00,000 CTC",
    "flat": "Flat:  8.33% of Annual CTC",
}

DEFAULT_SERVICE_DESCRIPTION = "Permanent Recruitment Services"

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def fee_cell_lines(fee_type: str) -> list[str]:
    """Split the fee option label into the lines shown in the fee table cell.

    The "Tiered:" / "Flat:" prefix is only for the form and is left out of the contract.
    """
    label = re.sub(r"^\s*(Tiered|Flat)\s*:\s*", "", FEE_TYPES[fee_type], flags=re.I)
    return [re.sub(r"\s+", " ", part).strip() for part in label.split("|")]


def format_contract_date(d: date) -> str:
    day = d.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%B')}, {d.year}"


# --------------------------------------------------------------------------- #
# Input model / validation
# --------------------------------------------------------------------------- #
@dataclass
class ContractDetails:
    contract_date: date
    company_name: str
    gst_number: str
    registered_address: str
    signatory_name: str
    signatory_designation: str
    payment_days: int
    replacement_days: int
    fee_type: str
    city: str = "Surat"
    service_description: str = DEFAULT_SERVICE_DESCRIPTION
    fill_information_sheet: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "ContractDetails":
        errors: list[str] = []

        def text(key, label, max_len, required=True, default=""):
            value = " ".join(str(data.get(key) or default).split())
            if required and not value:
                errors.append(f"{label} is required.")
            elif len(value) > max_len:
                errors.append(f"{label} must be at most {max_len} characters.")
            return value

        raw_date = data.get("contract_date")
        contract_date = None
        if isinstance(raw_date, date):
            contract_date = raw_date
        else:
            try:
                contract_date = date.fromisoformat(str(raw_date))
            except (TypeError, ValueError):
                errors.append("Contract date is required in YYYY-MM-DD format.")

        company = text("company_name", "Company name", 120)
        gst = text("gst_number", "GST number", 15).upper().replace(" ", "")
        if gst and not GSTIN_RE.match(gst):
            errors.append("GST number must be a valid 15-character GSTIN (e.g. 24ABCDE1234F1Z5).")
        address = text("registered_address", "Registered address", 300)
        signatory = text("signatory_name", "Signatory name", 60)
        designation = text("signatory_designation", "Signatory designation", 60)
        city = text("city", "City", 40, default="Surat")
        service = text("service_description", "Service description", 60,
                       default=DEFAULT_SERVICE_DESCRIPTION)

        def choice(key, label, options):
            try:
                value = int(data.get(key))
            except (TypeError, ValueError):
                value = None
            if value not in options:
                errors.append(f"{label} must be one of: {', '.join(map(str, options))}.")
            return value

        payment = choice("payment_days", "Payment days", PAYMENT_DAYS)
        replacement = choice("replacement_days", "Replacement days", REPLACEMENT_DAYS)
        fee_type = str(data.get("fee_type") or "")
        if fee_type not in FEE_TYPES:
            errors.append(f"Fee type must be one of: {', '.join(FEE_TYPES)}.")

        if errors:
            raise ValueError(errors)

        return cls(
            contract_date=contract_date,
            company_name=company,
            gst_number=gst,
            registered_address=address,
            signatory_name=signatory,
            signatory_designation=designation,
            payment_days=payment,
            replacement_days=replacement,
            fee_type=fee_type,
            city=city,
            service_description=service,
            fill_information_sheet=bool(data.get("fill_information_sheet", True)),
        )


# --------------------------------------------------------------------------- #
# Fonts & low level text drawing
# --------------------------------------------------------------------------- #
_FALLBACK_FONT_FILES = [  # used only for glyphs Helvetica lacks (e.g. ₹)
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Nirmala.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


class Fonts:
    def __init__(self):
        self.by_style = {
            "n": fitz.Font("helv"),
            "b": fitz.Font("hebo"),
            "i": fitz.Font("heit"),
        }
        self.fallback = None
        for path in _FALLBACK_FONT_FILES:
            if os.path.exists(path):
                try:
                    font = fitz.Font(fontfile=path)
                except Exception:
                    continue
                if font.has_glyph(0x20B9):
                    self.fallback = font
                    break

    def segments(self, text: str, style: str):
        """Split text into (text, font) chunks, routing unsupported glyphs to the fallback."""
        main = self.by_style[style]
        out: list[tuple[str, fitz.Font]] = []
        for ch in text:
            font = main
            if not main.has_glyph(ord(ch)) and ch not in " \xa0":
                if self.fallback is not None:
                    font = self.fallback
                else:
                    ch, font = ("Rs." if ch == "₹" else "?"), main
            if out and out[-1][1] is font:
                out[-1] = (out[-1][0] + ch, font)
            else:
                out.append((ch, font))
        return out

    def width(self, text: str, style: str, size: float) -> float:
        return sum(f.text_length(t, fontsize=size) for t, f in self.segments(text, style))


def _style_of(fontname: str) -> str:
    name = fontname.lower()
    if "bold" in name:
        return "b"
    if "oblique" in name or "italic" in name:
        return "i"
    return "n"


# --------------------------------------------------------------------------- #
# Template model
# --------------------------------------------------------------------------- #
@dataclass
class Span:
    text: str
    style: str
    color: int
    size: float
    x0: float
    x1: float
    bbox: fitz.Rect


@dataclass
class Line:
    y: float                       # baseline
    spans: list[Span]
    bbox: fitz.Rect

    @property
    def x0(self):
        return self.spans[0].x0

    @property
    def x1(self):
        return self.spans[-1].x1

    @property
    def size(self):
        return self.spans[0].size

    @property
    def has_placeholder(self):
        return any(s.color == PLACEHOLDER_COLOR for s in self.spans)


@dataclass
class Paragraph:
    lines: list[Line]
    new_lines: list | None = None  # re-typeset lines: list of (words, justify)
    changed: bool = False

    @property
    def top(self):
        return self.lines[0].y

    @property
    def bottom(self):
        return self.lines[-1].y


@dataclass
class Table:
    top: float
    bottom: float
    col_x: list[float]
    row_y: list[float]
    header_fill: tuple
    line_color: tuple
    line_width: float
    lines: list[Line] = field(default_factory=list)


def extract_lines(page: fitz.Page) -> list[Line]:
    rows: dict[float, list[Span]] = {}
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for s in line["spans"]:
                if not s["text"]:
                    continue
                key = round(s["origin"][1], 1)
                rows.setdefault(key, []).append(Span(
                    text=s["text"], style=_style_of(s["font"]), color=s["color"],
                    size=s["size"], x0=s["bbox"][0], x1=s["bbox"][2], bbox=fitz.Rect(s["bbox"]),
                ))
    lines = []
    for y, spans in sorted(rows.items()):
        spans.sort(key=lambda sp: sp.x0)
        bbox = fitz.Rect(spans[0].bbox)
        for sp in spans[1:]:
            bbox |= sp.bbox
        if spans[0].size < 9 and y > 790:          # "Page N" footer
            continue
        lines.append(Line(y=y, spans=spans, bbox=bbox))
    return lines


# --------------------------------------------------------------------------- #
# Typesetting (mirrors the template's ReportLab justified layout)
# --------------------------------------------------------------------------- #
Piece = tuple  # (text, style)


class Typesetter:
    def __init__(self, fonts: Fonts, left: float, right: float):
        self.fonts = fonts
        self.left = left
        self.right = right

    # -- words ------------------------------------------------------------- #
    @staticmethod
    def words_from_runs(runs: list[Piece]) -> list[list[Piece]]:
        words: list[list[Piece]] = []
        current: list[Piece] = []
        for text, style in runs:
            parts = re.split(r"( +)", text)
            for part in parts:
                if not part:
                    continue
                if part.startswith(" "):
                    if current:
                        words.append(current)
                        current = []
                else:
                    current.append((part, style))
        if current:
            words.append(current)
        return words

    def word_width(self, word, size):
        return sum(self.fonts.width(t, s, size) for t, s in word)

    def wrap(self, words, size, width=None):
        width = width or (self.right - self.left)
        space = self.fonts.width(" ", "n", size)
        lines, current, current_w = [], [], 0.0
        for w in words:
            ww = self.word_width(w, size)
            needed = ww if not current else current_w + space + ww
            if current and needed > width + 0.01:
                lines.append(current)
                current, current_w = [w], ww
            else:
                current.append(w)
                current_w = needed
        if current:
            lines.append(current)
        return lines

    # -- drawing ----------------------------------------------------------- #
    def draw_words(self, tw: fitz.TextWriter, words, x, y, size, justify, width=None):
        width = width or (self.right - self.left)
        space = self.fonts.width(" ", "n", size)
        gap = space
        if justify and len(words) > 1:
            total = sum(self.word_width(w, size) for w in words)
            gap = (width - total) / (len(words) - 1)
        for w in words:
            x = self.draw_pieces(tw, w, x, y, size)
            x += gap

    def draw_pieces(self, tw, pieces, x, y, size):
        for text, style in pieces:
            for chunk, font in self.fonts.segments(text, style):
                tw.append((x, y), chunk, font=font, fontsize=size)
                x += font.text_length(chunk, fontsize=size)
        return x

    def draw_original_line(self, tw, line: Line, y):
        """Redraw an unchanged template line at a new baseline."""
        if line.x0 <= self.left + 1 and line.x1 >= self.right - 1:
            runs = [(s.text, s.style) for s in line.spans]
            self.draw_words(tw, self.words_from_runs(runs), self.left, y, line.size, True)
        else:
            for s in line.spans:
                self.draw_pieces(tw, [(s.text, s.style)], s.x0, y, s.size)


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #
class ContractGenerator:
    def __init__(self, template_path: str = TEMPLATE_PATH):
        self.template_path = template_path
        self.fonts = Fonts()

    # -- public ------------------------------------------------------------ #
    def generate(self, details: ContractDetails) -> bytes:
        doc = fitz.open(self.template_path)
        self.details = details
        date_text = format_contract_date(details.contract_date)
        self.placeholders = {
            "[CITY]": details.city,
            "[DATE]": date_text,
            "[CLIENT COMPANY NAME]": details.company_name,
            "[GSTIN]": details.gst_number,
            "[CLIENT REGISTERED ADDRESS]": details.registered_address,
            "[PAYMENT DAYS]": PAYMENT_DAYS[details.payment_days],
            "[AUTHORIZED SIGNATORY NAME]": details.signatory_name,
            "[DESIGNATION]": details.signatory_designation,
        }
        # contract wording that depends on the chosen replacement period
        self.term_values = {
            "Ninety (90)": REPLACEMENT_DAYS[details.replacement_days],
        }
        self.term_pattern = re.compile(r"Ninety \(90\)(?= Days)")

        for page in doc:
            lines = extract_lines(page)
            if not lines:
                continue
            if self._is_signature_page(lines):
                self._fill_signature_table(page, lines)
            elif page.number == doc.page_count - 1:
                if details.fill_information_sheet:
                    self._fill_information_sheet(page, lines)
            else:
                self._process_flow_page(page, lines)

        doc.set_metadata({
            **doc.metadata,
            "title": f"Rishi Jobs - Placement Services Agreement - {details.company_name}",
            "author": "Rishi Jobs",
            "subject": "Placement Services Agreement",
            "creator": "Rishi Jobs Contract Generator",
        })
        doc.subset_fonts()
        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True)
        doc.close()
        return buf.getvalue()

    # -- page classification ---------------------------------------------- #
    @staticmethod
    def _is_signature_page(lines):
        return any("Authorized Signatory" in s.text for l in lines for s in l.spans)

    # -- substitution ------------------------------------------------------ #
    def _substitute_runs(self, runs):
        """runs: list of (text, style, color) -> list of (text, style), plus changed flag."""
        out, changed = [], False
        for text, style, color in runs:
            if color == PLACEHOLDER_COLOR:
                key = " ".join(text.split())
                if key in self.placeholders:
                    out.append((self.placeholders[key], "b"))
                    changed = True
                    continue
            # contract terms chosen in the form are set in bold, like the placeholders
            pos = 0
            for m in self.term_pattern.finditer(text):
                out.append((text[pos:m.start()], style))
                # only the first mention in a paragraph is bold (clause 4 mentions it twice)
                bold = self._terms_seen == 0
                self._terms_seen += 1
                out.append((self.term_values[m.group(0)], "b" if bold else style))
                pos = m.end()
                changed = True
            out.append((text[pos:], style))
        return [(t, st) for t, st in out if t], changed

    @staticmethod
    def _paragraph_runs(par: Paragraph):
        runs: list[list] = []
        for i, line in enumerate(par.lines):
            for j, s in enumerate(line.spans):
                text = s.text
                if i > 0 and j == 0:
                    runs[-1][0] += " "
                if runs and runs[-1][1] == s.style and runs[-1][2] == s.color:
                    runs[-1][0] += text
                else:
                    runs.append([text, s.style, s.color])
        return [tuple(r) for r in runs]

    # -- flowing text pages (1, 2, 4, 5) ----------------------------------- #
    def _process_flow_page(self, page: fitz.Page, lines: list[Line]):
        body = [l for l in lines if l.size > 9]
        left = min(l.x0 for l in body)
        right = max(l.x1 for l in body)
        ts = Typesetter(self.fonts, left, right)

        table = self._find_table(page, lines)
        flow = [l for l in lines if not (table and table.top <= l.y <= table.bottom)]
        paragraphs = self._group_paragraphs(flow)

        any_change = False
        for par in paragraphs:
            self._terms_seen = 0
            runs, changed = self._substitute_runs(self._paragraph_runs(par))
            if not changed:
                continue
            any_change = True
            par.changed = True
            size = par.lines[0].size
            kept = self._keep_line_breaks(par, ts, right)
            if kept is not None:
                par.new_lines = kept
                continue
            wrapped = ts.wrap(ts.words_from_runs(runs), size)
            continues = par.lines[-1].x1 >= right - 1   # paragraph runs on to next page
            par.new_lines = [(w, (i < len(wrapped) - 1) or continues) for i, w in enumerate(wrapped)]

        table_growth = 0.0
        if table:
            table_growth = self._table_growth(table, ts)
            any_change = True
        if not any_change:
            return

        # ---- vertical layout ------------------------------------------------
        items = []   # (kind, obj, orig_top, orig_bottom, new_height)
        for par in paragraphs:
            n = len(par.new_lines) if par.changed else len(par.lines)
            items.append(["par", par, par.top, par.bottom, (n - 1) * LINE_GAP])
        if table:
            items.append(["table", table, table.top, table.bottom,
                          table.bottom - table.top + table_growth])
        items.sort(key=lambda it: it[2])

        new_tops = []
        shift_started = False
        eligible = []
        for i, it in enumerate(items):
            if i == 0:
                new_tops.append(it[2])
            else:
                prev = items[i - 1]
                gap = it[2] - prev[3]
                new_tops.append(new_tops[-1] + prev[4] + gap)
                if shift_started and gap > MIN_PARA_GAP:
                    eligible.append((i, gap))
            obj = it[1]
            if (it[0] == "par" and obj.changed) or it[0] == "table":
                shift_started = True

        last = items[-1]
        overflow = new_tops[-1] + last[4] - BOTTOM_LIMIT
        if overflow > 0 and last[3] <= BOTTOM_LIMIT and eligible:
            # tighten paragraph spacing below the first change, never below MIN_PARA_GAP
            per_gap = overflow / len(eligible)
            reduce = {i: min(per_gap, gap - MIN_PARA_GAP) for i, gap in eligible}
            acc = 0.0
            for i in range(len(items)):
                acc += reduce.get(i, 0.0)
                new_tops[i] -= acc

        # ---- redact & redraw ------------------------------------------------
        to_redraw = []
        for it, new_top in zip(items, new_tops):
            kind, obj, orig_top = it[0], it[1], it[2]
            moved = abs(new_top - orig_top) > 0.01
            if kind == "table" or obj.changed or moved:
                to_redraw.append((kind, obj, new_top))

        if table:
            page.add_redact_annot(fitz.Rect(table.col_x[0] - 2, table.row_y[0] - 2,
                                            table.col_x[-1] + 2, table.row_y[-1] + 2), fill=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
        for kind, obj, _ in to_redraw:
            if kind == "par":
                for line in obj.lines:
                    r = fitz.Rect(line.bbox)
                    page.add_redact_annot(fitz.Rect(r.x0 - 1, r.y0 + 3, r.x1 + 1, r.y1 - 3), fill=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)

        tw = fitz.TextWriter(page.rect)
        for kind, obj, new_top in to_redraw:
            if kind == "table":
                self._draw_table(page, tw, obj, new_top, ts)
            elif obj.changed:
                size = obj.lines[0].size
                for i, (words, justify) in enumerate(obj.new_lines):
                    ts.draw_words(tw, words, ts.left, new_top + i * LINE_GAP, size, justify)
            else:
                for line in obj.lines:
                    ts.draw_original_line(tw, line, new_top + (line.y - obj.top))
        tw.write_text(page, color=BLACK)

    def _keep_line_breaks(self, par: Paragraph, ts: Typesetter, right: float):
        """Substitute line by line, keeping the template's line breaks, if everything fits."""
        self._terms_seen = 0
        result = []
        for line in par.lines:
            runs = [(s.text, s.style, s.color) for s in line.spans]
            if any(c == PLACEHOLDER_COLOR and " ".join(t.split()) not in self.placeholders
                   for t, _, c in runs):
                return None                     # a placeholder is split across lines
            pieces, line_changed = self._substitute_runs(runs)
            words = ts.words_from_runs(pieces)
            space = self.fonts.width(" ", "n", line.size)
            natural = sum(ts.word_width(w, line.size) for w in words) + space * (len(words) - 1)
            if line_changed and natural > ts.right - ts.left + 0.01:
                return None
            result.append((words, line.x1 >= right - 1))
        return result

    @staticmethod
    def _group_paragraphs(lines: list[Line]) -> list[Paragraph]:
        paragraphs: list[Paragraph] = []
        for line in lines:
            if paragraphs:
                prev = paragraphs[-1].lines[-1]
                same_block = (line.y - prev.y) <= LINE_GAP + 0.6 and abs(line.x0 - prev.x0) < 1 \
                    and abs(line.size - prev.size) < 0.1
                if same_block:
                    paragraphs[-1].lines.append(line)
                    continue
            paragraphs.append(Paragraph(lines=[line]))
        return paragraphs

    # -- fee table --------------------------------------------------------- #
    def _find_table(self, page, lines) -> Table | None:
        if not any(PLACEHOLDER_COLOR == s.color for l in lines for s in l.spans):
            return None
        drawings = page.get_drawings()
        strokes = [d for d in drawings if d.get("color") is not None]
        if not strokes:
            return None
        xs = sorted({round(d["rect"].x0, 2) for d in strokes if d["rect"].width < 0.5})
        ys = sorted({round(d["rect"].y0, 2) for d in strokes if d["rect"].height < 0.5})
        fill = next((d["fill"] for d in drawings if d.get("fill") is not None), (0.94, 0.94, 0.94))
        table = Table(top=ys[0], bottom=ys[-1], col_x=xs, row_y=ys, header_fill=fill,
                      line_color=strokes[0]["color"], line_width=strokes[0]["width"] or 0.75)
        table.lines = [l for l in lines if table.top <= l.y <= table.bottom]
        return table

    def _cell_values(self):
        return {
            "[NO.]": ["1"],
            "[SERVICE DESCRIPTION]": [self.details.service_description],
            "[FEE STRUCTURE]": fee_cell_lines(self.details.fee_type),
        }

    def _data_cells(self, table: Table, ts: Typesetter):
        """Return per-column list of wrapped lines for the data row."""
        values = self._cell_values()
        data_top = table.row_y[1]
        cells = []
        for line in table.lines:
            if line.y < data_top:
                continue
            for s in line.spans:
                key = s.text.strip()
                if key not in values:
                    continue
                col = max(i for i, x in enumerate(table.col_x) if x <= s.x0)
                pad = s.x0 - table.col_x[col]
                width = table.col_x[col + 1] - table.col_x[col] - 2 * pad
                wrapped = []
                for part in values[key]:
                    wrapped += ts.wrap(ts.words_from_runs([(part, "b")]), s.size, width)
                cells.append((s, pad, width, wrapped, line.y))
        return cells

    def _table_growth(self, table: Table, ts: Typesetter) -> float:
        n = max((len(c[3]) for c in self._data_cells(table, ts)), default=1)
        return (n - 1) * LINE_GAP

    def _draw_table(self, page, tw, table: Table, new_top, ts: Typesetter):
        dy = new_top - table.top
        growth = self._table_growth(table, ts)
        rows = [y + dy for y in table.row_y]
        rows[-1] += growth
        x0, x1 = table.col_x[0], table.col_x[-1]
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(x0, rows[0], x1, rows[1]))
        shape.finish(color=None, fill=table.header_fill, width=0)
        for y in rows:
            shape.draw_line((x0, y), (x1, y))
        for x in table.col_x:
            shape.draw_line((x, rows[0]), (x, rows[-1]))
        shape.finish(color=table.line_color, width=table.line_width)
        shape.commit()

        for line in table.lines:                       # header row, unchanged
            if line.y < table.row_y[1]:
                for s in line.spans:
                    ts.draw_pieces(tw, [(s.text, s.style)], s.x0, line.y + dy, s.size)
        for s, pad, width, wrapped, y in self._data_cells(table, ts):
            for i, words in enumerate(wrapped):
                ts.draw_words(tw, words, s.x0, y + dy + i * LINE_GAP, s.size, False, width)

    # -- signature page ---------------------------------------------------- #
    SIG_TABLE_X = (57.6378, 297.6378, 537.6378)   # same column grid as the template's tables
    SIG_CELL_PAD = 8.0
    SIG_SIGN_ROW = 55.0                           # blank space for signature & stamp

    def _fill_signature_table(self, page, lines):
        """Re-lay the two signature blocks as a bordered two-column table."""
        start = next(i for i, l in enumerate(lines)
                     if any("Signed for and on behalf" in s.text for s in l.spans))
        block = lines[start:]
        size = block[0].size
        x0, mid, x1 = self.SIG_TABLE_X
        pad = self.SIG_CELL_PAD
        width = mid - x0 - 2 * pad

        rows = []   # each row: None (signature space) or [left pieces, right pieces]
        for line in block:
            if all(set(s.text.strip()) <= {"_"} for s in line.spans):
                rows.append(None)
                continue
            cells = []
            for side in ([s for s in line.spans if s.x0 < mid - 1],
                         [s for s in line.spans if s.x0 >= mid - 1]):
                self._terms_seen = 0
                pieces, _ = self._substitute_runs([(s.text, s.style, s.color) for s in side])
                if side and side[0].x0 >= mid - 1:     # Rishi Jobs column stays regular weight
                    pieces = [(t, "n") for t, _ in pieces]
                cells.append(pieces)
            rows.append(cells)

        top_y = block[0].bbox.y0 - 4
        area = fitz.Rect(40, top_y - 1, page.rect.width - 40, block[-1].bbox.y1 + 2)
        page.add_redact_annot(area, fill=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)

        ts = Typesetter(self.fonts, 0, page.rect.width)
        line_lead, item_gap, cell_pad_y = 13.0, 20.0, 12.0

        # two blocks per column: "Signed for and on behalf of ..." and the signatory block
        blocks = [[[], []], [[], []]]      # blocks[row][col] -> list of items
        sign_space = [False, False]
        row = 0
        for r in rows:
            if r is None:
                row = 1
                sign_space[1] = True
                continue
            for col, cell in enumerate(r):
                if cell:
                    blocks[row][col].append(ts.wrap(ts.words_from_runs(cell), size, width))

        def column_height(items, with_sign):
            h = self.SIG_SIGN_ROW if with_sign else 0.0
            for i, item in enumerate(items):
                h += (item_gap if i else 0.0) + (len(item) - 1) * line_lead
            return h + size + 2 * cell_pad_y

        heights = [max(column_height(blocks[i][c], sign_space[i]) for c in (0, 1)) for i in (0, 1)]
        row_y = [top_y, top_y + heights[0], top_y + heights[0] + heights[1]]

        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(x0, row_y[0], x1, row_y[2]))
        shape.draw_line((x0, row_y[1]), (x1, row_y[1]))
        shape.draw_line((mid, row_y[0]), (mid, row_y[2]))
        shape.finish(color=(0.6, 0.6, 0.6), width=0.75)
        shape.commit()

        tw = fitz.TextWriter(page.rect)
        for i in (0, 1):
            for col_x, items in zip((x0, mid), blocks[i]):
                y = row_y[i] + cell_pad_y + size * 0.8
                if sign_space[i]:
                    y += self.SIG_SIGN_ROW
                for item in items:
                    for j, words in enumerate(item):
                        ts.draw_words(tw, words, col_x + pad, y + j * line_lead, size, False, width)
                    y += (len(item) - 1) * line_lead + item_gap
        tw.write_text(page, color=BLACK)

    @staticmethod
    def _fit(ts, value, style, width, size, max_lines, min_size, one_line_min=9.0):
        """Pick (size, wrapped lines): shrink a little to stay on one line, then wrap, then shrink."""
        words = ts.words_from_runs([(value, style)])
        s = size
        while s >= one_line_min:
            wrapped = ts.wrap(words, s, width)
            if len(wrapped) == 1:
                return s, wrapped
            s -= 0.25
        s = min(size, one_line_min)
        while True:
            wrapped = ts.wrap(words, s, width)
            if len(wrapped) <= max_lines or s <= min_size:
                return s, wrapped
            s -= 0.25

    # -- client information sheet (last page) ------------------------------ #
    def _fill_information_sheet(self, page, lines):
        d = self.details
        values = {
            "Company Name": d.company_name,
            "Regd. Address": d.registered_address,
            "GST NUMBER": d.gst_number,
        }
        strokes = [dr for dr in page.get_drawings() if dr.get("color") is not None]
        v_lines = [dr["rect"] for dr in strokes if dr["rect"].width < 0.5]
        ts = Typesetter(self.fonts, 0, page.rect.width)
        tw = fitz.TextWriter(page.rect)
        for line in lines:
            label = line.spans[0].text.strip()
            if label not in values or not values[label]:
                continue
            row_x = sorted(r.x0 for r in v_lines if r.y0 <= line.y <= r.y1)
            dividers = [x for x in row_x if x > line.x1]
            if len(row_x) < 3 or not dividers:
                continue
            right_edge = row_x[-1]
            pad = line.x0 - row_x[0]
            x = dividers[0] + pad
            width = right_edge - x - pad
            s, wrapped = self._fit(ts, values[label], "n", width, line.size,
                                   max_lines=3, min_size=6.5)
            lead = s * 1.15
            top = line.y - (len(wrapped) - 1) * lead / 2    # keep the text centred in the row
            for i, wline in enumerate(wrapped):
                ts.draw_words(tw, wline, x, top + i * lead, s, False, width)
        tw.write_text(page, color=BLACK)


_generator: ContractGenerator | None = None


def generate_contract(details: ContractDetails | dict) -> bytes:
    global _generator
    if isinstance(details, dict):
        details = ContractDetails.from_dict(details)
    if _generator is None:
        _generator = ContractGenerator()
    return _generator.generate(details)


def contract_filename(details: ContractDetails) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", details.company_name).strip("_") or "Client"
    return f"Placement_Services_Agreement_{safe}_{details.contract_date.isoformat()}.pdf"
