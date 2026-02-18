import pdfplumber
import json
import re
import sys
import glob
import os
from datetime import date
from pathlib import Path


def parse_purification_pdf(pdf_path: str) -> list:
    rates = []
    seen_tickers = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue

            for row in table:
                if not row or len(row) < 5:
                    continue

                ticker  = row[1]
                company = row[2]
                ratio   = row[3]
                status  = row[4]

                # Skip header row
                if not ticker or ticker.strip() == "Ticker":
                    continue

                ticker = ticker.strip()

                # Skip if not a valid PSX ticker (uppercase letters only)
                if not re.match(r'^[A-Z]+$', ticker):
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
                if ratio_str != 'N/A':
                    match = re.search(r'([\d.]+)%', ratio_str)
                    if match:
                        ratio_val = float(match.group(1))

                # Normalise status — remove trailing footnote numbers
                status_clean = re.sub(r'\d+$', '', status_str).strip()

                rates.append({
                    "ticker":            ticker,
                    "company":           company,
                    "purificationRatio": ratio_val,   # e.g. 2.26 means 2.26%
                    "shariahStatus":     status_clean  # "Compliant" | "Non-Compliant" | "NC by Nature"
                })

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
