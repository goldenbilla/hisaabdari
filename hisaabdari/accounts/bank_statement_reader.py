# Copyright (c) 2026, HisaabDari contributors
# See license.txt

"""Read a bank statement file (CSV, Excel or text PDF) into a clean list of transaction lines.

Pure functions: no database access, no site needed. The only entry point other code should use is
`read_statement`; it raises `StatementReadError` with a plain-language message when nothing usable
can be read.
"""

import csv
import io
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

PREVIEW_ROWS = 15
HEADING_SCAN_ROWS = 80
BALANCE_TOLERANCE = 0.006


class StatementReadError(Exception):
	"""The file could not be read as a bank statement. The message is written for the end user."""


# --------------------------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------------------------


def read_statement(
	file_name: str, content: bytes, layout: dict | None = None, password: str | None = None
) -> dict:
	"""Turn a bank statement file into transaction lines. See dev/BANK_REC_BRIEF.md for the contract."""
	if isinstance(content, str):
		content = content.encode("utf-8")
	if not content or not content.strip():
		raise StatementReadError("The file is empty.")

	file_type = _file_type(file_name, content)
	if file_type == "pdf":
		table = _pdf_table(content, password)
	else:
		table = _tabular_table(file_type, content, layout)
	return _build_result(file_type, table, layout)


# --------------------------------------------------------------------------------------------
# small helpers: text, amounts, dates
# --------------------------------------------------------------------------------------------


def _text(value) -> str:
	if value is None:
		return ""
	if isinstance(value, datetime):
		return value.date().isoformat()
	if isinstance(value, date):
		return value.isoformat()
	if isinstance(value, bool):
		return str(value)
	if isinstance(value, float):
		if value == int(value) and abs(value) < 1e15:
			return str(int(value))
		return ("%.6f" % value).rstrip("0").rstrip(".")
	return re.sub(r"\s+", " ", str(value)).strip()


_MARKER_RE = re.compile(r"(?i)(?<![a-z])(dr|cr|db|debit|credit)(?![a-z])\.?")
_CURRENCY_RE = re.compile(r"(?i)(?<![a-z])(?:rs|pkr|usd|inr|aed|sar|eur|gbp)(?![a-z])\.?|[$€£₨₹]|/-|/=")
_PLAIN_NUMBER_RE = re.compile(r"^(?:\d{1,3}(?:,\d{2,3})*,\d{3}|\d+)(?:\.\d+)?$|^\.\d+$")
_EURO_NUMBER_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,2}$")
_EMPTY_AMOUNTS = {"", "-", "--", "---", "nil", "n/a", "na", "null", "none"}


def _amount(value):
	"""Parse an amount cell. Returns (signed float | None, "DR" | "CR" | None)."""
	if value is None or isinstance(value, (bool, date, datetime)):
		return None, None
	if isinstance(value, (int, float)):
		return float(value), None
	s = str(value).replace("−", "-").replace("–", "-").replace("\xa0", " ").strip()
	if s.lower() in _EMPTY_AMOUNTS:
		return None, None
	marker = None
	m = _MARKER_RE.search(s)
	if m:
		marker = "DR" if m.group(1).lower() in ("dr", "db", "debit") else "CR"
		s = s[: m.start()] + s[m.end() :]
	s = _CURRENCY_RE.sub("", s).strip()
	negative = False
	if s.startswith("(") and s.endswith(")"):
		negative, s = True, s[1:-1]
	s = s.strip()
	if s.startswith("-") or s.endswith("-"):
		negative, s = True, s.strip("-")
	s = s.strip().lstrip("+").replace(" ", "")
	if _PLAIN_NUMBER_RE.match(s):
		number = float(s.replace(",", ""))
	elif _EURO_NUMBER_RE.match(s):
		number = float(s.replace(".", "").replace(",", "."))
	else:
		return None, None
	if negative:
		number = -number
	if marker == "DR":
		number = -abs(number)
	elif marker == "CR":
		number = abs(number)
	return number, marker


def parse_amount(value) -> float | None:
	"""Signed amount from text such as "1,250.00", "(1,250.00)", "1,250.00-", "Rs. 1,250.00 DR"."""
	return _amount(value)[0]


def _is_money(text: str) -> bool:
	"""Strict test used for PDF words: looks like a printed amount (has a decimal part or thousands comma)."""
	return bool(re.search(r"\d[.,]\d", text)) and _amount(text)[0] is not None


_MONTHS = {
	name: i + 1
	for i, names in enumerate(
		[
			("jan", "january"),
			("feb", "february"),
			("mar", "march"),
			("apr", "april"),
			("may",),
			("jun", "june"),
			("jul", "july"),
			("aug", "august"),
			("sep", "sept", "september"),
			("oct", "october"),
			("nov", "november"),
			("dec", "december"),
		]
	)
	for name in names
}
_TIME_RE = re.compile(r"(?i)[t\s]+\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:\s*[ap]m)?$")
_EXCEL_EPOCH = date(1899, 12, 30)


def _year(text: str) -> int:
	y = int(text)
	if len(text) <= 2:
		y += 2000 if y < 70 else 1900
	return y


def _valid(y, m, d):
	try:
		return date(y, m, d)
	except ValueError:
		return None


