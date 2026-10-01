"""Map raw row labels onto canonical line items."""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from .schema import ITEMS, SYNONYM_INDEX, normalize_label

# A fuzzy match is rejected if one side contains a qualifier the other lacks;
# "total non current assets" must never be mistaken for "total current assets".
_QUALIFIERS = {
    "non", "other", "excluding", "deferred", "minority", "noncontrolling", "controlling",
    "accumulated", "comprehensive", "discontinued", "gain", "loss", "income", "change",
    "increase", "decrease", "per", "share", "diluted", "basic", "average", "lease",
}
FUZZY_CUTOFF = 0.88


@dataclass(frozen=True)
class Match:
    key: str
    rank: int  # synonym preference (lower is better)
    method: str  # "override" | "exact" | "fuzzy"
    matched_synonym: str


class LabelMapper:
    def __init__(self, overrides: dict[str, str] | None = None):
        self.overrides: dict[str, str] = {}
        for raw, key in (overrides or {}).items():
            if key not in ITEMS:
                raise ValueError(
                    f"Mapping override for '{raw}' targets unknown item '{key}'. "
                    f"Valid items: {', '.join(sorted(ITEMS))}"
                )
            self.overrides[normalize_label(raw)] = key
        self._synonyms = list(SYNONYM_INDEX)

    @classmethod
    def from_file(cls, path: str | Path | None) -> "LabelMapper":
        if not path:
            return cls()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("Mapping file must be a JSON object of {\"raw label\": \"item_key\"}")
        return cls(data)

    def match(self, label: str) -> Match | None:
        norm = normalize_label(label)
        if not norm or len(norm) < 2:
            return None
        if norm in self.overrides:
            return Match(self.overrides[norm], -1, "override", norm)
        if norm in SYNONYM_INDEX:
            key, rank = SYNONYM_INDEX[norm]
            return Match(key, rank, "exact", norm)
        # Fuzzy fallback for typos / minor wording differences.
        for cand in difflib.get_close_matches(norm, self._synonyms, n=3, cutoff=FUZZY_CUTOFF):
            a, b = set(norm.split()), set(cand.split())
            if (a ^ b) & _QUALIFIERS:
                continue
            # Require the same number of words to stay conservative.
            if abs(len(a) - len(b)) > 1:
                continue
            key, rank = SYNONYM_INDEX[cand]
            return Match(key, rank + 100, "fuzzy", cand)
        return None
