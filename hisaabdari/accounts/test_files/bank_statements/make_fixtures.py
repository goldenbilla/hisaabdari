"""Rebuild the bank statement fixtures in this folder. All names and numbers are invented.

Run on a machine with Google Chrome, from any folder, with a Python that has openpyxl, xlwt and pypdf:
    python make_fixtures.py
The tests in ../../test_bank_statement_reader.py assert the values written here.
"""

import base64
import os
import struct
import subprocess
import tempfile
import zlib
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PDF_PASSWORD = "sitara-1947"

CSS = """
@page { size: A4; margin: 14mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9pt; color: #000; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
h1 { font-size: 14pt; margin: 0 0 2px 0; }
.sub { margin-bottom: 8px; }
.head { display: flex; justify-content: space-between; margin-bottom: 10px; }
.head div { line-height: 1.5; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 4px 8px; vertical-align: top; text-align: left; }
th { border-bottom: 1px solid #000; border-top: 1px solid #000; }
.r { text-align: right; }
td.n, .r { white-space: nowrap; }
.foot { margin-top: 14px; font-size: 8pt; }
"""


def html(body):
	return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def to_pdf(name, body):
	with tempfile.TemporaryDirectory() as tmp:
		source = os.path.join(tmp, name + ".html")
		with open(source, "w", encoding="utf-8") as f:
			f.write(html(body))
		subprocess.run(
			[
				CHROME,
				"--headless",
				"--disable-gpu",
				"--no-pdf-header-footer",
				f"--print-to-pdf={os.path.join(HERE, name + '.pdf')}",
				source,
			],
			check=True,
			capture_output=True,
		)


def table(headings, rows, right):
	out = ["<table><thead><tr>"]
	out += [f"<th class='{'r' if i in right else ''}'>{h}</th>" for i, h in enumerate(headings)]
	out.append("</tr></thead><tbody>")
	for row in rows:
		out.append("<tr>")
		out += [f"<td class='{'r' if i in right else ('' if '<br>' in c or len(c) > 14 else 'n')}'>{c}</td>" for i, c in enumerate(row)]
		out.append("</tr>")
	out.append("</tbody></table>")
	return "".join(out)


# ---------------------------------------------------------------- multi-page PDF, header on each page
def multi_page():
	head = """
	<h1>Sample Bank Limited</h1>
	<div class="sub">Statement of Account</div>
	<div class="head">
	  <div>Account Title: Sitara Hardware Store<br>Shop 14, Model Bazaar, Lahore<br>Branch: Main Boulevard Branch (0123)</div>
	  <div>Account Number: 0123-4567890-01<br>IBAN: PK36SMPL0000111122223333<br>Currency: PKR<br>
	  From 01-OCT-2026 To 31-OCT-2026<br>Opening Balance: 250,000.00<br>Closing Balance: 250,984.75</div>
	</div>"""
	headings = ["Date", "Value Date", "Particulars", "Cheque No", "Debit", "Credit", "Balance"]
	pages = [
		[
			["01-OCT-2026", "", "BALANCE B/F", "", "", "", "250,000.00"],
			["02-OCT-2026", "02-OCT-2026", "Cheque paid<br>Karim Packaging Works", "00451201", "45,000.00", "", "205,000.00"],
			["03-OCT-2026", "03-OCT-2026", "IBFT from Noor Textiles<br>Ref FT26276XK91 Inv 1045", "", "", "120,500.00", "325,500.00"],
			["05-OCT-2026", "05-OCT-2026", "ATM cash withdrawal Saddar Karachi", "", "20,000.00", "", "305,500.00"],
			["07-OCT-2026", "08-OCT-2026", "Online bill payment K-Electric<br>Consumer 0400012345678", "", "18,340.50", "", "287,159.50"],
			["09-OCT-2026", "09-OCT-2026", "Cash deposit", "", "", "60,000.00", "347,159.50"],
		],
		[
			["12-OCT-2026", "12-OCT-2026", "Cheque paid<br>Zafar Transport Services<br>against bilty 7781", "00451202", "32,750.00", "", "314,409.50"],
			["15-OCT-2026", "15-OCT-2026", "Withholding tax on cash withdrawal", "", "120.00", "", "314,289.50"],
			["20-OCT-2026", "21-OCT-2026", "Inward clearing Rehman Traders", "77120045", "", "85,000.00", "399,289.50"],
			["26-OCT-2026", "26-OCT-2026", "Salary transfer batch<br>October staff payroll", "", "150,000.00", "", "249,289.50"],
		],
		[
			["30-OCT-2026", "30-OCT-2026", "Profit credited", "", "", "1,845.25", "251,134.75"],
			["31-OCT-2026", "31-OCT-2026", "SMS alert charges<br>incl. FED", "", "150.00", "", "250,984.75"],
			["", "", "Closing Balance", "", "", "", "250,984.75"],
			["", "", "Total", "", "266,360.50", "267,345.25", ""],
		],
	]
	body = ""
	for n, rows in enumerate(pages, 1):
		note = "<div class='foot'>Please report any discrepancy within 14 days.</div>" if n == len(pages) else ""
		body += (
			f"<div class='page'>{head}{table(headings, rows, {4, 5, 6})}{note}"
			f"<div class='foot'>This is a computer generated statement and does not require a signature."
			f"<br>Page {n} of {len(pages)}</div></div>"
		)
	to_pdf("multi_page", body)


