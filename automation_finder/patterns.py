"""The four detectors. Each one reads the keyed events and returns candidate patterns with their evidence.

- near-duplicate requests: the same kind of request arriving again and again (tickets, answered emails);
- periodic routines: the same staff action at a regular time (daily, weekly or monthly);
- copy between systems: something arrives or happens in system A and the same person enters a record in
  system B shortly afterwards, far more often than chance would explain;
- hand-offs: one piece of work (linked by a reference such as PO-2041 or J-5521) passes between people.
"""

from __future__ import annotations

import bisect
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from automation_finder.events import Event, business_days, display_mask, span_months, working_minutes_between

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
APPROVAL_WORDS = ("approv", "authoris", "authoriz", "sign off", "sign-off", "declin", "reject")


@dataclass
class Settings:
    copy_window_min: float = 45.0  # working minutes between the two steps of a copy
    copy_min_support: int = 6
    copy_min_confidence: float = 0.5
    copy_min_lift: float = 3.0
    min_per_month: float = 2.0  # a pattern must happen at least this often to be worth a look
    min_count: int = 6
    reply_rate: float = 0.5  # share of inbound emails in a group that get a reply for it to count as work
    periodic_share: float = 0.7
    periodic_hour_spread: float = 1.25  # hours (standard deviation of the time of day)
    handoff_min_chains: int = 6


@dataclass
class Pattern:
    kind: str  # near_duplicate | periodic | copy | handoff
    actors: list[str]
    systems: list[str]
    events: list[str]
    occurrences: int
    keys: list[str]
    detail: dict[str, object] = field(default_factory=dict)


def _min_count(events: list[Event], s: Settings) -> int:
    return max(s.min_count, round(s.min_per_month * span_months(events)))


# --------------------------------------------------------------------------------------------- near-duplicates
def find_near_duplicates(events: list[Event], s: Settings) -> list[Pattern]:
    need = _min_count(events, s)
    groups: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.source == "ticket" or (e.source == "email" and e.direction == "inbound"):
            groups[e.key].append(e)
    replies: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for e in events:
        if e.source == "email" and e.direction in ("outbound", "internal"):
            replies[(e.actor, e.thread)].append(e)
    out = []
    for key, items in groups.items():
        if len(items) < need:
            continue
        if items[0].source == "email":
            answered = sum(any(r.when > i.when for r in replies.get((i.actor, i.thread), [])) for i in items)
            rate = answered / len(items)
            if rate < s.reply_rate:
                continue  # notifications and newsletters: they arrive, nobody acts on them
        actors = Counter(i.actor for i in items)
        out.append(
            Pattern(
                kind="near_duplicate",
                actors=[a for a, _ in actors.most_common()],
                systems=[items[0].system],
                events=[i.id for i in items],
                occurrences=len(items),
                keys=[key],
                detail={"variants": len({i.text for i in items})},
            )
        )
    return out


# --------------------------------------------------------------------------------------------- periodic
def _is_staff_task(e: Event) -> bool:
    if e.source == "activity":
        return True
    if e.source == "email":
        return e.direction in ("outbound", "internal")
    if e.source == "calendar":
        return e.attendees == 0  # a solo block of work; meetings with others are not chores to automate
    return False


def _bd_index(d: date) -> tuple[int, int]:
    """Working-day position of a date within its month, from the start and from the end (0 = first/last)."""
    first = date(d.year, d.month, 1)
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    days = [x for x in business_days(first, nxt) if x.month == d.month]
    i = days.index(d) if d in days else 0
    return i, len(days) - 1 - i


