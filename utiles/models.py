from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


ICOST_HEADERS = ["日期", "类型", "金额", "一级分类", "二级分类", "账户1", "账户2", "备注", "货币", "标签"]
UNKNOWN_HEADERS = [
    "日期",
    "BNZ方向",
    "金额",
    "particulars",
    "BNZ类型",
    "余额",
    "类型",
    "一级分类",
    "二级分类",
    "账户1",
    "账户2",
    "备注",
    "货币",
    "标签",
]
DEFAULT_CURRENCY = "NZD"


@dataclass
class Transaction:
    date_text: str
    date_sort_key: str
    particulars: str
    account: str
    bank_type: str
    amount: Decimal
    direction: str
    this_account: str = ""
    other_account: str = ""
    transaction_code: str = ""
    batch_number: str = ""
    processed_date: str = ""
    transfer_account: str = ""
    transfer_matched: bool = False

    @property
    def note(self) -> str:
        parts = [
            self.particulars,
            f"BNZ:{self.bank_type}" if self.bank_type else "",
            f"This:{self.this_account}" if self.this_account else "",
            f"Other:{self.other_account}" if self.other_account else "",
            f"Txn:{self.transaction_code}" if self.transaction_code else "",
            f"Batch:{self.batch_number}" if self.batch_number else "",
            f"Processed:{self.processed_date}" if self.processed_date else "",
        ]
        return " | ".join(part for part in parts if part)


@dataclass(frozen=True)
class Classification:
    tx_type: str
    primary: str
    secondary: str = ""
    account2: str = ""


def money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def money_to_cents(value: Decimal) -> int:
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tx_key(date_text: object, amount: object, particulars: object, bank_type: object, direction: object) -> tuple[str, int, str, str, str]:
    amount_decimal = Decimal(str(amount or "0"))
    return (
        str(date_text or "").strip(),
        money_to_cents(amount_decimal),
        str(particulars or "").strip().upper(),
        str(bank_type or "").strip().upper(),
        str(direction or "").strip(),
    )


def transaction_key(tx: Transaction) -> tuple[str, int, str, str, str]:
    return tx_key(tx.date_text, tx.amount, tx.particulars, tx.bank_type, tx.direction)