# ---------------------------------------------------------------- one amount column with Dr/Cr, wrapped headings
def single_amount():
	head = """
	<h1>Crescent Demo Bank</h1>
	<div class="sub">Account Statement</div>
	<div>Account Title : Sitara Hardware Store &nbsp; Account No : 0101-55667788</div>
	<div>IBAN : PK24 CDBK 0000 0101 5566 7788</div>
	<div>Statement Period: 01/10/2026 - 31/10/2026</div>
	<div style="margin-bottom:10px">Opening Balance 200,000.00</div>"""
	headings = ["Transaction<br>Date", "Description", "Ref<br>No", "Amount", "Balance"]
	rows = [
		["05/10/2026", "POS purchase Metro Cash &amp; Carry", "448812", "12,500.00 Dr", "187,500.00 Cr"],
		["08/10/2026", "Funds transfer from Hamza Electronics", "FT8821", "40,000.00 Cr", "227,500.00 Cr"],
		["13/10/2026", "Cheque 10023 paid<br>Faisal Paint House", "10023", "27,300.00 Dr", "200,200.00 Cr"],
		["21/10/2026", "Cash deposit by Imran", "", "15,000.00 Cr", "215,200.00 Cr"],
		["28/10/2026", "Bank charges", "", "250.00 Dr", "214,950.00 Cr"],
	]
	css = "<style>th { vertical-align: bottom; }</style>"
	to_pdf("single_amount", css + head + table(headings, rows, {3, 4}))


# ---------------------------------------------------------------- unsigned amounts: only the balance tells the side
def balance_only():
	head = """
	<h1>Indus Sample Bank</h1>
	<div class="head">
	  <div>Customer Name: Sitara Hardware Store</div>
	  <div>A/C #: 55501234567<br>Opening Balance: 80,000.00</div>
	</div>"""
	headings = ["Date", "Particulars", "Amount", "Balance"]
	rows = [
		["03 Oct 2026", "Cash deposit counter", "25,000.00", "105,000.00"],
		["06 Oct 2026", "Cheque 000187 Madina Steel", "30,000.00", "75,000.00"],
		["14 Oct 2026", "Mobile top-up", "1,000.00", "74,000.00"],
		["19 Oct 2026", "Raast transfer from Sana Boutique", "46,500.00", "120,500.00"],
		["27 Oct 2026", "Rent paid to Gulshan Plaza", "60,000.00", "60,500.00"],
	]
	to_pdf("balance_only", head + table(headings, rows, {2, 3}))


def encrypted():
	from pypdf import PdfReader, PdfWriter

	writer = PdfWriter()
	for page in PdfReader(os.path.join(HERE, "balance_only.pdf")).pages:
		writer.add_page(page)
	writer.encrypt(PDF_PASSWORD, algorithm="RC4-128")
	with open(os.path.join(HERE, "encrypted.pdf"), "wb") as f:
		writer.write(f)


