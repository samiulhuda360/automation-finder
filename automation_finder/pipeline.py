"""One analysis run: events in, ranked opportunities out."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from automation_finder.events import Event, display_mask, mask, span_months
from automation_finder.opportunities import Opportunity, TimeModel, build_opportunities
from automation_finder.patterns import Pattern, Settings, find_all
from automation_finder.similarity import Embedder, TfidfEmbedder, cluster


@dataclass
class Analysis:
    events: list[Event]
    patterns: list[Pattern]
    opportunities: list[Opportunity]
    key_labels: dict[str, str]
    months: float
    embedder: str
    time_model: TimeModel = field(default_factory=TimeModel)

    def summary(self) -> dict[str, object]:
        return {
            "events": len(self.events),
            "by_source": dict(Counter(e.source for e in self.events)),
            "people": len({e.actor for e in self.events}),
            "first": min(e.when for e in self.events).date().isoformat() if self.events else "",
            "last": max(e.when for e in self.events).date().isoformat() if self.events else "",
            "months": round(self.months, 2),
            "patterns": len(self.patterns),
            "opportunities": len(self.opportunities),
            "embedder": self.embedder,
        }


def _sender_groups(items: list[Event]) -> dict[str, list[int]]:
    """Inbound mail from a frequent outside sender (a supplier's billing system, a web form) is grouped by sender
    before its subjects are compared: who sent a message is part of what kind of message it is."""
    senders = Counter(e.extra.get("sender", "").lower() for e in items if e.direction == "inbound")
    need = max(6, round(2 * span_months(items)))
    out: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(items):
        sender = e.extra.get("sender", "").lower()
        if e.direction == "inbound" and senders[sender] >= need:
            out[f"from:{sender}"].append(i)
        else:
            out["inbound" if e.direction == "inbound" else "staff"].append(i)
    return out


def _text_for_similarity(e: Event, staff: frozenset[str]) -> str:
    if e.source == "ticket":  # title plus description: the description helps tell paraphrased requests apart
        return f"{mask(e.extra.get('subject', ''), staff)} {mask(e.text, staff)}".strip()
    return mask(e.text, staff)


def embedding_texts(events: list[Event]) -> list[str]:
    """Every masked text the similarity step will compare (used to fetch embeddings in large batches)."""
    staff = frozenset(e.actor for e in events if e.actor)
    return list(dict.fromkeys(_text_for_similarity(e, staff) for e in events if e.source != "activity"))


def assign_keys(events: list[Event], embedder: Embedder) -> dict[str, str]:
    """Gives every event a key naming what kind of event it is, and returns a readable label per key."""
    staff = frozenset(e.actor for e in events if e.actor)
    labels: dict[str, str] = {}
    for source in ("email", "ticket", "calendar"):
        items = [e for e in events if e.source == source]
        if not items:
            continue
        texts = [_text_for_similarity(e, staff) for e in items]
        groups: dict[str, list[Event]] = defaultdict(list)
        for part, indexes in _sender_groups(items).items():
            labels_in_part = cluster([texts[i] for i in indexes], embedder)
            for i, label in zip(indexes, labels_in_part, strict=True):
                items[i].key = f"{source}#{part}#{label}"
                groups[items[i].key].append(items[i])
        for key, members in groups.items():
            shown = Counter(display_mask(m.extra.get("subject", m.text)) for m in members).most_common(1)[0][0]
            labels[key] = shown
    for e in events:
        if e.source == "activity":
            e.key = f"{e.system}:{e.action}"
            labels.setdefault(e.key, f"{e.action} ({e.system})")
    return labels


def analyse(
    events: list[Event],
    embedder: Embedder | None = None,
    settings: Settings | None = None,
    time_model: TimeModel | None = None,
) -> Analysis:
    embedder = embedder or TfidfEmbedder()
    labels = assign_keys(events, embedder)
    patterns = find_all(events, settings)
    tm = time_model or TimeModel()
    opps = build_opportunities(patterns, events, labels, tm)
    return Analysis(events, patterns, opps, labels, span_months(events), embedder.name, tm)
