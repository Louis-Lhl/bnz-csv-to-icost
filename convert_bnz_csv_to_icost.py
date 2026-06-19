from __future__ import annotations

import argparse
import logging
from pathlib import Path

from utiles.converter import BnzCsvToIcostConverter


MONTH_ALIASES = {
    "1月": "2026-01",
    "2月": "2026-02",
    "3月": "2026-03",
    "4月": "2026-04",
    "5月": "2026-05",
    "6月": "2026-06",
    "7月": "2026-07",
    "8月": "2026-08",
    "9月": "2026-09",
    "10月": "2026-10",
    "11月": "2026-11",
    "12月": "2026-12",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert BNZ CSV statements to an iCost import workbook.")
    parser.add_argument("month", help="Target month, for example 2026-06 or 6月.")
    parser.add_argument("--input-dir", default="bnz_statements", help="Directory containing BNZ CSV files.")
    parser.add_argument("--output-dir", default="output", help="Directory for generated iCost workbooks.")
    parser.add_argument("--config-dir", default="config", help="Directory for local ignored account/rule configuration.")
    parser.add_argument("--ai-classify", action="store_true", help="Use AI to classify unknown merchant payees and save local rules.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs.")
    return parser.parse_args()


def normalize_month(value: str) -> str:
    return MONTH_ALIASES.get(value, value)


def configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.debug)
    month = normalize_month(args.month)
    converter = BnzCsvToIcostConverter(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        config_dir=Path(args.config_dir),
        output_month=month,
        ai_classify=args.ai_classify,
    )
    output_file, unknown_file, row_count, unknown_count = converter.run()
    print(f"Wrote {output_file} ({row_count} rows)")
    print(f"Wrote {unknown_file} ({unknown_count} unknown rows)")


if __name__ == "__main__":
    main()
