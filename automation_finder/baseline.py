"""The comparison baseline: count the most frequent keywords and call each one a pattern.

This is what a quick spreadsheet analysis looks like ("which words come up most in our email and logs?").
Each of the top keywords becomes one candidate; its events are every event whose text contains the word, and its
cost is a flat five minutes per event.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from automation_finder.events import Event, mask, span_months

STOP = frozenset(
    """a an and are as at be but by can do for from has have i if in is it me my no not of on or our
    please re fw the this to was we will with you your new about any up out all just get got more some
    than that there what when who num ref date amount email person""".split()  # noqa: SIM905
)


@dataclass
class KeywordPattern:
    keyword: str
    events: list[str]
    hours_per_month: float


def keyword_patterns(events: list[Event], top: int = 10, minutes: float = 5.0) -> list[KeywordPattern]:
    staff = frozenset(e.actor for e in events)
    words_of: dict[str, set[str]] = {}
    counts: Counter[str] = Counter()
    for e in events:
        text = f"{e.action} {e.text}" if e.source == "activity" else e.text
        words = {w for w in re.findall(r"[a-z][a-z']+", mask(text, staff)) if w not in STOP and len(w) > 2}
        words_of[e.id] = words
        counts.update(words)
    months = span_months(events)
    out = []
    for word, n in counts.most_common(top):
        ids = [eid for eid, ws in words_of.items() if word in ws]
        out.append(KeywordPattern(word, ids, round(n * minutes / 60 / months, 2)))
    return out


def repeat_patterns(events: list[Event], top: int = 10, minutes: float = 5.0) -> list[KeywordPattern]:
    """A second, stronger baseline: count exact repeats (same masked subject, or same action in the same system)."""
    staff = frozenset(e.actor for e in events)
    groups: dict[str, list[str]] = {}
    for e in events:
        key = f"{e.system}:{e.action}" if e.source == "activity" else f"{e.source}:{mask(e.text, staff)}"
        groups.setdefault(key, []).append(e.id)
    months = span_months(events)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]
    return [KeywordPattern(k, ids, round(len(ids) * minutes / 60 / months, 2)) for k, ids in ranked]
