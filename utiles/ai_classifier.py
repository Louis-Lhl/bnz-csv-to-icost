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
AI_ALLOWED_SECONDARIES = {
    "生活费": {"三餐", "零食", "水果", "蔬菜", "外食"},
    "住房": {"房租", "水电费"},
}
AI_SECONDARY_ALIASES = {
    "饮品": ("生活费", "外食"),
    "饮料": ("生活费", "外食"),
    "咖啡": ("生活费", "外食"),
    "奶茶": ("生活费", "外食"),
    "快餐": ("生活费", "外食"),
    "餐饮": ("生活费", "外食"),
}


@dataclass(frozen=True)
class SuggestedRule:
    match_text: str
    classification: Classification
    reason: str
    confidence: float
    direction: str = ""
    bank_type: str = ""


@dataclass(frozen=True)
class AITransactionContext:
    payee: str
    particulars: str
    code: str
    reference: str
    tran_type: str
    direction: str

    @property
    def match_source(self) -> str:
        return self.payee or self.particulars or self.code or self.reference

    def to_payload(self) -> dict[str, str]:
        payee = "[private_payee]" if likely_sensitive_payee(self.payee) else self.payee
        return {
            "payee": payee,
            "particulars": self.particulars,
            "code": self.code,
            "reference": self.reference,
            "tran_type": self.tran_type,
            "direction": self.direction,
        }


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
    if "," in text or "&" in text or " GIFT" in upper or upper.endswith(" GIFT"):
        return True
    tokens = re.findall(r"[A-Za-z]+", text)
    if 2 <= len(tokens) <= 4 and all(token[:1].isupper() and token[1:].islower() for token in tokens):
        return True
    return False


class PayeeAIClassifier:
    def __init__(self, env_file: Path, local_rules_file: Path) -> None:
        load_dotenv(env_file)
        self.local_rules_file = local_rules_file
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    def classify_and_save(self, contexts: list[AITransactionContext]) -> int:
        candidates = dedupe_contexts(contexts)
        if not candidates:
            LOGGER.info("AI classification skipped: no useful transaction context candidates")
            return 0
        if not self.api_key:
            LOGGER.warning("AI classification skipped: OPENAI_API_KEY is not set")
            return 0

        LOGGER.info("Sending %d unique transaction contexts to AI classification", len(candidates))
        suggestions = self._request_suggestions(candidates)
        accepted = [
            suggestion
            for suggestion in suggestions
            if suggestion.confidence >= MIN_CONFIDENCE and is_valid_classification(suggestion.classification)
        ]
        LOGGER.info("AI returned %d suggestions; accepted %d", len(suggestions), len(accepted))
        return append_rules(self.local_rules_file, accepted)

    def _request_suggestions(self, contexts: list[AITransactionContext]) -> list[SuggestedRule]:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": json.dumps({"transactions": [context.to_payload() for context in contexts]}, ensure_ascii=False)},
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
            classification = normalize_ai_classification(
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
                    direction=matched_context_value(match_text, contexts, "direction"),
                    bank_type=matched_context_value(match_text, contexts, "tran_type"),
                )
            )
        return suggestions


def matched_context_value(match_text: str, contexts: list[AITransactionContext], field: str) -> str:
    needle = match_text.strip().upper()
    if not needle:
        return ""
    for context in contexts:
        payload = context.to_payload()
        for source_field in ["payee", "particulars", "code", "reference"]:
            if needle in payload[source_field].upper():
                return payload[field]
    return ""


def dedupe_contexts(contexts: list[AITransactionContext]) -> list[AITransactionContext]:
    unique: dict[tuple[str, str, str, str, str, str], AITransactionContext] = {}
    for context in contexts:
        if not context.match_source.strip():
            continue
        payload = context.to_payload()
        if payload["payee"] == "[private_payee]" and not any(payload[field].strip() for field in ["particulars", "code", "reference"]):
            continue
        key = tuple(payload[field].strip().upper() for field in ["payee", "particulars", "code", "reference", "tran_type", "direction"])
        unique.setdefault(key, context)
    return sorted(unique.values(), key=lambda item: item.match_source.upper())


def normalize_ai_classification(tx_type: str, primary: str, secondary: str) -> Classification:
    if secondary in AI_SECONDARY_ALIASES:
        primary, secondary = AI_SECONDARY_ALIASES[secondary]
    if secondary and secondary not in AI_ALLOWED_SECONDARIES.get(primary, set()):
        secondary = ""
    return Classification(tx_type=tx_type, primary=primary, secondary=secondary)


def create_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def system_prompt() -> str:
    return (
        "You classify New Zealand bank transaction context snippets for iCost personal finance import. "
        "You receive selected fields only: payee, particulars, code, reference, tran_type, direction. "
        "You never receive dates, amounts, account names, account numbers, balances, or full CSV rows. "
        "Return JSON only, with key 'rules'. "
        "For each clear merchant or clear reimbursement purpose, return match_text, 类型, 一级分类, 二级分类, confidence, reason. "
        "Use match_text as the shortest stable text that appears in one of payee/particulars/code/reference. "
        "Do not classify personal names by name alone, ambiguous payees, bank transfers, or unknown merchants. "
        "If payee is [private_payee], use only particulars/code/reference/tran_type/direction to infer purpose. "
        "Example: direction=收入 with particulars/code/reference containing Lunch, Dinner, Cafe, Restaurant, Food, Meal, Brunch "
        "usually means reimbursement or bill split and can be 收入/生活费/外食. "
        "Example: direction=收入 with particulars/code/reference containing Hotel, Airbnb, Accommodation, Trip, Travel "
        "can be 收入/旅游 when it is a shared travel cost reimbursement. "
        "For those, omit them from rules. Use only these 类型 values: 支出, 收入. "
        "Do not invent secondary categories. 二级分类 may only be one of: "
        "生活费/三餐, 生活费/零食, 生活费/水果, 生活费/蔬菜, 生活费/外食, 住房/房租, 住房/水电费. "
        "For all other primary categories, leave 二级分类 empty. "
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
                "BNZ方向": suggestion.direction,
                "BNZ类型": suggestion.bank_type,
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
