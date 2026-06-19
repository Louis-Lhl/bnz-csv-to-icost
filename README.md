# BNZ CSV to iCost

Convert BNZ CSV statement exports into iCost-compatible `.xlsx` import files.

This project intentionally treats bank statements, generated workbooks, and local classification rules as private data. Those files are ignored by Git by default.

## Project Structure

```text
bnz_statements/              # Put private BNZ CSV exports here
convert_bnz_csv_to_icost.py  # Main CLI program
utiles/                      # Converter, parsing, classification, workbook helpers
tests/                       # CI integration tests
tests/data/                  # Synthetic test data only
config/                      # Optional local config, ignored by Git
output/                      # Generated iCost files, ignored by Git
README.md
.gitignore
```

## Setup

```bash
python -m pip install -r requirements.txt
```

## Usage

Put BNZ CSV exports in `bnz_statements/`, then run:

```bash
python convert_bnz_csv_to_icost.py 2026-06
```

Chinese month aliases are also supported:

```bash
python convert_bnz_csv_to_icost.py 6月
```

Generated files are written to `output/`:

```text
output/2026-06.xlsx
output/2026-06_unknown.xlsx
```

Fill `*_unknown.xlsx` when classification is unclear, then rerun the same command. Confirmed classifications are persisted to:

```text
output/csv_manual_classifications.xlsx
```

## Optional Local Config

Local config files are ignored by Git because they can contain account names or personal rules.

`config/accounts.csv` maps filename prefixes to iCost account names:

```csv
filename_prefix,account_name
Joint-Account,Joint Account
Joint-Saving,Joint Saving
```

`config/local_rules.csv` adds personal or private classification rules:

```csv
match_text,类型,一级分类,二级分类,账户2,BNZ方向,BNZ类型,金额,优先级
EXAMPLE SOFTWARE SHARE,收入,应用软件,,,收入,AP,11.50,200
```

Do not commit real account numbers, names, or bank statements.

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

The tests use synthetic CSV data under `tests/data/`; no personal bank data is required.

## Notes

- Only BNZ CSV exports are supported.
- PDF statement conversion has been removed from the codebase.
- Internal transfers are detected when both sides of a transfer are present in the CSV inputs.
- BNZ `TD` rows are exported as iCost transfers to a generated `Term Deposit ...` account.
- Output `.xlsx` files are generated with shared strings because iCost rejects inline string-only workbooks.