def _date_parts(value, loose=False):
	"""Recognise a date cell.

	Returns None, ("fixed", date) or ("amb", a, b, year, sep, year_digits) for all-numeric dates
	where day and month order must be decided from the whole column.
	"""
	if value is None or isinstance(value, bool):
		return None
	if isinstance(value, datetime):
		return ("fixed", value.date())
	if isinstance(value, date):
		return ("fixed", value)
	if isinstance(value, (int, float)):
		if 20000 <= value <= 80000:
			return ("fixed", _EXCEL_EPOCH + timedelta(days=int(value)))
		return None
	s = _TIME_RE.sub("", str(value).strip()).strip().strip(",")
	if not s:
		return None
	m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
	if m:
		d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
		return ("fixed", d) if d else None
	m = re.match(r"^(\d{1,2})([-/. ])(\d{1,2})\2(\d{4}|\d{2})$", s)
	if m:
		a, b, y = int(m.group(1)), int(m.group(3)), _year(m.group(4))
		if _valid(y, b, a) or _valid(y, a, b):
			return ("amb", a, b, y, m.group(2), len(m.group(4)))
		return None
	m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?[-/. ]*([A-Za-z]{3,9})[-/., ]*(\d{4}|\d{2})$", s)
	if m and m.group(2).lower() in _MONTHS:
		d = _valid(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
		return ("fixed", d) if d else None
	m = re.match(r"^([A-Za-z]{3,9})[-/. ]*(\d{1,2})(?:st|nd|rd|th)?[-/., ]+(\d{4})$", s)
	if m and m.group(1).lower() in _MONTHS:
		d = _valid(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
		return ("fixed", d) if d else None
	if re.match(r"^\d{8}$", s):
		d = None
		if 1990 <= int(s[:4]) <= 2100:
			d = _valid(int(s[:4]), int(s[4:6]), int(s[6:]))
		if not d and 1990 <= int(s[4:]) <= 2100:
			d = _valid(int(s[4:]), int(s[2:4]), int(s[:2]))
		return ("fixed", d) if d else None
	if re.match(r"^\d{5}(?:\.0+)?$", s) and 20000 <= float(s) <= 80000:
		return ("fixed", _EXCEL_EPOCH + timedelta(days=int(float(s))))
	if loose and " " in s:
		# PDF: a date followed by something else in the same cell ("31 OCT 2026 31 OCT 2026")
		tokens = s.split()
		for n in (3, 1):
			if len(tokens) > n:
				parts = _date_parts(" ".join(tokens[:n]))
				if parts:
					return parts
	return None


def _resolve_date(parts, day_first: bool, date_format: str | None = None, raw=None):
	if parts is None:
		return None
	if date_format and isinstance(raw, str):
		try:
			return datetime.strptime(_TIME_RE.sub("", raw.strip()), date_format).date()
		except ValueError:
			pass
	if parts[0] == "fixed":
		return parts[1]
	_, a, b, y = parts[:4]
	if day_first:
		return _valid(y, b, a) or _valid(y, a, b)
	return _valid(y, a, b) or _valid(y, b, a)


def _decide_day_first(all_parts):
	"""(day_first, date_format, mixed) from every recognised date of the date column."""
	first_big = second_big = 0
	sample = None
	for parts in all_parts:
		if not parts or parts[0] != "amb":
			continue
		sample = sample or parts
		if parts[1] > 12:
			first_big += 1
		if parts[2] > 12:
			second_big += 1
	day_first = not (second_big > first_big)
	date_format = None
	if sample:
		sep, year = sample[4], "%Y" if sample[5] == 4 else "%y"
		order = ("%d", "%m") if day_first else ("%m", "%d")
		date_format = f"{order[0]}{sep}{order[1]}{sep}{year}"
	return day_first, date_format, bool(first_big and second_big)


# --------------------------------------------------------------------------------------------
# column headings
# --------------------------------------------------------------------------------------------

_DR_WORDS = {"dr", "debit", "debits", "withdrawal", "withdrawals", "withdraw", "withdrawl"}
_CR_WORDS = {"cr", "credit", "credits", "deposit", "deposits"}
_REF_WORDS = {
	"cheque",
	"chq",
	"check",
	"instrument",
	"inst",
	"ref",
	"reference",
	"voucher",
	"doc",
	"document",
}
_DESC_WORDS = {
	"description",
	"particulars",
	"particular",
	"narration",
	"narrative",
	"details",
	"detail",
	"remarks",
	"memo",
	"transaction",
	"transactions",
}
_TYPE_LABELS = {"type", "txn type", "tran type", "trans type", "transaction type", "d/c", "dc", "sign"}
_OTHER_ROLES = {"description", "withdrawal", "deposit", "balance", "reference", "amount", "dr_cr"}


def _norm_label(label: str) -> str:
	return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/#]+", " ", (label or "").lower())).strip()


def _role(label: str):
	n = _norm_label(label)
	if not n or len(n) > 40:
		return None
	words = set(n.replace("/", " ").split())
	has_dr = bool(words & _DR_WORDS) or "paid out" in n or "money out" in n
	has_cr = bool(words & _CR_WORDS) or "paid in" in n or "money in" in n
	if (has_dr and has_cr) or n in _TYPE_LABELS:
		return "dr_cr"
	if "balance" in words or "bal" in words:
		return "balance"
	if "date" in words:
		if words & _REF_WORDS:
			return None
		return "value_date" if words & {"value", "val", "effective"} else "date"
	if has_dr:
		return "withdrawal"
	if has_cr:
		return "deposit"
	if words & {"amount", "amt"}:
		return "amount"
	if words & _REF_WORDS or ("id" in words and words & {"transaction", "txn", "tran"}):
		return "reference"
	if words & _DESC_WORDS:
		return "description"
	return None


def _heading_score(labels) -> int:
	"""0 when the labels are not a column-heading line, else the number of recognised other columns."""
	roles = [_role(label) for label in labels]
	if "date" not in roles and "value_date" not in roles:
		return 0
	for label in labels:
		if _date_parts(label) or (re.search(r"\d", label or "") and _amount(label)[0] is not None):
			return 0
	return len(set(roles) & _OTHER_ROLES)


def _layout_from_labels(labels) -> dict:
	roles = [_role(label) for label in labels]

	def first(role):
		return roles.index(role) if role in roles else None

	layout = {
		"header_row": None,
		"date": first("date") if "date" in roles else first("value_date"),
		"description": [i for i, r in enumerate(roles) if r == "description"],
		"reference": first("reference"),
		"withdrawal": first("withdrawal"),
		"deposit": first("deposit"),
		"amount": first("amount"),
		"balance": first("balance"),
		"dr_cr": first("dr_cr"),
		"date_format": None,
		"day_first": True,
	}
	if layout["withdrawal"] is not None and layout["deposit"] is not None:
		layout["amount"] = None
	return layout


# --------------------------------------------------------------------------------------------
# tabular files: csv, xlsx, xls
# --------------------------------------------------------------------------------------------


def _file_type(file_name: str, content: bytes) -> str:
	ext = (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""
	head = content[:8]
	if head.startswith(b"%PDF") or b"%PDF-" in content[:1024]:
		return "pdf"
	if head.startswith(b"PK\x03\x04"):
		return "xlsx"
	if head.startswith(b"\xd0\xcf\x11\xe0"):
		return "xls"
	if ext == "pdf":
		return "pdf"
	if ext in ("xlsx", "xlsm"):
		return "xlsx"
	if ext == "xls":
		return "xls"
	return "csv"


def _decode(content: bytes) -> str:
	for encoding in ("utf-8-sig", "utf-16", "cp1252"):
		try:
			text = content.decode(encoding)
		except (UnicodeDecodeError, UnicodeError):
			continue
		if encoding == "utf-16" and not content[:2] in (b"\xff\xfe", b"\xfe\xff"):
			continue
		return text
	return content.decode("latin-1", errors="replace")


def _csv_rows(content: bytes):
	text = _decode(content).replace("\r\n", "\n").replace("\r", "\n")
	if "\x00" in text:
		raise StatementReadError("This file is not a readable CSV, Excel or PDF bank statement.")
	if re.search(r"(?i)<table[\s>]", text[:20000]):
		return _html_rows(text)
	best, best_score = ",", -1
	sample = "\n".join(text.split("\n")[:60])
	for delimiter in (",", ";", "\t", "|"):
		widths = Counter(len(r) for r in csv.reader(io.StringIO(sample), delimiter=delimiter) if len(r) > 1)
		if not widths:
			continue
		width, count = widths.most_common(1)[0]
		score = (width - 1) * count
		if score > best_score:
			best, best_score = delimiter, score
	return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=best)]


class _TableParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.rows, self.row, self.cell = [], None, None

	def handle_starttag(self, tag, attrs):
		if tag == "tr":
			self.row = []
		elif tag in ("td", "th") and self.row is not None:
			self.cell = []
		elif tag == "br" and self.cell is not None:
			self.cell.append(" ")

	def handle_endtag(self, tag):
		if tag in ("td", "th") and self.cell is not None and self.row is not None:
			self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
			self.cell = None
		elif tag == "tr" and self.row is not None:
			self.rows.append(self.row)
			self.row = None

	def handle_data(self, data):
		if self.cell is not None:
			self.cell.append(data)


def _html_rows(text: str):
	parser = _TableParser()
	parser.feed(text)
	return parser.rows


def _xlsx_sheets(content: bytes):
	import openpyxl

	try:
		book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	except Exception:
		raise StatementReadError(
			"This Excel file could not be opened. Save it again as .xlsx or .csv and upload that."
		) from None
	for sheet in book.worksheets:
		rows = []
		for row in sheet.iter_rows(values_only=True):
			rows.append([c.strip() if isinstance(c, str) else c for c in row])
		yield rows


def _xls_sheets(content: bytes):
	import xlrd

	try:
		book = xlrd.open_workbook(file_contents=content)
	except Exception:
		raise StatementReadError(
			"This Excel file could not be opened. Save it again as .xlsx or .csv and upload that."
		) from None
	for sheet in book.sheets():
		rows = []
		for r in range(sheet.nrows):
			row = []
			for cell in sheet.row(r):
				value = cell.value
				if cell.ctype == xlrd.XL_CELL_DATE:
					try:
						value = xlrd.xldate_as_datetime(value, book.datemode)
					except Exception:
						pass
				elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
					value = None
				elif isinstance(value, str):
					value = value.strip()
				row.append(value)
			rows.append(row)
		yield rows


def _find_heading_row(rows):
	fallback = None
	for i, row in enumerate(rows[:HEADING_SCAN_ROWS]):
		score = _heading_score([_text(c) for c in row])
		if score >= 2:
			return i
		if score == 1 and fallback is None:
			fallback = i
	return fallback


def _trim(rows):
	rows = [list(r) for r in rows]
	while rows and not any(_text(c) for c in rows[-1]):
		rows.pop()
	width = 0
	for row in rows:
		for i in range(len(row), 0, -1):
			if _text(row[i - 1]):
				width = max(width, i)
				break
	return [(row + [None] * width)[:width] for row in rows]


def _tabular_table(file_type: str, content: bytes, layout: dict | None) -> dict:
	if file_type == "csv":
		sheets = [_csv_rows(content)]
	elif file_type == "xlsx":
		sheets = list(_xlsx_sheets(content))
	else:
		head = content[:2048].lstrip().lower()
		if content[:4] != b"\xd0\xcf\x11\xe0" and (head.startswith(b"<") or b"<table" in head):
			sheets = [_html_rows(_decode(content))]  # an HTML table saved with an .xls name
		elif content[:4] != b"\xd0\xcf\x11\xe0":
			sheets = [_csv_rows(content)]
		else:
			sheets = list(_xls_sheets(content))

	sheets = [s for s in (_trim(s) for s in sheets) if s]
	if not sheets:
		raise StatementReadError("The file has no rows to read.")
	rows, heading_row = sheets[0], _find_heading_row(sheets[0])
	if heading_row is None:
		for candidate in sheets[1:]:
			found = _find_heading_row(candidate)
			if found is not None:
				rows, heading_row = candidate, found
				break

	warnings, trust_balance = [], False
	if layout:
		detected = dict(layout)
		heading_row = detected.get("header_row")
	elif heading_row is not None:
		detected = _layout_from_labels([_text(c) for c in rows[heading_row]])
		detected["header_row"] = heading_row
	else:
		detected = _guess_layout(rows)
		trust_balance = True
		warnings.append(
			"No column headings were found, so the columns were worked out from the data. "
			"Please check the columns."
		)

	if heading_row is not None and 0 <= heading_row < len(rows):
		columns = [_text(c) or f"Column {i + 1}" for i, c in enumerate(rows[heading_row])]
		start = heading_row + 1
		header_lines = [[t for t in (_text(c) for c in row) if t] for row in rows[:heading_row]]
	else:
		columns = [f"Column {i + 1}" for i in range(len(rows[0]))]
		start = 0
		header_lines = []
	return {
		"rows": rows,
		"start": start,
		"columns": columns,
		"layout": detected,
		"header_lines": header_lines,
		"preview": rows[:PREVIEW_ROWS],
		"warnings": warnings,
		"trust_balance": trust_balance,
		"cont_ok": None,
		"loose_dates": False,
	}


def _guess_layout(rows) -> dict:
	"""No heading row: find the date column and the amount columns from the values themselves."""
	width = max(len(r) for r in rows)
	dates, numbers, text_len = Counter(), Counter(), Counter()
	for row in rows:
		for i, cell in enumerate(row):
			if cell is None or cell == "":
				continue
			if not isinstance(cell, (int, float)) and _date_parts(cell):
				dates[i] += 1
			elif _amount(cell)[0] is not None:
				numbers[i] += 1
			else:
				text_len[i] += len(_text(cell))
	date_col = max(range(width), key=lambda i: dates[i]) if dates else None
	if date_col is None or dates[date_col] < 1:
		raise StatementReadError(
			"No date column was found in this file. Check that it is a bank statement with one "
			"transaction per row and a date on each row."
		)
	need = max(1, dates[date_col] * 0.3)
	numeric = [i for i in range(width) if i != date_col and numbers[i] >= need]
	texts = [i for i in range(width) if i != date_col and i not in numeric and text_len[i]]
	layout = _layout_from_labels([])
	layout["date"] = date_col
	layout["description"] = [max(texts, key=lambda i: text_len[i])] if texts else []
	if len(numeric) == 1:
		layout["amount"] = numeric[0]
	elif len(numeric) == 2:
		both = sum(
			1
			for row in rows
			if (_amount(row[numeric[0]])[0] or 0) != 0 and (_amount(row[numeric[1]])[0] or 0) != 0
		)
		if both >= need:
			layout["amount"], layout["balance"] = numeric
		else:
			layout["withdrawal"], layout["deposit"] = numeric
	elif len(numeric) >= 3:
		layout["withdrawal"], layout["deposit"], layout["balance"] = numeric[-3:]
	return layout


# --------------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------------

_PAGE_NO_RE = re.compile(r"(?i)\bpage\s*(?:no\.?\s*)?:?\s*\d+(?:\s*(?:of|/)\s*\d+)?\b")
_HEADING_EXTRA_WORDS = (
	{"value", "date", "no", "no.", "number", "#", "amount", "balance", "running", "transaction", "txn"}
	| {"posting", "(pkr)", "pkr", "(rs)", "(rs.)", "rs", "rs.", "/"}
	| _DR_WORDS
	| _CR_WORDS
	| _REF_WORDS
	| _DESC_WORDS
)
COLUMN_PAD = 4.0


def _pdf_open_password(content: bytes, password: str | None) -> str:
	"""Check encryption with pypdf. Returns the password that opens the file ("" when none needed)."""
	try:
		from pypdf import PdfReader

		reader = PdfReader(io.BytesIO(content))
		if not reader.is_encrypted:
			return ""
	except Exception:
		return password or ""
	for candidate in [password] if password else [""]:
		try:
			if reader.decrypt(candidate):
				return candidate
		except Exception:
			pass
	if password:
		raise StatementReadError("The password for this PDF is not correct. Check it and try again.")
	raise StatementReadError(
		"This PDF is password-protected. Enter the password the bank gave you for this statement "
		"and try again."
	)


def _pdf_word_pages(content: bytes, password: str):
	import pdfplumber

	pages = []
	with pdfplumber.open(io.BytesIO(content), password=password or None) as pdf:
		for page in pdf.pages:
			words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
			pages.append(
				[
					{
						"text": unicodedata.normalize("NFKC", w["text"]),
						"x0": float(w["x0"]),
						"x1": float(w["x1"]),
						"top": float(w["top"]),
						"bottom": float(w["bottom"]),
					}
					for w in words
					if w["text"].strip()
				]
			)
	return pages


def _pdf_text_pages(content: bytes, password: str):
	from pypdf import PdfReader

	reader = PdfReader(io.BytesIO(content))
	if reader.is_encrypted:
		reader.decrypt(password or "")
	pages = []
	for page in reader.pages:
		text = page.extract_text() or ""
		text = unicodedata.normalize("NFKC", text)
		pages.append([{"text": t.strip(), "words": []} for t in text.splitlines() if t.strip()])
	return pages


def _group_lines(words):
	lines = []
	for w in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
		mid = (w["top"] + w["bottom"]) / 2
		if lines and abs(mid - lines[-1]["mid"]) <= 3:
			lines[-1]["words"].append(w)
		else:
			lines.append({"mid": mid, "words": [w]})
	for line in lines:
		line["words"].sort(key=lambda w: w["x0"])
		line["top"] = min(w["top"] for w in line["words"])
		line["bottom"] = max(w["bottom"] for w in line["words"])
		line["height"] = max(w["bottom"] - w["top"] for w in line["words"])
		line["text"] = " ".join(w["text"] for w in line["words"])
	return lines


def _chunks(words, min_gap=None):
	"""Join neighbouring words into cells' worth of text; a wide gap starts a new chunk."""
	chunks = []
	for w in sorted(words, key=lambda w: w["x0"]):
		gap_limit = min_gap if min_gap is not None else max(3.2, 0.42 * (w["bottom"] - w["top"]))
		if chunks and w["x0"] - chunks[-1]["x1"] <= gap_limit:
			chunks[-1]["words"].append(w)
			chunks[-1]["x1"] = max(chunks[-1]["x1"], w["x1"])
		else:
			chunks.append({"x0": w["x0"], "x1": w["x1"], "words": [w]})
	for c in chunks:
		ordered = sorted(c["words"], key=lambda w: (round((w["top"] + w["bottom"]) / 2 / 3), w["x0"]))
		c["text"] = " ".join(w["text"] for w in ordered)
	return chunks


def _find_pdf_heading(lines):
	"""Index range (first, last) of the column-heading line(s) and the column labels with positions."""
	for i, line in enumerate(lines):
		if re.search(r"\d", line["text"]) or not re.search(r"(?i)\bdate\b", line["text"]):
			continue
		if _heading_score([c["text"] for c in _chunks(line["words"])]) < 2:
			# the gaps may be too narrow to separate the labels: judge the words on their own
			if _heading_score([w["text"] for w in line["words"]]) < 2:
				continue
		first = last = i
		words = list(line["words"])
		# headings wrapped over two or three lines ("Value" above "Date", "Cheque" above "No")
		for step in (-1, 1):
			j = i + step
			while 0 <= j < len(lines) and abs(j - i) <= 2:
				other = lines[j]
				near = abs(other["mid"] - lines[j - step]["mid"]) <= 1.35 * max(line["height"], 6)
				tokens = [w["text"].lower().strip(".:") for w in other["words"]]
				if not near or len(tokens) > 6 or not all(t in _HEADING_EXTRA_WORDS for t in tokens):
					break
				words += other["words"]
				first, last = min(first, j), max(last, j)
				j += step
		labels = _chunks(words)
		if _heading_score([c["text"] for c in labels]) >= 2:
			return first, last, [{"label": c["text"], "x0": c["x0"], "x1": c["x1"]} for c in labels]
	return None


def _pdf_cells(words, cols, numeric):
	cells = [[] for _ in cols]
	for chunk in _chunks(words):
		index = None
		if numeric and _is_money(chunk["text"]):
			centre = (chunk["x0"] + chunk["x1"]) / 2

			def distance(i):
				col = cols[i]
				return min(
					abs(chunk["x1"] - col["x1"]),
					abs(chunk["x0"] - col["x0"]),
					abs(centre - (col["x0"] + col["x1"]) / 2),
				)

			best = min(numeric, key=distance)
			if distance(best) <= 45:
				index = best
		if index is None:
			if len(cols) > 1 and chunk["x0"] < cols[1]["x0"] - COLUMN_PAD:
				index = 0
			else:
				best_overlap = None
				for i, col in enumerate(cols):
					left = col["x0"] - COLUMN_PAD if i else float("-inf")
					right = cols[i + 1]["x0"] - COLUMN_PAD if i + 1 < len(cols) else float("inf")
					overlap = min(chunk["x1"], right) - max(chunk["x0"], left)
					if best_overlap is None or overlap > best_overlap:
						best_overlap, index = overlap, i
		cells[index].append(chunk)
	return [" ".join(c["text"] for c in sorted(cell, key=lambda c: c["x0"])) for cell in cells]


def _drop_page_furniture(pages):
	"""Remove page numbers and lines printed identically on several pages (repeated headers/footers)."""
	seen = Counter()
	for lines in pages:
		for text in {line["text"] for line in lines}:
			seen[text] += 1
	cleaned = []
	for lines in pages:
		kept = []
		for line in lines:
			text = line["text"]
			if _PAGE_NO_RE.search(text) and len(_PAGE_NO_RE.sub("", text).strip()) < 40:
				continue
			if seen[text] > 1 and not _date_parts(text, loose=True):
				continue
			kept.append(line)
		cleaned.append(kept)
	return cleaned


def _pdf_layout_word_pages(content: bytes, password: str):
	"""pypdf fallback: text laid out in character columns, turned into words with pretend positions."""
	from pypdf import PdfReader

	reader = PdfReader(io.BytesIO(content))
	if reader.is_encrypted:
		reader.decrypt(password or "")
	pages = []
	for page in reader.pages:
		words = []
		for n, text in enumerate((page.extract_text(extraction_mode="layout") or "").splitlines()):
			for m in re.finditer(r"\S+", text):
				words.append(
					{
						"text": unicodedata.normalize("NFKC", m.group(0)),
						"x0": m.start() * 4.0,
						"x1": m.end() * 4.0,
						"top": n * 12.0,
						"bottom": n * 12.0 + 10.0,
					}
				)
		pages.append(words)
	return pages


def _pdf_table(content: bytes, password: str | None) -> dict:
	opened_with = _pdf_open_password(content, password)
	fallback_note = (
		"This PDF could not be read in the usual way, so a simpler method was used. "
		"Please check the lines."
	)
	pages = None
	try:
		pages = [_group_lines(words) for words in _pdf_word_pages(content, opened_with)]
	except Exception:
		pages = None
	if pages and any(pages):
		table = _pdf_positioned_table(pages)
		if table:
			return table
		pages = [[{"text": line["text"], "words": []} for line in lines] for lines in pages]
	else:
		try:
			table = _pdf_positioned_table(
				[_group_lines(words) for words in _pdf_layout_word_pages(content, opened_with)]
			)
		except Exception:
			table = None
		if table:
			table["warnings"].append(fallback_note)
			return table
		try:
			pages = _pdf_text_pages(content, opened_with)
		except Exception:
			raise StatementReadError(
				"This PDF could not be opened. Download the statement again from your bank and retry."
			) from None
	if not pages or not any(pages):
		raise StatementReadError(
			"This PDF has no readable text; it looks like a scanned image. Download the statement "
			"from your bank's online banking as a PDF, Excel or CSV file instead."
		)
	table = _pdf_text_table(pages)
	table["warnings"] = [fallback_note] + table["warnings"]
	return table


def _pdf_positioned_table(pages):
	heading = None
	heading_page = 0
	for heading_page, lines in enumerate(pages):
		heading = _find_pdf_heading(lines)
		if heading:
			break
	if not heading:
		return None
	first, _last, cols = heading
	header_lines = [line for lines in pages[:heading_page] for line in lines] + pages[heading_page][:first]
	header_segments = [[c["text"] for c in _chunks(line["words"], min_gap=12)] for line in header_lines]

	body_pages = []
	for p, lines in enumerate(pages):
		if p < heading_page:
			body_pages.append([])
			continue
		page_heading = _find_pdf_heading(lines)
		page_cols = cols
		if page_heading:
			lines = lines[page_heading[1] + 1 :]
			if len(page_heading[2]) == len(cols):
				page_cols = [dict(c, label=cols[i]["label"]) for i, c in enumerate(page_heading[2])]
		body_pages.append([dict(line, cols=page_cols) for line in lines])
	body_pages = _drop_page_furniture(body_pages)

	labels = [c["label"] for c in cols]
	roles = [_role(label) for label in labels]
	numeric = [i for i, r in enumerate(roles) if r in ("withdrawal", "deposit", "amount", "balance")]
	rows, cont_ok = [], []
	for lines in body_pages:
		previous = None
		for line in lines:
			rows.append(_pdf_cells(line["words"], line["cols"], numeric))
			cont_ok.append(
				previous is not None
				and line["top"] - previous["bottom"] <= 1.2 * max(line["height"], previous["height"])
			)
			previous = line
	return {
		"rows": rows,
		"start": 0,
		"columns": labels,
		"layout": _layout_from_labels(labels),
		"header_lines": header_segments,
		"preview": rows[:PREVIEW_ROWS],
		"warnings": [],
		"trust_balance": True,
		"cont_ok": cont_ok,
		"loose_dates": True,
	}


def _pdf_text_table(pages):
	"""Fallback without word positions: a date at the start of a line, amounts at its end."""
	lines = [line["text"] for page in _drop_page_furniture(pages) for line in page]
	start = None
	for i, text in enumerate(lines):
		if not re.search(r"\d", text) and _heading_score(text.split()) >= 2:
			start = i + 1
			break
	if start is None:
		for i, text in enumerate(lines):
			if _split_text_line(text)[0] and _split_text_line(text)[2]:
				start = i
				break
	if start is None:
		raise StatementReadError(
			"No transaction lines with a date were found in this PDF. Check that it is a bank "
			"statement, or download it from your bank as Excel or CSV instead."
		)
	header_lines = [[t] for t in lines[: max(start - 1, 0) if start else 0]]
	rows = []
	for text in lines[start:]:
		date_text, description, amounts = _split_text_line(text)
		if date_text:
			movement = [a for a in amounts[:-1] if (_amount(a)[0] or 0) != 0] if len(amounts) > 1 else amounts
			amount = movement[-1] if movement else ""
			rows.append([date_text, description, amount, amounts[-1] if len(amounts) > 1 else ""])
		else:
			rows.append(["", description, "", amounts[-1] if amounts else ""])
	layout = _layout_from_labels(["Date", "Description", "Amount", "Balance"])
	return {
		"rows": rows,
		"start": 0,
		"columns": ["Date", "Description", "Amount", "Balance"],
		"layout": layout,
		"header_lines": header_lines,
		"preview": rows[:PREVIEW_ROWS],
		"warnings": [],
		"trust_balance": True,
		"cont_ok": None,
		"loose_dates": True,
	}


def _split_text_line(text: str):
	tokens = text.split()
	date_text = ""
	for n in (3, 1):
		if len(tokens) >= n and _date_parts(" ".join(tokens[:n])):
			date_text, tokens = " ".join(tokens[:n]), tokens[n:]
			break
	if date_text:
		# a value date printed right after the transaction date
		for n in (3, 1):
			if len(tokens) > n and _date_parts(" ".join(tokens[:n])):
				tokens = tokens[n:]
				break
	amounts = []
	while tokens:
		if _is_money(tokens[-1]):
			amounts.insert(0, tokens.pop())
		elif len(tokens) > 1 and tokens[-1].upper().strip(".") in ("DR", "CR") and _is_money(tokens[-2]):
			marker = tokens.pop()
			amounts.insert(0, tokens.pop() + " " + marker)
		else:
			break
	return date_text, " ".join(tokens), amounts


# --------------------------------------------------------------------------------------------
# header block (bank, account, period, balances)
# --------------------------------------------------------------------------------------------

_DATE_TOKEN_RE = re.compile(
	r"(?i)\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
	r"|\d{1,2}[-/. ](?:\d{1,2}|[a-z]{3,9})[-/., ]+\d{2,4}"
	r"|\d{1,2}[a-z]{3}\d{4}"
	r"|[a-z]{3,9} \d{1,2},? \d{4})\b"
)
_AMOUNT_TOKEN_RE = re.compile(
	r"(?i)[(-]?\s*(?:(?:rs|pkr)\.?\s*)?\d[\d,]*(?:\.\d+)?\s*\)?-?(?:\s*(?:dr|cr)\b)?"
)
_OPENING_RE = (
	r"opening\s+bal(?:ance)?|bal(?:ance)?\s+b\s*/?\s*f(?:wd)?\b|b\s*/\s*f\b"
	r"|(?:bal(?:ance)?\s+)?brought\s+forward|previous\s+balance|balance\s+forward"
)
_CLOSING_RE = (
	r"closing\s+bal(?:ance)?|bal(?:ance)?\s+c\s*/?\s*f(?:wd)?\b|c\s*/\s*f\b"
	r"|(?:bal(?:ance)?\s+)?carried\s+forward|ending\s+balance"
)
_LABEL_START_RE = re.compile(
	r"(?i)\b(?:account|a/c|acct|iban|branch|currency|statement|period|from|to|opening|closing|title"
	r"|customer|address|date|page|cnic|ntn|phone|mobile|email|swift)\b[^:]{0,25}:"
)
_CURRENCIES = ("PKR", "USD", "EUR", "GBP", "AED", "SAR", "CNY", "INR")


def _labelled(lines, label_re: str):
	"""Value printed after a label, in the same segment ("Label: value") or the next one."""
	pattern = re.compile(r"(?i)(?:^|[\s(])(?:" + label_re + r")\s*[:\-–#.]*\s*(.*)$")
	for segments in lines:
		for i, segment in enumerate(segments):
			m = pattern.search(segment)
			if not m:
				continue
			value = m.group(1).strip()
			cut = _LABEL_START_RE.search(value)
			if cut and cut.start() > 0:
				value = value[: cut.start()].strip()
			if not value and i + 1 < len(segments):
				value = segments[i + 1].strip().lstrip(":").strip()
			if value:
				return value
	return None


def _first_amount(text: str | None):
	if not text:
		return None
	text = _DATE_TOKEN_RE.sub(" ", text)
	for m in _AMOUNT_TOKEN_RE.finditer(text):
		value = _amount(m.group(0))[0]
		if value is not None:
			return round(value, 2)
	return None


def _header_date(text: str | None, day_first: bool):
	if not text:
		return None
	m = _DATE_TOKEN_RE.search(text)
	d = _resolve_date(_date_parts(m.group(0) if m else text.strip(), loose=True), day_first)
	return d.isoformat() if d else None


def _parse_header(lines, day_first: bool) -> dict:
	header = dict.fromkeys(
		(
			"bank_name",
			"account_title",
			"account_number",
			"iban",
			"period_from",
			"period_to",
			"opening_balance",
			"closing_balance",
			"currency",
		)
	)
	lines = [[s for s in segments if s] for segments in lines if any(segments)]
	texts = ["  ".join(segments) for segments in lines]
	full = "\n".join(texts)

	m = re.search(r"\bPK\s?\d{2}\s?[A-Z]{4}(?:\s?\d){16}\b", full) or re.search(
		r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b", full
	)
	if m:
		header["iban"] = re.sub(r"\s", "", m.group(0))

	value = _labelled(lines, r"(?:account|a/c|acct)\.?\s*(?:no\b\.?|number|num\b\.?|#)")
	if value:
		m = re.match(r"[0-9][0-9\-]*(?: [0-9][0-9\-]*)*", value)
		if m and len(re.sub(r"\D", "", m.group(0))) >= 5:
			header["account_number"] = m.group(0).strip()

	header["account_title"] = _labelled(
		lines,
		r"(?:account|a/c)\s+title|title\s+of\s+(?:the\s+)?account|account\s+name|account\s+holder(?:\s+name)?"
		r"|customer\s+name|title",
	)

	value = _labelled(lines, r"bank\s+name|bank\s*:")
	if value and ":" not in value and len(value) <= 60:
		header["bank_name"] = value
	for segments in lines:
		if header["bank_name"]:
			break
		for part in (p.strip() for segment in segments for p in re.split(r"\s+[-–|]\s+|,\s", segment)):
			if (
				re.search(r"(?i)\bbank\b", part)
				and ":" not in part
				and len(part) <= 60
				and not re.search(r"(?i)statement|account|branch|charges|\d{3}", part)
			):
				header["bank_name"] = part
				break

	value = _labelled(lines, r"currency|ccy")
	m = re.match(r"[A-Za-z]{3}\b", value or "")
	if m:
		header["currency"] = m.group(0).upper()
	else:
		m = re.search(r"\b(" + "|".join(_CURRENCIES) + r")\b", full)
		if m:
			header["currency"] = m.group(1)
		elif re.search(r"\bRs\b\.?", full):
			header["currency"] = "PKR"

	for text in texts:
		if not re.search(r"(?i)\b(period|from|between|duration)\b", text):
			continue
		found = [m.group(0) for m in _DATE_TOKEN_RE.finditer(text)]
		found = [d for d in (_header_date(f, day_first) for f in found) if d]
		if len(found) >= 2:
			header["period_from"], header["period_to"] = found[0], found[1]
			break
	if not header["period_from"]:
		header["period_from"] = _header_date(_labelled(lines, r"from(?:\s+date)?|start\s+date"), day_first)
		header["period_to"] = _header_date(_labelled(lines, r"to(?:\s+date)?|end\s+date"), day_first)

	header["opening_balance"] = _first_amount(_labelled(lines, _OPENING_RE))
	header["closing_balance"] = _first_amount(_labelled(lines, _CLOSING_RE))
	return header


# --------------------------------------------------------------------------------------------
# rows -> transaction lines
# --------------------------------------------------------------------------------------------

_TOTAL_RE = r"(?:grand\s+|sub\s*)?totals?\b"


def _balance_row_kind(text: str, strict: bool):
	"""'opening' / 'closing' / 'total' when the row is a balance or totals row, not a transaction."""
	if strict:
		# a dated row: only when the description is nothing but the balance label
		bare = re.sub(r"[\d/\-.,:()]+", " ", text.lower())
		bare = re.sub(r"\b(as\s+(on|at|of)|on|rs|pkr)\b", " ", bare)
		bare = re.sub(r"\s+", " ", bare).strip()
		for kind, pattern in (("opening", _OPENING_RE), ("closing", _CLOSING_RE), ("total", _TOTAL_RE)):
			if re.fullmatch(pattern, bare):
				return kind
		return None
	for kind, pattern in (("opening", _OPENING_RE), ("closing", _CLOSING_RE)):
		if re.search(r"(?i)(?:^|[^a-z])(?:" + pattern + ")", text):
			return kind
	if re.search(r"(?i)(?:^|[^a-z])" + _TOTAL_RE, text):
		return "total"
	return None


def _marker_side(text: str):
	n = re.sub(r"[^a-z]", "", (text or "").lower())
	if n in ("dr", "d", "db", "debit", "withdrawal", "w", "out"):
		return "w"
	if n in ("cr", "c", "credit", "deposit", "in"):
		return "d"
	return None


def _col(layout: dict, key: str):
	value = layout.get(key)
	if value is None or value == "":
		return None
	return int(value)


def _build_result(file_type: str, table: dict, passed_layout: dict | None) -> dict:
	rows, start = table["rows"], table["start"]
	warnings = list(table["warnings"])
	layout = dict(table["layout"])
	if passed_layout and file_type == "pdf":
		layout.update({k: v for k, v in passed_layout.items() if k != "header_row"})
	layout["header_row"] = None if file_type == "pdf" else layout.get("header_row")

	date_col = _col(layout, "date")
	if date_col is None:
		raise StatementReadError(
			"No date column was found in this file. Check that it is a bank statement with one "
			"transaction per row and a date on each row."
		)
	description = layout.get("description")
	if description is None or description == "":
		description = []
	elif isinstance(description, int):
		description = [description]
	desc_cols = [int(c) for c in description]
	ref_col, w_col, d_col = _col(layout, "reference"), _col(layout, "withdrawal"), _col(layout, "deposit")
	a_col, b_col, m_col = _col(layout, "amount"), _col(layout, "balance"), _col(layout, "dr_cr")
	loose = table["loose_dates"]

	def cell(row, index):
		return row[index] if index is not None and 0 <= index < len(row) else None

	body = rows[start:]
	if not desc_cols and not passed_layout:
		used = {date_col, ref_col, w_col, d_col, a_col, b_col, m_col}
		lengths = Counter()
		for row in body:
			for i, value in enumerate(row):
				if i not in used and isinstance(value, str) and not _date_parts(value):
					lengths[i] += len(value)
		if lengths:
			desc_cols = [lengths.most_common(1)[0][0]]

	# a "Type" style column only counts as a Dr/Cr marker when it really holds Dr/Cr values
	if m_col is not None and not passed_layout:
		values = [_text(cell(row, m_col)) for row in body if _date_parts(cell(row, date_col), loose)]
		values = [v for v in values if v]
		if not values or sum(1 for v in values if _marker_side(v)) < 0.6 * len(values):
			if a_col is None and values and all(_amount(v)[0] is not None for v in values):
				a_col = m_col  # a single "Debit/Credit" column that holds signed amounts
			m_col = None

	all_parts = [_date_parts(cell(row, date_col), loose) for row in body]
	found_day_first, found_format, mixed = _decide_day_first(all_parts)
	if passed_layout and passed_layout.get("day_first") is not None:
		# the user's choice wins; keep the format's day/month order in step with it
		day_first = bool(passed_layout["day_first"])
		date_format = passed_layout.get("date_format") or found_format
		if date_format and "%d" in date_format and "%m" in date_format:
			if (date_format.index("%d") < date_format.index("%m")) != day_first:
				date_format = date_format.replace("%d", "%x").replace("%m", "%d").replace("%x", "%m")
	else:
		day_first, date_format = found_day_first, found_format
	if not any(all_parts):
		raise StatementReadError(
			"No dates were found in the date column. Check that the right column is chosen as the "
			"date and that the file is a bank statement."
		)
	if mixed:
		warnings.append(
			"Some dates look day-first and others month-first. Dates were read as "
			+ ("day/month/year" if day_first else "month/day/year")
			+ "; please check them."
		)

	heading_norm = {_norm_label(c) for c in table["columns"] if _norm_label(c)}
	numeric_cols = [c for c in (w_col, d_col, a_col, b_col) if c is not None]
	cont_ok = table["cont_ok"]
	entries, skipped = [], 0
	row_opening = row_closing = None
	current, may_continue = None, False

	for offset, row in enumerate(body):
		texts = [_text(c) for c in row]
		filled = [t for t in texts if t]
		if not filled:
			continue
		if len(filled) >= 2 and sum(1 for t in filled if _norm_label(t) in heading_norm) >= 0.6 * len(filled):
			may_continue = False
			continue  # the column headings repeated (new page)
		raw_date = cell(row, date_col)
		parts = all_parts[offset]
		desc = " ".join(texts[c] for c in desc_cols if c < len(texts) and texts[c])
		kind = _balance_row_kind(desc if parts else " ".join(filled), strict=bool(parts))
		if kind:
			value = _amount(cell(row, b_col))[0]
			if value is None:
				for c in reversed(range(len(row))):
					if c != date_col and not _date_parts(row[c]) and _amount(row[c])[0] is not None:
						value = _amount(row[c])[0]
						break
			if value is None:
				value = _first_amount(re.sub(r"(?i)" + _OPENING_RE + "|" + _CLOSING_RE, " ", " ".join(filled)))
			if value is not None and kind == "opening" and row_opening is None:
				row_opening = round(value, 2)
			elif value is not None and kind == "closing":
				row_closing = round(value, 2)
			current, may_continue = None, False
			continue

		if not parts:
			has_amount = any(_amount(cell(row, c))[0] is not None for c in numeric_cols)
			allowed = cont_ok is None or cont_ok[start + offset]
			if current and may_continue and allowed and desc and not _text(raw_date) and not has_amount:
				current["description"] = (current["description"] + " " + desc).strip()
				extra_ref = _text(cell(row, ref_col))
				if extra_ref and not current["reference_no"]:
					current["reference_no"] = extra_ref
			else:
				skipped += 1
				may_continue = False
			continue

		when = _resolve_date(parts, day_first, date_format, raw_date)
		entry = _entry_amounts(row, cell, w_col, d_col, a_col, m_col)
		balance = _amount(cell(row, b_col))[0]
		if when is None or entry is None:
			skipped += 1
			current, may_continue = None, False
			continue
		entry.update(
			date=when.isoformat(),
			description=desc,
			reference_no=_text(cell(row, ref_col)),
			balance=None if balance is None else round(balance, 2),
		)
		entries.append(entry)
		current, may_continue = entry, True

	header = _parse_header(table["header_lines"], day_first)
	if header["opening_balance"] is None:
		header["opening_balance"] = row_opening
	if header["closing_balance"] is None:
		header["closing_balance"] = row_closing

	single_amount = w_col is None and d_col is None and m_col is None
	trust = table["trust_balance"] or single_amount
	_apply_balance_check(entries, header["opening_balance"], trust, b_col is not None, warnings)

	lines = [
		{
			"date": e["date"],
			"description": e["description"],
			"reference_no": e["reference_no"],
			"withdrawal": round(e["amount"], 2) if e["side"] == "w" else 0.0,
			"deposit": round(e["amount"], 2) if e["side"] == "d" else 0.0,
			"balance": e["balance"],
		}
		for e in entries
	]
	if not lines:
		warnings.append("No transaction lines were found. Check the column choices.")
	if skipped:
		warnings.append(
			f"{skipped} row(s) were left out because they had no date or no amount. "
			"Check that nothing is missing."
		)

	layout_out = {
		"header_row": layout.get("header_row"),
		"date": date_col,
		"description": desc_cols,
		"reference": ref_col,
		"withdrawal": w_col,
		"deposit": d_col,
		"amount": a_col,
		"balance": b_col,
		"dr_cr": m_col,
		"date_format": date_format,
		"day_first": day_first,
	}
	width = max([len(r) for r in table["preview"]] + [len(table["columns"])])
	return {
		"file_type": file_type,
		"header": header,
		"columns": list(table["columns"]),
		"layout": layout_out,
		"preview_rows": [[_text(c) for c in (list(r) + [None] * width)[:width]] for r in table["preview"]],
		"lines": lines,
		"warnings": warnings,
		"skipped_rows": skipped,
	}


def _entry_amounts(row, cell, w_col, d_col, a_col, m_col):
	"""{"amount", "side", "explicit", "options"} for one row, or None when it carries no amount.

	`explicit` is False when the side is only a default (an unsigned figure in a single amount
	column); `options` lists the possible (side, amount) pairs when both columns are filled.
	"""
	w = abs(_amount(cell(row, w_col))[0] or 0)
	d = abs(_amount(cell(row, d_col))[0] or 0)
	if w and d:
		return {"amount": d, "side": "d", "explicit": False, "options": [("w", w), ("d", d)]}
	if w:
		return {"amount": w, "side": "w", "explicit": True, "options": None}
	if d:
		return {"amount": d, "side": "d", "explicit": True, "options": None}
	value, marker = _amount(cell(row, a_col))
	if not value:
		return None
	side = _marker_side(_text(cell(row, m_col))) if m_col is not None else None
	if side:
		explicit = True
	elif marker:
		side, explicit = ("w" if marker == "DR" else "d"), True
	elif value < 0:
		side, explicit = "w", True
	else:
		side, explicit = "d", False
	return {"amount": abs(value), "side": side, "explicit": explicit, "options": None}


def _apply_balance_check(entries, opening, trust: bool, has_balance_col: bool, warnings: list):
	"""Use the running balance to confirm, or decide, which side each amount is on."""
	unsigned = [e for e in entries if not e["explicit"]]
	with_balance = [i for i, e in enumerate(entries) if e["balance"] is not None]
	if len(with_balance) < 1 or not has_balance_col:
		if unsigned and not any(e["explicit"] for e in entries):
			warnings.append(
				"The amounts carry no sign and there is no running balance, so every line was read "
				"as money in. Please check which lines are payments."
			)
		elif unsigned and any(e["options"] for e in unsigned):
			warnings.append(
				f"{sum(1 for e in unsigned if e['options'])} row(s) had both a debit and a credit "
				"amount; the credit was used. Please check them."
			)
		return

	def fits(i, previous):
		e = entries[i]
		if previous is None or e["balance"] is None:
			return None
		change = e["balance"] - previous
		for side, amount in e["options"] or [("w", e["amount"]), ("d", e["amount"])]:
			if abs(change - (amount if side == "d" else -amount)) <= BALANCE_TOLERANCE:
				return side, amount
		return False

	def previous_balances(descending):
		result = []
		for i in range(len(entries)):
			j = i + 1 if descending else i - 1
			if 0 <= j < len(entries):
				result.append(entries[j]["balance"])
			else:
				result.append(opening)
		return result

	ascending, descending = previous_balances(False), previous_balances(True)
	score_up = sum(1 for i in range(len(entries)) if fits(i, ascending[i]))
	score_down = sum(1 for i in range(len(entries)) if fits(i, descending[i]))
	previous = descending if score_down > score_up else ascending

	results = [fits(i, previous[i]) for i in range(len(entries))]
	checked = [(e, r) for e, r in zip(entries, results) if r]
	against = [(e, r) for e, r in checked if e["explicit"] and r[0] != e["side"]]
	if against and not trust and len(against) > 0.5 * len(checked):
		warnings.append(
			"The running balance moves the opposite way to the debit and credit columns. The "
			"columns were used as they are; please check that money in and money out are not swapped."
		)
		return
	for e, (side, amount) in checked:
		e["side"], e["amount"] = side, amount
	if against:
		warnings.append(
			f"{len(against)} line(s) were moved between money in and money out because the running "
			"balance showed the other side."
		)
	mismatched = sum(1 for r in results if r is False)
	if mismatched:
		warnings.append(
			f"On {mismatched} line(s) the running balance does not match the amount. A row may be "
			"missing or misread; please check."
		)
	unsure = sum(1 for e, r in zip(entries, results) if not r and not e["explicit"])
	if unsure:
		warnings.append(
			f"{unsure} line(s) could not be checked against the running balance and were read as "
			"money in. Please check them."
		)
