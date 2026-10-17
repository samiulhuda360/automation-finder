"""Turns uploaded exports into events.

Each CSV kind has a few canonical fields. The loader guesses which column holds each field from the header names
(the guess is shown in the web page and can be changed), so exports from different tools work without editing
the files. Calendars are read from standard .ics files, including weekly and monthly repeating entries.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from dateutil import parser as dateparser
from dateutil.rrule import rrulestr

from automation_finder.events import Event, domain_of, find_refs, person_key, thread_of

KINDS = ("email", "ticket", "activity", "calendar")

FIELDS: dict[str, dict[str, tuple[bool, tuple[str, ...]]]] = {
    # field: (required, header names that usually hold it)
    "email": {
        "id": (False, ("message id", "message-id", "id", "internet message id")),
        "sender": (True, ("from", "sender", "sender address", "from address")),
        "recipients": (True, ("to", "recipients", "recipient", "to address")),
        "subject": (True, ("subject", "title")),
        "time": (True, ("date", "received", "sent", "time", "timestamp", "date received", "received time")),
        "folder": (False, ("folder", "mailbox folder", "location")),
    },
    "ticket": {
        "id": (False, ("ticket id", "id", "ticket", "number", "ticket number")),
        "created": (True, ("created", "created at", "opened", "date", "created date")),
        "requester": (False, ("requester", "customer", "from", "requester email", "contact")),
        "subject": (True, ("subject", "title", "summary")),
        "description": (False, ("description", "body", "details", "message")),
        "assignee": (True, ("assignee", "assigned to", "agent", "owner")),
        "closed": (False, ("closed", "closed at", "resolved", "resolved at")),
    },
    "activity": {
        "id": (False, ("event id", "id", "log id")),
        "user": (True, ("user", "who", "person", "actor", "staff", "employee")),
        "action": (True, ("action", "what", "activity", "event", "operation")),
        "time": (True, ("timestamp", "when", "time", "date", "datetime")),
        "system": (True, ("system", "app", "application", "tool", "source")),
        "record": (False, ("record", "record id", "reference", "ref", "object")),
        "details": (False, ("details", "description", "notes", "info")),
    },
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def guess_mapping(kind: str, headers: list[str]) -> dict[str, str]:
    """Best guess of field -> column header, by exact then partial name match."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    normed = {h: _norm(h) for h in headers}
    for fld, (_, names) in FIELDS[kind].items():
        choice = next((h for h in headers if h not in used and normed[h] in names), None)
        if choice is None:
            choice = next((h for h in headers if h not in used and any(n in normed[h] for n in names)), None)
        if choice is not None:
            mapping[fld] = choice
            used.add(choice)
    return mapping


def missing_fields(kind: str, mapping: dict[str, str]) -> list[str]:
    return [f for f, (required, _) in FIELDS[kind].items() if required and not mapping.get(f)]


def read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def parse_time(value: str) -> datetime:
    return dateparser.parse(value, dayfirst=False).replace(tzinfo=None)


def detect_internal_domain(rows: Iterable[tuple[str, str]]) -> str:
    """The organisation's own domain: the one that appears in the most messages (as sender or recipient)."""
    counts: Counter[str] = Counter()
    for sender, recipients in rows:
        domains = {domain_of(sender)} | {domain_of(r) for r in re.split(r"[;,]", recipients)}
        counts.update(d for d in domains if d)
    return counts.most_common(1)[0][0] if counts else ""


def load_emails(text: str, mapping: dict[str, str] | None = None, internal_domain: str = "") -> list[Event]:
    headers, rows = read_csv(text)
    m = mapping or guess_mapping("email", headers)
    if missing := missing_fields("email", m):
        raise ValueError(f"email export is missing columns for: {', '.join(missing)}")
    domain = internal_domain or detect_internal_domain((r[m["sender"]], r[m["recipients"]]) for r in rows)
    events = []
    for i, r in enumerate(rows):
        sender = r[m["sender"]].strip()
        recipients = [x.strip() for x in re.split(r"[;,]", r[m["recipients"]]) if x.strip()]
        internal_to = [x for x in recipients if domain_of(x) == domain]
        sender_internal = domain_of(sender) == domain
        if sender_internal:
            actor = person_key(sender)
            direction = "internal" if internal_to else "outbound"
        elif internal_to:
            actor = person_key(internal_to[0])
            direction = "inbound"
        else:
            continue  # nothing to do with this organisation
        subject = r[m["subject"]]
        refs = find_refs(subject)
        events.append(
            Event(
                id=f"email:{r.get(m.get('id', ''), '') or i}",
                source="email",
                system="email",
                actor=actor,
                when=parse_time(r[m["time"]]),
                text=subject,
                direction=direction,
                refs=refs,
                primary_ref=refs[0] if refs else "",
                thread=thread_of(subject),
                extra={"sender": sender, "folder": r.get(m.get("folder", ""), "") or ""},
            )
        )
    return events


