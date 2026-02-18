import pdfplumber
import json
import re
import sys
import glob
from datetime import date
from pathlib import Path


def parse_purification_pdf(pdf_path: str) -> dict:
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

                # Parse ratio — strip footnote digits e.g. "Compliant1" → "Compliant"
                ratio_val = None
                if ratio_str != 'N/A':
                    match = re.search(r'([\d.]+)%', ratio_str)
                    if match:
                        ratio_val = float(match.group(1))

                # Normalise status — remove trailing footnote numbers
                status_clean = re.sub(r'\d+$', '', status_str).strip()

                rates.append({
                    "ticker":           ticker,
                    "company":          company,
                    "purificationRatio": ratio_val,   # percentage e.g. 2.26 means 2.26%
                    "shariahStatus":    status_clean  # "Compliant" | "Non-Compliant" | "NC by Nature"
                })

    # Extract period from filename e.g. "Final-List-of-KMI-30-June-2025.pdf" → "Jun-2025"
    filename = Path(pdf_path).stem
    period_match = re.search(r'(\w+)-(\d{4})$', filename)
    period = f"{period_match.group(1)[:3]}-{period_match.group(2)}" if period_match else "Unknown"

    return {
        "lastUpdated":  str(date.today()),
        "period":       period,
        "totalStocks":  len(rates),
        "rates":        rates
    }


if __name__ == "__main__":
    # Use path from arg, or find first PDF in current directory
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdfs = glob.glob("*.pdf")
        if not pdfs:
            print("Error: No PDF found. Place a PDF in this directory or pass path as argument.")
            sys.exit(1)
        pdf_path = pdfs[0]

    print(f"Parsing: {pdf_path}")
    data = parse_purification_pdf(pdf_path)

    output_path = "purification-rates.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Done. {data['totalStocks']} stocks written to {output_path}")
    print(f"Period: {data['period']} | Last Updated: {data['lastUpdated']}")