def scanned():
	"""A PDF that holds only a picture (no text layer), like a scan."""
	width, height = 120, 60
	raw = b""
	for y in range(height):
		raw += b"\x00" + bytes(200 if (x // 6 + y // 6) % 2 else 90 for x in range(width))

	def chunk(kind, data):
		return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

	png = (
		b"\x89PNG\r\n\x1a\n"
		+ chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
		+ chunk(b"IDAT", zlib.compress(raw, 9))
		+ chunk(b"IEND", b"")
	)
	uri = "data:image/png;base64," + base64.b64encode(png).decode()
	to_pdf("scanned", f"<img src='{uri}' style='width:100%'>")


# ---------------------------------------------------------------- Excel
def excel_xlsx():
	import openpyxl

	book = openpyxl.Workbook()
	sheet = book.active
	sheet.title = "Statement"
	rows = [
		["Sample Bank Limited"],
		["Account Statement"],
		["Account Title", "Sitara Hardware Store"],
		["Account Number", 1234567890123],
		["IBAN", "PK36SMPL0000111122223333"],
		["Statement Period", "01/10/2026 to 31/10/2026"],
		["Currency", "PKR", None, "Opening Balance", 150000],
		[],
		["Transaction Date", "Value Date", "Description", "Remarks", "Instrument No", "Withdrawal", "Deposit", "Balance"],
		[datetime(2026, 10, 2), datetime(2026, 10, 2), "Cheque paid", "Karim Packaging", 451201, 45000, None, 105000],
		["07-Oct-2026", "07-Oct-2026", "IBFT Noor Textiles", None, "FT26280AB", None, 80000.5, 185000.5],
		[(date(2026, 10, 12) - date(1899, 12, 30)).days, None, "ATM withdrawal", "Saddar", None, 10000, 0, 175000.5],
		[datetime(2026, 10, 25), datetime(2026, 10, 26), "Utility bill", None, None, "2,500.50", None, 172500],
		[None, None, "Closing Balance", None, None, None, None, 172500],
		["Total", None, None, None, None, 57500.5, 80000.5],
		["*** End of statement ***"],
	]
	for row in rows:
		sheet.append(row)
	book.save(os.path.join(HERE, "excel_export.xlsx"))


def excel_xls():
	import xlwt

	book = xlwt.Workbook()
	sheet = book.add_sheet("Sheet1")
	date_style = xlwt.easyxf(num_format_str="DD/MM/YYYY")
	rows = [
		["Allied Sample Bank - Account Activity"],
		["Account No", "0044-112233-7"],
		["Date", "Narration", "Chq No", "Debit", "Credit", "Balance"],
		[date(2026, 10, 3), "Cash deposit", "", "", 30000, 130000],
		[date(2026, 10, 10), "Cheque paid Usman Glass", "9001", 12500.75, "", 117499.25],
		[date(2026, 10, 11), "Service charges", "", 100, "", 117399.25],
	]
	for r, row in enumerate(rows):
		for c, value in enumerate(row):
			if isinstance(value, date):
				sheet.write(r, c, value, date_style)
			else:
				sheet.write(r, c, value)
	book.save(os.path.join(HERE, "excel_legacy.xls"))


# ---------------------------------------------------------------- CSV
CSVS = {
	"separate_columns.csv": """Sample Bank Limited,,,,,,
Statement of Account,,,,,,
Account Title:,Sitara Hardware Store,,,,,
Account No:,0123-4567890-01,,IBAN:,PK36SMPL0000111122223333,,
Period:,01-OCT-2026 to 31-OCT-2026,,Currency:,PKR,,
,,,,,,
Date,Value Date,Particulars,Cheque No,Debit,Credit,Balance
,,Opening Balance,,,,"100,000.00"
01-OCT-2026,01-OCT-2026,Cheque paid Karim Packaging,00451201,"1,250.00",,"98,750.00"
05-OCT-2026,05-OCT-2026,"IBFT from Noor Textiles, Faisalabad",,,"25,000.00","123,750.00"
,,Invoice 1045 settlement,,,,
12-OCT-2026,13-OCT-2026,ATM withdrawal,,"10,000.00",0.00,"113,750.00"
31-OCT-2026,31-OCT-2026,Profit credited,,,845.25,"114,595.25"
,,Closing Balance,,,,"114,595.25"
,,Total,,"11,250.00","25,845.25",
""",
	"signed_amount.csv": """Date,Description,Amount,Balance
05/10/2026,Card payment Metro Store,"-1,250.00","48,750.00"
09/10/2026,Transfer from Hamza Electronics,"Rs. 15,000.00","63,750.00"
17/10/2026,Cheque 10023,(500.00),"63,250.00"
23/10/2026,Standing order rent,"2,000.00-","61,250.00"
31/10/2026,Profit,PKR 120.50,"61,370.50"
""",
	"drcr_marker.csv": """Crescent Demo Bank;;;;;
Txn Date;Narration;Ref No;Amount;Dr/Cr;Balance
05-Oct-26;Supplier payment Madina Steel;TR-5501;7,500.00;DR;42,500.00 CR
06-Oct-26;Customer receipt Sana Boutique;TR-5502;12,000.00;CR;54,500.00 CR
20-Oct-26;Excise duty;;35.00;Dr;54,465.00 CR
""",
	"month_first.csv": """Date,Details,Money Out,Money In
10/05/2026,Wire fee,25.00,
10/13/2026,Export proceeds,,"4,300.00"
11/02/2026,Courier,60.00,
""",
	"no_headings.csv": """Tarikh,Tafseel,Jama,Nikasi
03/10/2026,Cash jama,"5,000.00",
04/10/2026,Bijli bill,,"1,800.00"
06/10/2026,Dukaan kiraya,,"12,000.00"
""",
}


def csvs():
	for name, text in CSVS.items():
		with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as f:
			f.write(text)


if __name__ == "__main__":
	csvs()
	excel_xlsx()
	excel_xls()
	multi_page()
	single_amount()
	balance_only()
	encrypted()
	scanned()
	print("fixtures written to", HERE)
