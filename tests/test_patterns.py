from __future__ import annotations

from datetime import date, datetime, timedelta

from automation_finder.events import Event
from automation_finder.patterns import Settings, find_copies, find_handoffs, find_near_duplicates, find_periodic

MONDAY = date(2026, 6, 1)


def ev(
    i: str,
    when: datetime,
    *,
    source: str = "activity",
    system: str = "accounts",
    actor: str = "emma",
    key: str = "",
    direction: str = "self",
    text: str = "",
    ref: str = "",
    thread: str = "",
) -> Event:
    return Event(
        id=i,
        source=source,
        system=system,
        actor=actor,
        when=when,
        text=text or key,
        key=key or text,
        direction=direction,
        primary_ref=ref,
        thread=thread,
        action=key.split(":")[-1],
    )


def days(n: int) -> list[date]:
    out, d = [], MONDAY
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


def test_copy_needs_a_consistent_follow_up_and_beats_chance() -> None:
    events = []
    for i, d in enumerate(days(30)):
        events.append(ev(f"m{i}", at(d, 9), source="email", system="email", key="email#invoice", direction="inbound"))
        events.append(ev(f"a{i}", at(d, 9, 15), key="accounts:enter bill"))
        events.append(ev(f"n{i}", at(d, 13 + i % 4), key="accounts:reconcile"))  # unrelated, irregular
    (p,) = find_copies(events, Settings())
    assert p.keys == ["email#invoice", "accounts:enter bill"]
    assert p.occurrences == 30 and p.detail["confidence"] == 1.0 and p.detail["lift"] >= 3


def test_copy_ignores_an_action_that_is_done_all_day_anyway() -> None:
    events = []
    for i, d in enumerate(days(30)):
        events.append(ev(f"m{i}", at(d, 9), source="email", system="email", key="email#x", direction="inbound"))
        for h in range(7, 18):  # this person creates invoices every hour, whatever arrives
            events.append(ev(f"a{i}-{h}", at(d, h, 10), key="accounts:create invoice"))
    assert find_copies(events, Settings()) == []


def test_weekly_routine_is_found_and_irregular_work_is_not() -> None:
    events = []
    for i, d in enumerate(days(60)):
        if d.weekday() == 4:
            events.append(ev(f"r{i}", at(d, 14), key="payroll:check timesheets", actor="james"))
        events.append(ev(f"j{i}", at(d, 7 + (i * 5) % 10), key="jobs:start job", actor="tom"))
    found = find_periodic(events, Settings())
    assert [(p.actors, p.detail["period"], p.detail["anchor"]) for p in found] == [
        (["james"], "weekly", "every Friday")
    ]


def test_meetings_with_other_people_are_not_routines() -> None:
    events = [
        Event(
            id=f"c{i}",
            source="calendar",
            system="calendar",
            actor="james",
            when=at(d, 7),
            text="Toolbox",
            key="calendar#0",
            attendees=8,
        )
        for i, d in enumerate(days(60))
        if d.weekday() == 0
    ]
    assert find_periodic(events, Settings()) == []


def test_handoff_follows_a_reference_across_people() -> None:
    events = []
    for i, d in enumerate(days(20)):
        ref = f"J-{100 + i}"
        events.append(ev(f"s{i}", at(d, 9), key="jobs:complete job", system="jobs", actor="tom", ref=ref))
        events.append(ev(f"e{i}", at(d, 15), key="accounts:create invoice", actor="emma", ref=ref))
    (p,) = find_handoffs(events, Settings())
    assert p.occurrences == 20 and p.detail["ref_type"] == "J" and p.detail["steps_per_chain"] == 2
    assert [r["step"] for r in p.detail["route"]] == ["jobs:complete job", "accounts:create invoice"]


def test_near_duplicate_emails_need_replies_to_count_as_work() -> None:
    events = []
    for i, d in enumerate(days(20)):
        events.append(
            ev(
                f"n{i}",
                at(d, 6),
                source="email",
                system="email",
                key="email#news",
                direction="inbound",
                thread="weekly specials",
            )
        )
        events.append(
            ev(
                f"q{i}",
                at(d, 10),
                source="email",
                system="email",
                key="email#ask",
                direction="inbound",
                thread=f"question {i}",
            )
        )
        events.append(
            ev(
                f"r{i}",
                at(d, 11),
                source="email",
                system="email",
                key="email#reply",
                direction="outbound",
                thread=f"question {i}",
            )
        )
    found = find_near_duplicates(events, Settings())
    assert [p.keys for p in found] == [["email#ask"]]