def periodicity(items: list[Event], all_days: list[date], s: Settings) -> dict[str, object] | None:
    hours = [e.when.hour + e.when.minute / 60 for e in items]
    spread = statistics.pstdev(hours) if len(hours) > 1 else 0.0
    if spread > s.periodic_hour_spread:
        return None
    hour = statistics.median(hours)
    days = sorted({e.when.date() for e in items})
    if len(days) >= s.periodic_share * len(all_days) and len(days) >= 10:
        return {"period": "daily", "anchor": "every working day", "hour": hour}
    by_weekday = Counter(d.weekday() for d in days)
    wd, n = by_weekday.most_common(1)[0]
    slots = [d for d in all_days if d.weekday() == wd]
    if len(slots) >= 4 and n >= s.periodic_share * len(slots) and n >= s.periodic_share * len(days):
        return {"period": "weekly", "anchor": f"every {WEEKDAYS[wd]}", "hour": hour}
    months = sorted({(d.year, d.month) for d in all_days})
    hit_months = {(d.year, d.month) for d in days}
    if len(months) >= 3 and len(hit_months) >= s.periodic_share * len(months) and len(days) <= 2 * len(months):
        idx = [_bd_index(d) for d in days]
        start_ok = sum(i <= 1 for i, _ in idx) / len(idx)
        end_ok = sum(j <= 1 for _, j in idx) / len(idx)
        if max(start_ok, end_ok) >= 0.8:
            where = "first working day" if start_ok >= end_ok else "last working day"
            return {"period": "monthly", "anchor": f"on the {where} of each month", "hour": hour}
    return None


def find_periodic(events: list[Event], s: Settings) -> list[Pattern]:
    if not events:
        return []
    all_days = business_days(min(e.when for e in events).date(), max(e.when for e in events).date())
    groups: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for e in events:
        if _is_staff_task(e):
            groups[(e.actor, e.key)].append(e)
    out = []
    for (actor, key), items in groups.items():
        if len(items) < 3:
            continue
        found = periodicity(items, all_days, s)
        if found is None:
            continue
        out.append(
            Pattern(
                kind="periodic",
                actors=[actor],
                systems=sorted({e.system for e in items}),
                events=[e.id for e in items],
                occurrences=len(items),
                keys=[key],
                detail=found,
            )
        )
    return out


# --------------------------------------------------------------------------------------------- copy between systems
def find_copies(events: list[Event], s: Settings) -> list[Pattern]:
    by_actor: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_actor[e.actor].append(e)
    n_days = len(business_days(min(e.when for e in events).date(), max(e.when for e in events).date())) or 1
    active_minutes = n_days * 11 * 60
    out = []
    for actor, items in by_actor.items():
        sources = [e for e in items if e.source in ("ticket", "activity") or e.direction == "inbound"]
        targets = [e for e in items if e.source == "activity"]
        target_times = [t.when for t in targets]
        key_count = Counter(e.key for e in sources)
        target_count = Counter(t.key for t in targets)
        candidates: dict[tuple[str, str], list[tuple[Event, Event]]] = defaultdict(list)
        for a in sources:
            seen: set[str] = set()
            for j in range(bisect.bisect_right(target_times, a.when), len(targets)):
                b = targets[j]
                if (b.when - a.when).days > 4:
                    break
                if b.system == a.system or b.key in seen:
                    continue
                if working_minutes_between(a.when, b.when) > s.copy_window_min:
                    break  # targets are in time order, so every later one is further away
                seen.add(b.key)
                candidates[(a.key, b.key)].append((a, b))
        for (ka, kb), pairs in candidates.items():
            used: set[str] = set()
            matched = []
            for a, b in sorted(pairs, key=lambda p: (p[0].when, p[1].when)):
                if b.id not in used:
                    used.add(b.id)
                    matched.append((a, b))
            support = len(matched)
            if support < s.copy_min_support:
                continue
            confidence = support / key_count[ka]
            chance = min(1.0, target_count[kb] * s.copy_window_min / active_minutes)
            lift = support / max(key_count[ka] * chance, 1e-9)
            if confidence < s.copy_min_confidence or lift < s.copy_min_lift:
                continue
            a0, b0 = matched[0]
            out.append(
                Pattern(
                    kind="copy",
                    actors=[actor],
                    systems=[a0.system, b0.system],
                    events=[x.id for pair in matched for x in pair],
                    occurrences=support,
                    keys=[ka, kb],
                    detail={
                        "confidence": round(confidence, 2),
                        "lift": round(lift, 1),
                        "median_gap_min": round(
                            statistics.median(working_minutes_between(a.when, b.when) for a, b in matched), 1
                        ),
                        "target_action": b0.action,
                    },
                )
            )
    return out


