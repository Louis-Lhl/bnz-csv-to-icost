from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .models import Transaction

LOGGER = logging.getLogger(__name__)

STATEMENT_RANGE_RE = re.compile(
    r"(?P<prefix>.+?)-(?P<from>\d{1,2}[A-Z]{3}\d{4})-to-(?P<to>\d{1,2}[A-Z]{3}\d{4})\.csv$",
    re.I,
)
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

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


@dataclass(frozen=True)
class StatementCoverage:
    path: Path
    account: str
    date_from: date
    date_to: date


class StatementCoverageError(ValueError):
    pass


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


def parse_statement_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2})([A-Z]{3})(\d{4})", value.strip(), re.I)
    if not match:
        raise ValueError(f"Unsupported statement date token: {value}")
    day = int(match.group(1))
    month = MONTHS[match.group(2).upper()]
    year = int(match.group(3))
    return date(year, month, day)


def parse_statement_coverage(path: Path, account_resolver: AccountResolver) -> StatementCoverage:
    match = STATEMENT_RANGE_RE.match(path.name)
    if not match:
        raise StatementCoverageError(f"Cannot read date range from statement filename: {path.name}")
    date_from = parse_statement_date(match.group("from"))
    date_to = parse_statement_date(match.group("to"))
    if date_from > date_to:
        raise StatementCoverageError(f"Statement filename has inverted date range: {path.name}")
    return StatementCoverage(
        path=path,
        account=account_resolver.account_from_path(path),
        date_from=date_from,
        date_to=date_to,
    )


def validate_statement_coverage(paths: list[Path], account_resolver: AccountResolver, date_from: date, date_to: date) -> list[StatementCoverage]:
    if date_from > date_to:
        raise StatementCoverageError(f"Invalid requested date range: {date_from} to {date_to}")
    if not paths:
        raise StatementCoverageError("No BNZ CSV statement files found")

    coverages = [parse_statement_coverage(path, account_resolver) for path in paths]
    by_account: dict[str, list[StatementCoverage]] = {}
    for coverage in coverages:
        by_account.setdefault(coverage.account, []).append(coverage)

    failures: list[str] = []
    for account, account_coverages in sorted(by_account.items()):
        current = date_from
        for coverage in sorted(account_coverages, key=lambda item: (item.date_from, item.date_to)):
            if coverage.date_to < current:
                continue
            if coverage.date_from > current:
                failures.append(f"{account}: missing {current.isoformat()} to {(coverage.date_from - timedelta(days=1)).isoformat()}")
                current = coverage.date_to + timedelta(days=1)
            else:
                current = max(current, coverage.date_to + timedelta(days=1))
            if current > date_to:
                break
        if current <= date_to:
            failures.append(f"{account}: missing {current.isoformat()} to {date_to.isoformat()}")

    if failures:
        detail = "\n".join(f"- {failure}" for failure in failures)
        raise StatementCoverageError(f"Requested date range is not fully covered by BNZ CSV files:\n{detail}")

    LOGGER.info("Validated statement filename coverage for %d account(s)", len(by_account))
    return coverages


def particulars_from_row(row: dict[str, str]) -> str:
    return clean_join(row.get("Payee"), row.get("Particulars"), row.get("Code"), row.get("Reference"))


def csv_paths(input_dir: Path) -> list[Path]:
    paths = sorted(path for path in input_dir.rglob("*.csv") if path.is_file())
    LOGGER.debug("Discovered %d CSV files in %s", len(paths), input_dir)
    return paths


def parse_csv_transactions(path: Path, date_from: date, date_to: date, account_resolver: AccountResolver) -> list[Transaction]:
    account = account_resolver.account_from_path(path)
    transactions: list[Transaction] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            amount = Decimal(row["Amount"])
            date = parse_csv_date(row["Date"])
            if not (date_from <= date.date() <= date_to):
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
    LOGGER.debug("Parsed %d transactions from %s as account %s", len(transactions), path.name, account)
    return transactions
