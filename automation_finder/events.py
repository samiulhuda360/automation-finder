"""The common event record every export is turned into, plus the text clean-up shared by the detectors."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

REF_RE = re.compile(r"\b[A-Z]{1,4}-\d{3,7}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(\.\d+)?")
MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
DATE_RE = re.compile(rf"\b(\d{{1,2}}\s+({MONTHS})|({MONTHS})\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}(/\d{{2,4}})?|w/e)\b")
NUM_RE = re.compile(r"\b\d+([.,]\d+)?\b")
PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw|sv)\s*:\s*)+", re.IGNORECASE)

WORK_START = 7 * 60  # working day used for gaps measured in working minutes
WORK_END = 18 * 60


@dataclass
class Event:
    id: str  # "<source>:<row id>", stable across runs
    source: str  # email | ticket | calendar | activity
    system: str  # the business system the work happened in
    actor: str  # the staff member doing the work (a short person key)
    when: datetime
    text: str  # what a person would read: subject, ticket title, action and details
    action: str = ""  # activity verb, e.g. "enter supplier bill"
    direction: str = "self"  # inbound | outbound | internal | self
    refs: tuple[str, ...] = ()
    primary_ref: str = ""
    thread: str = ""  # email subject without RE:/FW: prefixes
    duration_min: float | None = None
    attendees: int = 0  # other people on a calendar entry
    key: str = ""  # what kind of event this is; set by the clustering step
    extra: dict[str, str] = field(default_factory=dict)


def num(value: object, default: float = 0.0) -> float:
    """A number from loosely typed evidence (detail dicts hold mixed values)."""
    return float(value) if isinstance(value, int | float | str) and str(value).strip() else default


def seq(value: object) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def person_key(value: str) -> str:
    """'emma.wilson@x.example', 'Emma Wilson' and 'emma' all become 'emma'."""
    value = value.strip().strip('"').lower()
    if not value:
        return ""
    if "<" in value and ">" in value:
        value = value[value.index("<") + 1 : value.index(">")]
    if "@" in value:
        value = value.split("@")[0]
    return re.split(r"[\s._-]+", value)[0]


def domain_of(address: str) -> str:
    address = address.strip().lower()
    if "<" in address and ">" in address:
        address = address[address.index("<") + 1 : address.index(">")]
    return address.split("@")[1] if "@" in address else ""


def find_refs(*texts: str) -> tuple[str, ...]:
    seen: list[str] = []
    for text in texts:
        for ref in REF_RE.findall(text or ""):
            if ref not in seen:
                seen.append(ref)
    return tuple(seen)


def thread_of(subject: str) -> str:
    return PREFIX_RE.sub("", subject or "").strip().lower()


def mask(text: str, names: frozenset[str] = frozenset()) -> str:
    """Hides the parts that change between repeats of the same task (ids, amounts, dates, numbers, names).

    "FW: PO request PO-2041 ($1,240)" and "PO request PO-2077 ($310)" both become "po request <ref> <amount>",
    so the same chore is recognised however its details vary. It also keeps personal details out of anything that
    is sent to an embedding model.
    """
    out = PREFIX_RE.sub("", text or "")
    out = EMAIL_RE.sub(" <email> ", out)
    out = REF_RE.sub(" <ref> ", out)
    out = MONEY_RE.sub(" <amount> ", out)
    out = out.lower()
    out = DATE_RE.sub(" <date> ", out)
    out = NUM_RE.sub(" <num> ", out)
    if names:
        out = " ".join("<person>" if w in names else w for w in out.split())
    return re.sub(r"\s+", " ", out).strip()


def working_minutes_between(a: datetime, b: datetime) -> float:
    """Minutes of working time (Mon-Fri, 07:00-18:00) from a to b; work arriving overnight waits for the morning."""
    if b <= a:
        return 0.0
    total = 0.0
    day = a.date()
    while day <= b.date():
        if day.weekday() < 5:
            start = datetime.combine(day, datetime.min.time()) + timedelta(minutes=WORK_START)
            end = datetime.combine(day, datetime.min.time()) + timedelta(minutes=WORK_END)
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return total


def business_days(first: date, last: date) -> list[date]:
    days = []
    d = first
    while d <= last:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def span_months(events: list[Event]) -> float:
    if not events:
        return 1.0
    first = min(e.when for e in events).date()
    last = max(e.when for e in events).date()
    return max(((last - first).days + 1) / 30.44, 0.25)


def display_mask(text: str) -> str:
    """Like mask(), but keeps the wording readable for people: 'Invoice [ref] from Plumbing World'."""
    out = PREFIX_RE.sub("", text or "")
    out = EMAIL_RE.sub("[email]", out)
    out = REF_RE.sub("[ref]", out)
    out = MONEY_RE.sub("[amount]", out)
    out = DATE_RE.sub("[date]", out) if not DATE_RE.search(out.lower()) else _mask_dates(out)
    out = NUM_RE.sub("[n]", out)
    return re.sub(r"\s+", " ", out).strip()


def _mask_dates(text: str) -> str:
    return re.sub(DATE_RE.pattern, "[date]", text, flags=re.IGNORECASE)
