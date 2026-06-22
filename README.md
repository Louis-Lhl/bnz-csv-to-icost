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
config/default_rules.csv     # Public default merchant rules
output/                      # Generated iCost files, ignored by Git
README.md
.gitignore
```

## Setup

```bash
python -m pip install -r requirements.txt
```

On macOS, use `python3` if `python` is not available:

```bash
python3 -m pip install -r requirements.txt
```

## Usage

Put BNZ CSV exports in `bnz_statements/`, then run:

```bash
python convert_bnz_csv_to_icost.py --from 2026-06-01 --to 2026-06-30
```

Both dates are inclusive. The converter scans BNZ CSV filenames before parsing rows and verifies that every discovered account covers the requested period. BNZ filenames must include an export range like:

```text
Joint-Account-1JUN2026-to-30JUN2026.csv
```

If an account's files do not fully cover the requested date range, the program prints an error and exits without writing import files.

Generated files are written to `output/` using the requested period:

```text
output/2026-06-01_to_2026-06-30.xlsx
output/2026-06-01_to_2026-06-30_unknown.xlsx
```

Fill `*_unknown.xlsx` when classification is unclear, then rerun the same command. Confirmed classifications are persisted to:

```text
output/csv_manual_classifications.xlsx
```

## Screenshot Workflow

When asking Codex to convert a screenshot to an iCost bill, Codex should first ask which screenshot to use. The screenshot content should then be transcribed into a small private CSV with this shape:

```csv
Date,Details,Amount
1 Jun 2026,Tax Interest Payment 00089369602 00004 TD TAX,-$4.92
1 Jun 2026,Gross Interest Payment 00089369602 00004 TD INTEREST,$28.16
```

Normalize that extracted screenshot CSV into the standard BNZ CSV format:

```bash
python3 convert_bnz_screenshot_to_csv.py \
  --input bnz_statements/screenshot_extract.csv \
  --account 1年定期
```

The generated CSV is written to `bnz_statements/screenshot_imports/` with a BNZ-compatible filename and columns. Then use the normal converter:

```bash
python3 convert_bnz_csv_to_icost.py \
  --input-dir bnz_statements/screenshot_imports \
  --from 2026-06-01 \
  --to 2026-06-01
```

This keeps the final iCost workbook generation in one place: `convert_bnz_csv_to_icost.py`.

## Classification Rules

The converter loads rules in this order:

1. `config/default_rules.csv`: public default merchant examples that are safe to commit, such as `PAK N SAVE`, `KFC`, `GITHUB`, and `WOOLWORTHS`.
2. `config/local_rules.csv`: private local rules learned from your own corrections or AI suggestions. This file is ignored by Git.
3. Manual classifications persisted from filled unknown workbooks in `output/csv_manual_classifications.xlsx`.

## Optional Local Config

Local config files are ignored by Git because they can contain account names or personal rules.

`config/accounts.csv` maps filename prefixes to iCost account names:

```csv
filename_prefix,account_name
Main-Account,Main Account
Savings,Savings
```

`config/local_rules.csv` adds personal or private classification rules:

```csv
match_text,类型,一级分类,二级分类,账户2,BNZ方向,BNZ类型,金额,优先级
EXAMPLE SOFTWARE SHARE,收入,应用软件,,,收入,AP,11.50,200
```

Do not commit real account numbers, names, or bank statements.

## Optional AI Classification

AI classification is disabled by default. Enable it explicitly:

```bash
python convert_bnz_csv_to_icost.py --from 2026-06-01 --to 2026-06-30 --ai-classify
```

Privacy boundary: the AI request only sends selected context fields from transactions that could not already be classified: `Payee`, `Particulars`, `Code`, `Reference`, BNZ transaction type, and income/expense direction. It does not send full CSV rows, dates, amounts, account names, account numbers, balances, generated workbooks, or existing local rule files. Likely personal payees are masked as `[private_payee]`, while non-accounting memo fields such as `Lunch` can still be used to classify reimbursements or shared costs.

Create a local `.env` from the template:

```bash
cp .env.example .env
```

Then set:

```text
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

`.env` is ignored by Git. For a single-user local tool, `.env` is practical and auditable. A more secure option is storing the key in the macOS Keychain or exporting `OPENAI_API_KEY` only for the current shell session; that avoids a long-lived plaintext key file, but it is less convenient for non-technical users. Do not commit API keys.

If AI classification fails with `CERTIFICATE_VERIFY_FAILED`, reinstall dependencies so Python uses the bundled CA certificates:

```bash
python3 -m pip install -r requirements.txt
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

The tests use synthetic CSV data under `tests/data/`; no personal bank data is required.

GitHub Actions runs the same integration test suite through:

```bash
python tests/run_ci_report.py
```

Each CI run writes a readable test summary to the GitHub Actions run page and uploads `ci-test-report` as an artifact.

## Notes

- Only BNZ CSV exports are supported.
- PDF statement conversion has been removed from the codebase.
- Internal transfers are detected when both sides of a transfer are present in the CSV inputs.
- BNZ `TD` rows are exported as iCost transfers to a generated `Term Deposit ...` account.
- Output `.xlsx` files are generated with shared strings because iCost rejects inline string-only workbooks.