# --------------------------------------------------------------------------------------------- hand-offs
def _ref_type(ref: str) -> str:
    return ref.split("-")[0]


def _step_key(e: Event) -> str:
    return e.key if e.source == "activity" else e.system


def _route(group: list[list[Event]], step_lists: dict[str, list[list[Event]]]) -> list[dict[str, object]]:
    """The usual route, one entry per person's turn: what is done, who does it, and an example (ids hidden)."""
    routes = Counter(tuple(_step_key(step[-1]) for step in step_lists[chain[0].primary_ref]) for chain in group)
    usual = routes.most_common(1)[0][0]
    people: list[Counter[str]] = [Counter() for _ in usual]
    examples: list[Counter[str]] = [Counter() for _ in usual]
    for chain in group:
        steps = step_lists[chain[0].primary_ref]
        if tuple(_step_key(step[-1]) for step in steps) != usual:
            continue
        for i, step in enumerate(steps):
            people[i][step[-1].actor] += 1
            examples[i][display_mask(step[-1].text)] += 1
    return [
        {
            "step": key,
            "people": [a for a, _ in people[i].most_common(3)],
            "count": len(people[i]),
            "example": examples[i].most_common(1)[0][0] if examples[i] else "",
        }
        for i, key in enumerate(usual)
    ]


def find_handoffs(events: list[Event], s: Settings) -> list[Pattern]:
    need = max(s.handoff_min_chains, round(s.min_per_month * span_months(events)))
    chains: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.primary_ref:
            chains[e.primary_ref].append(e)
    groups: dict[tuple[str, str], list[list[Event]]] = defaultdict(list)
    step_counts: dict[str, int] = {}
    step_lists: dict[str, list[list[Event]]] = {}
    for ref, chain in chains.items():
        chain.sort(key=lambda e: e.when)
        steps: list[list[Event]] = []
        for e in chain:
            if steps and steps[-1][-1].actor == e.actor:
                steps[-1].append(e)
            else:
                steps.append([e])
        if len({e.actor for e in chain}) < 2:
            continue
        step_counts[ref] = len(steps)
        step_lists[ref] = steps
        groups[(_ref_type(ref), _step_key(steps[0][-1]))].append(chain)
    out = []
    for (ref_type, first_step), group in groups.items():
        if len(group) < need:
            continue
        flat = [e for chain in group for e in chain]
        roles: Counter[str] = Counter()
        for chain in group:
            roles.update(set(e.actor for e in chain))
        text = " ".join(e.text.lower() for e in flat)
        signatures = Counter(tuple(dict.fromkeys(_step_key(e) for e in chain)) for chain in group)
        steps_per_chain = statistics.mean(step_counts[chain[0].primary_ref] for chain in group)
        route = _route(group, step_lists)
        out.append(
            Pattern(
                kind="handoff",
                actors=[a for a, _ in roles.most_common()],
                systems=sorted({e.system for e in flat}),
                events=[e.id for e in flat],
                occurrences=len(group),
                keys=sorted({e.key for e in flat}),
                detail={
                    "ref_type": ref_type,
                    "first_step": first_step,
                    "approval": any(w in text for w in APPROVAL_WORDS),
                    "steps_per_chain": round(steps_per_chain, 1),
                    "common_route": list(signatures.most_common(1)[0][0]),
                    "route": route,
                },
            )
        )
    return out


def find_all(events: list[Event], s: Settings | None = None) -> list[Pattern]:
    s = s or Settings()
    return (
        find_near_duplicates(events, s) + find_periodic(events, s) + find_copies(events, s) + find_handoffs(events, s)
    )
