from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from utiles.bnz_csv import StatementCoverageError
from utiles.converter import BnzCsvToIcostConverter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert BNZ CSV statements to an iCost import workbook.")
    parser.add_argument("--from", dest="date_from", required=True, type=parse_iso_date, help="Start date, inclusive, in YYYY-MM-DD format.")
    parser.add_argument("--to", dest="date_to", required=True, type=parse_iso_date, help="End date, inclusive, in YYYY-MM-DD format.")
    parser.add_argument("--input-dir", default="bnz_statements", help="Directory containing BNZ CSV files.")
    parser.add_argument("--output-dir", default="output", help="Directory for generated iCost workbooks.")
    parser.add_argument("--config-dir", default="config", help="Directory for local ignored account/rule configuration.")
    parser.add_argument("--ai-classify", action="store_true", help="Use AI to classify unknown merchant payees and save local rules.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs.")
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from error


def configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.debug)
    date_from = args.date_from
    date_to = args.date_to
    if date_from > date_to:
        print(f"ERROR: --from must be on or before --to ({date_from} > {date_to})", file=sys.stderr)
        raise SystemExit(2)
    converter = BnzCsvToIcostConverter(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        config_dir=Path(args.config_dir),
        date_from=date_from,
        date_to=date_to,
        ai_classify=args.ai_classify,
    )
    try:
        output_file, unknown_file, row_count, unknown_count = converter.run()
    except StatementCoverageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(f"Wrote {output_file} ({row_count} rows)")
    print(f"Wrote {unknown_file} ({unknown_count} unknown rows)")


if __name__ == "__main__":
    main()
