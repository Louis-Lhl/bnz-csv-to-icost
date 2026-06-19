from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

from utiles.converter import BnzCsvToIcostConverter


class ConverterIntegrationTest(unittest.TestCase):
    def test_converter_outputs_icost_workbook_and_unknown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_dir = root / "bnz_statements"
            config_dir = root / "config"
            output_dir = root / "output"
            shutil.copytree(Path("tests/data/bnz_statements"), input_dir)
            shutil.copytree(Path("tests/data/config"), config_dir)

            output_file, unknown_file, row_count, unknown_count = BnzCsvToIcostConverter(
                input_dir=input_dir,
                output_dir=output_dir,
                config_dir=config_dir,
                output_month="2026-01",
            ).run()

            self.assertEqual(row_count, 4)
            self.assertEqual(unknown_count, 0)
            self.assertTrue(output_file.exists())
            self.assertTrue(unknown_file.exists())

            workbook = load_workbook(output_file, data_only=True, read_only=True)
            rows = list(workbook.active.iter_rows(values_only=True))
            self.assertEqual(rows[0], ("日期", "类型", "金额", "一级分类", "二级分类", "账户1", "账户2", "备注", "货币", "标签"))
            self.assertIn(("2026年01月02日 12:00:00", "转账", 100, "其他", None, "Main Account", "Savings"), [row[:7] for row in rows[1:]])
            self.assertIn(("2026年01月04日 12:00:00", "转账", 1000, "其他", None, "Savings", "Term Deposit 3333333-01"), [row[:7] for row in rows[1:]])

            with ZipFile(output_file) as archive:
                sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIsNone(archive.testzip())
                self.assertIn("xl/sharedStrings.xml", archive.namelist())
                self.assertNotIn("inlineStr", sheet_xml)

            unknown_workbook = load_workbook(unknown_file, data_only=True, read_only=True)
            self.assertEqual(unknown_workbook.active.max_row, 1)


if __name__ == "__main__":
    unittest.main()
