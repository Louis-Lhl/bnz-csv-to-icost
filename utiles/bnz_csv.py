from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import Transaction

LOGGER = logging.getLogger(__name__)

TRAN_TYPE_MAP = {
    "POS": "PS",
    "FT": "IB",
    "DC": "DC",
    "BP": "BP",
    "DD": "DD",
    "AP": "AP",
    "ATM": "ATM",
    "INT": "INT",
    "TD": "TD",
}


class AccountResolver:
    def __init__(self, account_map: dict[str, str] | None = None) -> None:
        self.account_map = account_map or {}

    @classmethod
    def from_csv(cls, path: Path) -> "AccountResolver":
        if not path.exists():
            return cls()
        mapping: dict[str, str] = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                prefix = str(row.get("filename_prefix") or "").strip()
                account = str(row.get("account_name") or "").strip()
                if prefix and account:
                    mapping[prefix] = account
        return cls(mapping)

    def account_from_path(self, path: Path) -> str:
        for prefix, account in self.account_map.items():
            if path.name.startswith(prefix):
                return account
        stem = path.stem
        match = re.match(r"(.+?)-\d{1,2}[A-Z]{3}\d{4}-to-", stem, re.I)
        prefix = match.group(1) if match else stem.split("-")[0]
        return prefix.replace("-", " ").strip()


def clean_join(*parts: object) -> str:
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def parse_csv_date(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%d/%m/%y").replace(hour=12)


def particulars_from_row(row: dict[str, str]) -> str:
    return clean_join(row.get("Payee"), row.get("Particulars"), row.get("Code"), row.get("Reference"))


def csv_paths(input_dir: Path) -> list[Path]:
    paths = sorted(path for path in input_dir.rglob("*.csv") if path.is_file())
    LOGGER.debug("Discovered %d CSV files in %s", len(paths), input_dir)
    return paths


def parse_csv_transactions(path: Path, output_month: str, account_resolver: AccountResolver) -> list[Transaction]:
    account = account_resolver.account_from_path(path)
    transactions: list[Transaction] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            amount = Decimal(row["Amount"])
            date = parse_csv_date(row["Date"])
            if date.strftime("%Y-%m") != output_month:
                continue
            bank_type = str(row.get("Tran Type") or "").strip()
            transactions.append(
                Transaction(
                    date_text=date.strftime("%Y年%m月%d日 %H:%M:%S"),
                    date_sort_key=date.strftime("%Y-%m-%d"),
                    particulars=particulars_from_row(row),
                    account=account,
                    bank_type=TRAN_TYPE_MAP.get(bank_type, bank_type),
                    amount=abs(amount),
                    direction="收入" if amount > 0 else "支出",
                    payee=str(row.get("Payee") or "").strip(),
                    this_account=str(row.get("This Party Account") or "").strip(),
                    other_account=str(row.get("Other Party Account") or "").strip(),
                    transaction_code=str(row.get("Transaction Code") or "").strip(),
                    batch_number=str(row.get("Batch Number") or "").strip(),
                    processed_date=str(row.get("Processed Date") or "").strip(),
                )
            )
    LOGGER.debug("Parsed %d %s transactions from %s as account %s", len(transactions), output_month, path.name, account)
    return transactions