def load_tickets(text: str, mapping: dict[str, str] | None = None) -> list[Event]:
    headers, rows = read_csv(text)
    m = mapping or guess_mapping("ticket", headers)
    if missing := missing_fields("ticket", m):
        raise ValueError(f"ticket export is missing columns for: {', '.join(missing)}")
    events = []
    for i, r in enumerate(rows):
        subject = r[m["subject"]]
        body = r.get(m.get("description", ""), "") or ""
        refs = find_refs(subject, body)
        events.append(
            Event(
                id=f"ticket:{r.get(m.get('id', ''), '') or i}",
                source="ticket",
                system="helpdesk",
                actor=person_key(r[m["assignee"]]),
                when=parse_time(r[m["created"]]),
                text=f"{subject}. {body}".strip(". ") if body else subject,
                direction="inbound",
                refs=refs,
                primary_ref=refs[0] if refs else "",
                thread=thread_of(subject),
                extra={"subject": subject},
            )
        )
    return events


def load_activity(text: str, mapping: dict[str, str] | None = None) -> list[Event]:
    headers, rows = read_csv(text)
    m = mapping or guess_mapping("activity", headers)
    if missing := missing_fields("activity", m):
        raise ValueError(f"activity log is missing columns for: {', '.join(missing)}")
    events = []
    for i, r in enumerate(rows):
        action = r[m["action"]].strip()
        record = (r.get(m.get("record", ""), "") or "").strip()
        details = (r.get(m.get("details", ""), "") or "").strip()
        refs = find_refs(record, details)
        events.append(
            Event(
                id=f"activity:{r.get(m.get('id', ''), '') or i}",
                source="activity",
                system=r[m["system"]].strip().lower() or "other",
                actor=person_key(r[m["user"]]),
                when=parse_time(r[m["time"]]),
                text=f"{action}: {details}" if details else action,
                action=action.lower(),
                direction="self",
                refs=refs,
                primary_ref=record or (refs[0] if refs else ""),
            )
        )
    return events


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _ics_value(line: str) -> tuple[str, str, str]:
    head, _, value = line.partition(":")
    name, _, params = head.partition(";")
    return name.upper(), params, value


def _ics_time(value: str) -> datetime:
    return parse_time(value.rstrip("Z"))


def load_calendar(text: str, until: datetime | None = None) -> list[Event]:
    """Reads VEVENTs; repeating entries (RRULE) become one event per occurrence."""
    events: list[Event] = []
    current: dict[str, list[tuple[str, str]]] | None = None
    for line in _unfold(text):
        name, params, value = _ics_value(line)
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            events += _expand(current, until)
            current = None
        elif current is not None:
            current.setdefault(name, []).append((params, value))
    return events


def _expand(vevent: dict[str, list[tuple[str, str]]], until: datetime | None) -> list[Event]:
    def first(name: str) -> str:
        return vevent.get(name, [("", "")])[0][1]

    if not first("DTSTART"):
        return []
    start = _ics_time(first("DTSTART"))
    end = _ics_time(first("DTEND")) if first("DTEND") else start + timedelta(hours=1)
    organizer = first("ORGANIZER").replace("mailto:", "").replace("MAILTO:", "")
    attendees = {person_key(v.replace("mailto:", "").replace("MAILTO:", "")) for _, v in vevent.get("ATTENDEE", [])}
    actor = person_key(organizer)
    attendees.discard(actor)
    uid = first("UID") or f"{start.isoformat()}-{first('SUMMARY')}"
    summary = first("SUMMARY").replace("\\,", ",")
    starts = [start]
    if first("RRULE"):
        rule = rrulestr(first("RRULE"), dtstart=start)
        limit = until or start + timedelta(days=366)
        starts = list(rule.between(start, limit, inc=True))[:500]
    duration = (end - start).total_seconds() / 60
    return [
        Event(
            id=f"calendar:{uid}" if len(starts) == 1 and not first("RRULE") else f"calendar:{uid}#{s:%Y%m%dT%H%M%S}",
            source="calendar",
            system="calendar",
            actor=actor,
            when=s,
            text=summary,
            direction="self",
            refs=find_refs(summary),
            primary_ref="",
            duration_min=duration,
            attendees=len(attendees),
        )
        for s in starts
    ]


def load(kind: str, text: str, mapping: dict[str, str] | None = None) -> list[Event]:
    if kind == "email":
        return load_emails(text, mapping)
    if kind == "ticket":
        return load_tickets(text, mapping)
    if kind == "activity":
        return load_activity(text, mapping)
    if kind == "calendar":
        return load_calendar(text)
    raise ValueError(f"unknown export kind: {kind}")


def detect_kind(filename: str, text: str) -> str:
    """Guesses what an uploaded file is from its name and header row."""
    if filename.lower().endswith(".ics") or text.lstrip().startswith("BEGIN:VCALENDAR"):
        return "calendar"
    headers, _ = read_csv(text.split("\n", 1)[0] + "\n")
    scores = {}
    for kind in ("email", "ticket", "activity"):
        mapping = guess_mapping(kind, headers)
        scores[kind] = len(mapping) - 2 * len(missing_fields(kind, mapping))
    return max(scores, key=lambda k: scores[k])


def load_all(files: Mapping[str, tuple[str, str, dict[str, str] | None]]) -> list[Event]:
    """files: name -> (kind, text, mapping or None). Calendar repeats are cut off at the end of the other data."""
    events: list[Event] = []
    calendars = []
    for kind, text, mapping in files.values():
        if kind == "calendar":
            calendars.append(text)
        else:
            events += load(kind, text, mapping)
    until = max((e.when for e in events), default=None)
    for text in calendars:
        events += load_calendar(text, until)
    events.sort(key=lambda e: (e.when, e.id))
    return events
