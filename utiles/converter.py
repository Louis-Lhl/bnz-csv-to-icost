from __future__ import annotations

import logging
import shutil
from datetime import date, datetime
from pathlib import Path

from .ai_classifier import PayeeAIClassifier
from .bnz_csv import AccountResolver, csv_paths, parse_csv_transactions, validate_statement_coverage
from .models import Classification, transaction_key
from .rules import RuleEngine, read_filled_unknown_workbook, read_manual_workbook
from .transfers import mark_internal_transfers, should_export_transfer
from .workbook import icost_row, transfer_row, unknown_row, write_icost_import, write_unknown, write_workbook

LOGGER = logging.getLogger(__name__)

CSV_MANUAL_HEADERS = ["日期", "金额", "particulars", "BNZ类型", "BNZ方向", "类型", "一级分类", "二级分类", "账户2"]


class BnzCsvToIcostConverter:
    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        config_dir: Path,
        date_from: date,
        date_to: date,
        ai_classify: bool = False,
    ) -> None:
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.config_dir = config_dir
        self.date_from = date_from
        self.date_to = date_to
        self.output_label = f"{date_from.isoformat()}_to_{date_to.isoformat()}"
        self.output_file = output_dir / f"{self.output_label}.xlsx"
        self.unknown_file = output_dir / f"{self.output_label}_unknown.xlsx"
        self.manual_file = output_dir / "csv_manual_classifications.xlsx"
        self.local_rules_file = config_dir / "local_rules.csv"
        self.default_rules_file = config_dir / "default_rules.csv"
        self.ai_classify = ai_classify
        self.account_resolver = AccountResolver.from_csv(config_dir / "accounts.csv")
        self.rule_engine = RuleEngine.load(self.local_rules_file, self.default_rules_file)

    def run(self) -> tuple[Path, Path, int, int]:
        paths = csv_paths(self.input_dir)
        validate_statement_coverage(paths, self.account_resolver, self.date_from, self.date_to)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manual = read_manual_workbook(self.manual_file)
        filled_unknown = read_filled_unknown_workbook(self.unknown_file)
        if filled_unknown:
            manual.update(filled_unknown)
            self._persist_manual(manual)

        transactions = []
        for path in paths:
            transactions.extend(parse_csv_transactions(path, self.date_from, self.date_to, self.account_resolver))
        mark_internal_transfers(transactions)
        LOGGER.info("Loaded %d transactions for %s to %s", len(transactions), self.date_from, self.date_to)
        if self.ai_classify:
            added = PayeeAIClassifier(Path(".env"), self.local_rules_file).classify_and_save(
                [tx.payee for tx in self._unknown_candidates(transactions, manual)]
            )
            if added:
                LOGGER.info("Added %d AI classification rules to %s", added, self.local_rules_file)
                self.rule_engine = RuleEngine.load(self.local_rules_file, self.default_rules_file)

        icost_rows: list[list[object]] = []
        unknown_rows: list[list[object]] = []
        for tx in sorted(transactions, key=lambda item: (item.date_sort_key, item.account, item.particulars)):
            if should_export_transfer(tx):
                icost_rows.append(transfer_row(tx))
                continue
            if tx.transfer_account:
                continue

            classification = manual.get(transaction_key(tx)) or self.rule_engine.classify(tx)
            if classification is None:
                unknown_rows.append(unknown_row(tx))
            elif classification.tx_type == "转账":
                icost_rows.append(transfer_row(tx, classification.account2))
            else:
                icost_rows.append(icost_row(tx, classification))

        self._backup_existing(self.output_file)
        self._backup_existing(self.unknown_file)
        write_icost_import(self.output_file, icost_rows)
        write_unknown(self.unknown_file, unknown_rows)
        return self.output_file, self.unknown_file, len(icost_rows), len(unknown_rows)

    def _unknown_candidates(
        self,
        transactions: list,
        manual: dict[tuple[str, int, str, str, str], Classification],
    ) -> list:
        candidates = []
        for tx in transactions:
            if should_export_transfer(tx) or tx.transfer_account:
                continue
            if manual.get(transaction_key(tx)) or self.rule_engine.classify(tx):
                continue
            candidates.append(tx)
        LOGGER.debug("Prepared %d unknown transaction payees for optional AI classification", len(candidates))
        return candidates

    def _persist_manual(self, manual: dict[tuple[str, int, str, str, str], Classification]) -> None:
        rows = [
            [
                key[0],
                key[1] / 100,
                key[2],
                key[3],
                key[4],
                classification.tx_type,
                classification.primary,
                classification.secondary,
                classification.account2,
            ]
            for key, classification in sorted(manual.items())
        ]
        write_workbook(self.manual_file, CSV_MANUAL_HEADERS, rows, "csv_manual_classifications")
        LOGGER.info("Persisted %d manual classifications", len(rows))

    def _backup_existing(self, path: Path) -> None:
        if not path.exists():
            return
        backup_dir = path.parent / "_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, backup_dir / f"{path.stem}_{stamp}{path.suffix}")
