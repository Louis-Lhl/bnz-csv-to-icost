from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

LOGGER = logging.getLogger(__name__)

BNZ_HEADERS = [
    "Date",
    "Amount",
    "Payee",
    "Particulars",
    "Code",
    "Reference",
    "Tran Type",
    "This Party Account",
    "Other Party Account",
    "Serial",
    "Transaction Code",
    "Batch Number",
    "Originating Bank/Branch",
    "Processed Date",
]


@dataclass(frozen=True)
class ScreenshotTransaction:
    date: datetime
    details: str
    amount: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize manually extracted BNZ screenshot transactions to BNZ CSV format.")
    parser.add_argument("--input", required=True, type=Path, help="CSV file extracted from a screenshot with Date, Details, and Amount columns.")
    parser.add_argument("--output-dir", default=Path("bnz_statements/screenshot_imports"), type=Path, help="Directory for the generated BNZ-compatible CSV.")
    parser.add_argument("--account", required=True, help="iCost account name, for example: 1年定期")
    parser.add_argument("--payee", default="BNZ SCREENSHOT", help="Payee value written to the generated BNZ CSV.")
    parser.add_argument("--tran-type", default="TD", help="BNZ transaction type written to the generated BNZ CSV.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs.")
    return parser.parse_args()


def configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def parse_date(value: str) -> datetime:
    value = value.strip()
    for pattern in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, pattern).replace(hour=12)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date '{value}'. Expected formats like '1 Jun 2026' or '2026-06-01'.")


def parse_amount(value: str) -> Decimal:
    cleaned = value.strip().replace("$", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Unsupported amount '{value}'.") from error


def read_screenshot_csv(path: Path) -> list[ScreenshotTransaction]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header.")
        normalized_headers = {header.strip().lower(): header for header in reader.fieldnames}
        date_header = normalized_headers.get("date")
        details_header = normalized_headers.get("details") or normalized_headers.get("description")
        amount_header = normalized_headers.get("amount")
        if not date_header or not details_header or not amount_header:
            raise ValueError("Input CSV must include Date, Details, and Amount columns.")

        rows: list[ScreenshotTransaction] = []
        for row_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            date = parse_date(str(row.get(date_header) or ""))
            details = str(row.get(details_header) or "").strip()
            amount = parse_amount(str(row.get(amount_header) or ""))
            if not details:
                raise ValueError(f"Row {row_number} has an empty Details value.")
            rows.append(ScreenshotTransaction(date=date, details=details, amount=amount))
    if not rows:
        raise ValueError(f"{path} has no transaction rows.")
    return rows


def safe_prefix(account: str) -> str:
    prefix = re.sub(r"\s+", "-", account.strip())
    prefix = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "", prefix)
    if not prefix:
        raise ValueError("Account name cannot be empty after filename sanitization.")
    return prefix


def statement_token(value: datetime) -> str:
    return f"{value.day}{value.strftime('%b').upper()}{value.year}"


def format_amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def bnz_rows(rows: list[ScreenshotTransaction], payee: str, tran_type: str) -> list[dict[str, str]]:
    output_rows: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: (item.date, item.details, item.amount)):
        output_rows.append(
            {
                "Date": row.date.strftime("%d/%m/%y"),
                "Amount": format_amount(row.amount),
                "Payee": payee,
                "Particulars": row.details,
                "Code": "",
                "Reference": "",
                "Tran Type": tran_type,
                "This Party Account": "",
                "Other Party Account": "",
                "Serial": "",
                "Transaction Code": "",
                "Batch Number": "",
                "Originating Bank/Branch": "",
                "Processed Date": row.date.strftime("%d/%m/%y"),
            }
        )
    return output_rows


def output_path(output_dir: Path, account: str, rows: list[ScreenshotTransaction]) -> Path:
    sorted_rows = sorted(rows, key=lambda item: item.date)
    return output_dir / f"{safe_prefix(account)}-{statement_token(sorted_rows[0].date)}-to-{statement_token(sorted_rows[-1].date)}.csv"


def write_bnz_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BNZ_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    LOGGER.info("Wrote %s (%d rows)", path, len(rows))


def main() -> None:
    args = parse_args()
    configure_logging(args.debug)
    try:
        source_rows = read_screenshot_csv(args.input)
        output = output_path(args.output_dir, args.account, source_rows)
        write_bnz_csv(output, bnz_rows(source_rows, args.payee, args.tran_type))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    sorted_rows = sorted(source_rows, key=lambda row: row.date)
    print(f"Wrote {output} ({len(source_rows)} rows)")
    print("Next:")
    print(f"python3 convert_bnz_csv_to_icost.py --input-dir {args.output_dir} --from {sorted_rows[0].date.date()} --to {sorted_rows[-1].date.date()}")


if __name__ == "__main__":
    main()
