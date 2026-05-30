import pdfplumber
import json
import re
import sys
import glob
import os
from datetime import date
from pathlib import Path


def _detect_format(header_row: list) -> str:
    """Return 'new' if 11-column screening table, 'old' if 5-column purification table."""
    cols = [c.replace('\n', ' ').strip() if c else '' for c in header_row]
    if any('Income Ratio' in c for c in cols):
        return 'new'
    return 'old'


def _normalise_status(status: str) -> str:
    """Return a consistent status value and remove trailing PDF footnote numbers."""
    status = re.sub(r'\d+$', '', status or '').strip()
    if status.lower() == 'nc by nature':
        return 'NC by Nature'
    return status


def _extract_text_only_rows(pdf) -> tuple[dict, list]:
    """Recover statuses and rows omitted by pdfplumber's table extraction."""
    statuses = {}
    extra_rows = []
    seen_extra_tickers = set()
    in_etf_section = False

    for page in pdf.pages:
        for line in (page.extract_text() or '').splitlines():
            if line == 'EXCHANGE TRADED FUNDS (ETFs)':
                in_etf_section = True
                continue
            if in_etf_section and line.startswith('NOTE:'):
                in_etf_section = False

            # Standard rows can lose the final status cell when it has a footnote.
            match = re.match(
                r'^\d+(?:\s+\d+)?\s+([A-Za-z0-9]+)\s+.+\s+'
                r'(NC by [Nn]ature|Non-Compliant|Compliant)(?:\s+\d+)?$',
                line
            )
            if match:
                statuses[match.group(1).upper()] = _normalise_status(match.group(2))

            # The PDF intentionally has no final status for these companies.
            match = re.match(
                r'^\d+(?:\s+\d+)?\s+([A-Z0-9]+)\s+(.+?)\s+Compliant\s+'
                r'As no recent (?:financial|Shariah certificate) .*'
                r'no shariah opinion is drawn$',
                line,
                re.IGNORECASE
            )
            if match:
                ticker, company = match.groups()
                ticker = ticker.upper()
                statuses[ticker] = 'No Shariah Opinion'
                if ticker not in seen_extra_tickers:
                    extra_rows.append({
                        "ticker": ticker,
                        "company": company.strip(),
                        "purificationRatio": None,
                        "shariahStatus": "No Shariah Opinion"
                    })
                    seen_extra_tickers.add(ticker)

            if in_etf_section:
                match = re.match(
                    r'^\d+\s+([A-Z0-9]+)\s+(.+?)\s+(Non-Compliant|Compliant)$',
                    line
                )
                if match:
                    ticker, company, status = match.groups()
                    ticker = ticker.upper()
                    if ticker not in seen_extra_tickers:
                        extra_rows.append({
                            "ticker": ticker,
                            "company": company.strip(),
                            "purificationRatio": None,
                            "shariahStatus": status
                        })
                        seen_extra_tickers.add(ticker)

    return statuses, extra_rows


def parse_purification_pdf(pdf_path: str) -> list:
    rates = []
    seen_tickers = set()
    fmt = None  # detected on first header row

    with pdfplumber.open(pdf_path) as pdf:
        text_statuses, text_only_rows = _extract_text_only_rows(pdf)

        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue

            for row in table:
                if not row:
                    continue

                # Detect/re-confirm format from header rows
                if row[1] and str(row[1]).strip() == "Ticker":
                    fmt = _detect_format(row)
                    continue

                # Ignore front matter until a real screening table header is found.
                if fmt is None:
                    continue

                if fmt == 'new':
                    if len(row) < 11:
                        continue
                    ticker  = row[1]
                    company = row[2]
                    # Income Ratio (NCInc/TR) is the purification ratio
                    ratio   = row[6]
                    status  = row[10]
                else:
                    # old format or not yet detected — fall back to old layout
                    if len(row) < 5:
                        continue
                    ticker  = row[1]
                    company = row[2]
                    ratio   = row[3]
                    status  = row[4]

                if not ticker:
                    continue
                ticker = ticker.strip().upper()

                # Skip if not a valid PSX ticker after normalising PDF casing.
                if not re.match(r'^[A-Z0-9]+$', ticker):
                    continue

                # Skip duplicates (header repeats on each page)
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)

                company    = company.replace('\n', ' ').strip() if company else ''
                status_str = status.replace('\n', ' ').strip() if status else ''
                ratio_str  = ratio.strip() if ratio else 'N/A'

                # Parse ratio value
                ratio_val = None
                if ratio_str not in ('N/A', ''):
                    match = re.search(r'([\d.]+)%', ratio_str)
                    if match:
                        ratio_val = float(match.group(1))

                status_clean = _normalise_status(status_str)
                if not status_clean:
                    status_clean = text_statuses.get(ticker, '')

                rates.append({
                    "ticker":            ticker,
                    "company":           company,
                    "purificationRatio": ratio_val,   # e.g. 2.26 means 2.26%
                    "shariahStatus":     status_clean  # Includes "No Shariah Opinion" when PSX gives no opinion
                })

        for row in text_only_rows:
            if row["ticker"] not in seen_tickers:
                rates.append(row)
                seen_tickers.add(row["ticker"])

    return rates


def load_index() -> dict:
    if os.path.exists("index.json"):
        with open("index.json", "r") as f:
            return json.load(f)
    return {"periods": []}


def save_index(index: dict):
    with open("index.json", "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python3 parse_pdf.py <pdf_path> <period> <valid_from> <valid_to>")
        print("Example: python3 parse_pdf.py file.pdf 2025-H1 2025-01-01 2025-06-30")
        sys.exit(1)

    pdf_path    = sys.argv[1]
    period      = sys.argv[2]   # e.g. "2025-H1"
    valid_from  = sys.argv[3]   # e.g. "2025-01-01"
    valid_to    = sys.argv[4]   # e.g. "2025-06-30"

    print(f"Parsing: {pdf_path}")
    print(f"Period:  {period} ({valid_from} → {valid_to})")

    rates = parse_purification_pdf(pdf_path)
    print(f"Parsed:  {len(rates)} stocks")

    # Save period-specific file
    os.makedirs("rates", exist_ok=True)
    period_file = f"rates/{period}.json"
    period_data = {
        "period":      period,
        "validFrom":   valid_from,
        "validTo":     valid_to,
        "parsedOn":    str(date.today()),
        "totalStocks": len(rates),
        "rates":       rates
    }
    with open(period_file, "w") as f:
        json.dump(period_data, f, indent=2, ensure_ascii=False)
    print(f"Saved:   {period_file}")

    # Update index.json
    index = load_index()
    # Remove existing entry for this period if re-running
    index["periods"] = [p for p in index["periods"] if p["period"] != period]
    index["periods"].append({
        "period":    period,
        "validFrom": valid_from,
        "validTo":   valid_to,
        "file":      period_file
    })
    # Keep sorted by validFrom
    index["periods"].sort(key=lambda x: x["validFrom"])
    index["lastUpdated"] = str(date.today())
    save_index(index)
    print(f"Updated: index.json ({len(index['periods'])} period(s) total)")
