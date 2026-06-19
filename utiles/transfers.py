from __future__ import annotations

import logging

from .models import Transaction

LOGGER = logging.getLogger(__name__)


def mark_internal_transfers(transactions: list[Transaction]) -> None:
    account_by_number = {
        tx.this_account: tx.account
        for tx in transactions
        if tx.this_account and tx.this_account != "---"
    }
    marked = 0
    for tx in transactions:
        if tx.bank_type != "IB" or not tx.other_account or tx.other_account == "---":
            continue
        other_account = account_by_number.get(tx.other_account)
        if other_account and other_account != tx.account:
            tx.transfer_account = other_account
            tx.transfer_matched = True
            marked += 1
    LOGGER.debug("Marked %d internal transfer rows", marked)


def should_export_transfer(tx: Transaction) -> bool:
    return bool(tx.transfer_account) and tx.direction == "支出"
