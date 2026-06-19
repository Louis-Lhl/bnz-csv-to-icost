from __future__ import annotations

import csv
import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import Classification
from .rules import EXPENSE_CATEGORIES, INCOME_CATEGORIES, is_valid_classification

LOGGER = logging.getLogger(__name__)

RULE_HEADERS = ["match_text", "类型", "一级分类", "二级分类", "账户2", "备注规则", "BNZ方向", "BNZ类型", "金额", "优先级"]
AI_RULE_PRIORITY = "180"
MIN_CONFIDENCE = 0.75
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class SuggestedRule:
    match_text: str
    classification: Classification
    reason: str
    confidence: float


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def likely_sensitive_payee(payee: str) -> bool:
    text = payee.strip()
    upper = text.upper()
    if not text:
        return True
    if "," in text or " GIFT" in upper or upper.endswith(" GIFT"):
        return True
    tokens = re.findall(r"[A-Za-z]+", text)
    merchant_markers = {
        "AIR",
        "APPLE",
        "BAKERY",
        "BP",
        "CAFE",
        "CHEMIST",
        "GITHUB",
        "GOOGLE",
        "KFC",
        "MART",
        "MCDONALD",
        "NEW",
        "NZ",
        "PAK",
        "POWER",
        "POWERSHOP",
        "RESTAURANT",
        "SAVE",
        "SHOP",
        "STORE",
        "TRANSPORT",
        "UBER",
        "WAREHOUSE",
        "WOOLWORTHS",
        "WORLD",
    }
    if 2 <= len(tokens) <= 4 and not any(token.upper() in merchant_markers for token in tokens):
        return True
    return False


class PayeeAIClassifier:
    def __init__(self, env_file: Path, local_rules_file: Path) -> None:
        load_dotenv(env_file)
        self.local_rules_file = local_rules_file
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    def classify_and_save(self, payees: list[str]) -> int:
        candidates = sorted({payee.strip() for payee in payees if payee.strip() and not likely_sensitive_payee(payee)})
        if not candidates:
            LOGGER.info("AI classification skipped: no non-sensitive payee candidates")
            return 0
        if not self.api_key:
            LOGGER.warning("AI classification skipped: OPENAI_API_KEY is not set")
            return 0

        LOGGER.info("Sending %d unique payee strings to AI classification", len(candidates))
        suggestions = self._request_suggestions(candidates)
        accepted = [
            suggestion
            for suggestion in suggestions
            if suggestion.confidence >= MIN_CONFIDENCE and is_valid_classification(suggestion.classification)
        ]
        LOGGER.info("AI returned %d suggestions; accepted %d", len(suggestions), len(accepted))
        return append_rules(self.local_rules_file, accepted)

    def _request_suggestions(self, payees: list[str]) -> list[SuggestedRule]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": json.dumps({"payees": payees}, ensure_ascii=False)},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45, context=create_ssl_context()) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI classification request failed: HTTP {error.code} {detail}") from error
        except urllib.error.URLError as error:
            reason = str(error.reason)
            if "CERTIFICATE_VERIFY_FAILED" in reason:
                reason = f"{reason}. Run `python3 -m pip install -r requirements.txt` to install certifi CA certificates."
            raise RuntimeError(f"AI classification request failed: {reason}") from error

        content = response_payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        suggestions: list[SuggestedRule] = []
        for item in parsed.get("rules", []):
            match_text = str(item.get("match_text") or "").strip()
            tx_type = str(item.get("类型") or "").strip()
            primary = str(item.get("一级分类") or "").strip()
            if not match_text or not tx_type or not primary:
                continue
            confidence = float(item.get("confidence") or 0)
            classification = Classification(
                tx_type=tx_type,
                primary=primary,
                secondary=str(item.get("二级分类") or "").strip(),
            )
            suggestions.append(
                SuggestedRule(
                    match_text=match_text,
                    classification=classification,
                    reason=str(item.get("reason") or "AI suggested merchant classification").strip(),
                    confidence=confidence,
                )
            )
        return suggestions


def create_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def system_prompt() -> str:
    return (
        "You classify New Zealand bank transaction payee strings for iCost personal finance import. "
        "You receive only payee strings, never full bank rows. Return JSON only, with key 'rules'. "
        "For each known merchant, return match_text, 类型, 一级分类, 二级分类, confidence, reason. "
        "Do not classify personal names, ambiguous payees, bank transfers, or unknown merchants. "
        "For those, omit them from rules. Use only these 类型 values: 支出, 收入. "
        f"支出一级分类 allowed: {sorted(EXPENSE_CATEGORIES)}. "
        f"收入一级分类 allowed: {sorted(INCOME_CATEGORIES)}. "
        "Examples: PAK N SAVE => 支出/生活费; WOOLWORTHS => 支出/生活费; "
        "KFC => 支出/生活费/外食; GITHUB => 支出/应用软件; OPENAI => 支出/应用软件; "
        "POWERSHOP => 支出/住房/水电费."
    )


def append_rules(path: Path, suggestions: list[SuggestedRule]) -> int:
    if not suggestions:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_rule_rows(path)
    seen = {str(row.get("match_text") or "").strip().upper() for row in rows}
    added = 0
    for suggestion in suggestions:
        key = suggestion.match_text.upper()
        if key in seen:
            continue
        seen.add(key)
        added += 1
        rows.append(
            {
                "match_text": suggestion.match_text,
                "类型": suggestion.classification.tx_type,
                "一级分类": suggestion.classification.primary,
                "二级分类": suggestion.classification.secondary,
                "账户2": "",
                "备注规则": f"AI: {suggestion.reason} (confidence={suggestion.confidence:.2f})",
                "BNZ方向": "",
                "BNZ类型": "",
                "金额": "",
                "优先级": AI_RULE_PRIORITY,
            }
        )
    if added:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=RULE_HEADERS)
            writer.writeheader()
            writer.writerows({header: row.get(header, "") for header in RULE_HEADERS} for row in rows)
    return added


def read_rule_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [{header: str(row.get(header) or "") for header in RULE_HEADERS} for row in reader]
