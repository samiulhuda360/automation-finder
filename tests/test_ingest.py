from __future__ import annotations

from datetime import datetime

import pytest

from automation_finder.events import mask, person_key, working_minutes_between
from automation_finder.ingest import (
    detect_kind,
    guess_mapping,
    load_activity,
    load_calendar,
    load_emails,
    load_tickets,
)

EMAILS = """Sender Address,Recipient,Title,Received Time,Location
billing@supplier.example,emma.wilson@acme.example,Invoice INV-123 from Supplier,2026-06-01 09:00,Inbox
emma.wilson@acme.example,billing@supplier.example,RE: Invoice INV-123 from Supplier,2026-06-01 09:30,Sent Items
james.carter@acme.example,emma.wilson@acme.example,Lunch?,2026-06-01 12:00,Inbox
"""


def test_mapping_is_guessed_from_other_header_names() -> None:
    headers = EMAILS.splitlines()[0].split(",")
    m = guess_mapping("email", headers)
    assert m == {
        "sender": "Sender Address",
        "recipients": "Recipient",
        "subject": "Title",
        "time": "Received Time",
        "folder": "Location",
    }


def test_email_direction_and_actor() -> None:
    events = load_emails(EMAILS)
    assert [e.direction for e in events] == ["inbound", "outbound", "internal"]
    assert [e.actor for e in events] == ["emma", "emma", "james"]
    assert events[0].refs == ("INV-123",)
    assert events[1].thread == events[0].thread == "invoice inv-123 from supplier"


def test_missing_required_column_is_reported() -> None:
    with pytest.raises(ValueError, match="subject"):
        load_emails("From,To,Date\na@x.example,b@y.example,2026-06-01 09:00\n")


def test_explicit_mapping_overrides_the_guess() -> None:
    text = "who,did,at,app\nTom Baker,start job,2026-06-01 08:00,jobs\n"
    events = load_activity(text, {"user": "who", "action": "did", "time": "at", "system": "app"})
    assert events[0].actor == "tom" and events[0].action == "start job" and events[0].system == "jobs"


def test_tickets_use_assignee_and_keep_the_subject() -> None:
    text = (
        "Ticket ID,Created,Subject,Description,Assignee\n"
        "T1,2026-06-01 10:00,Move my visit,Can't do Tuesday,Claire T\n"
    )
    (e,) = load_tickets(text)
    assert e.actor == "claire" and e.extra["subject"] == "Move my visit" and "Tuesday" in e.text


def test_calendar_repeats_are_expanded_and_attendees_counted() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            "UID:x1",
            "DTSTART:20260601T070000",
            "DTEND:20260601T073000",
            "SUMMARY:Toolbox meeting",
            "ORGANIZER;CN=James:mailto:james.carter@acme.example",
            "ATTENDEE;CN=Tom:mailto:tom.baker@acme.example",
            "RRULE:FREQ=WEEKLY;COUNT=3",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:x2",
            "DTSTART:20260602T090000",
            "DTEND:20260602T110000",
            "SUMMARY:Report",
            "ORGANIZER:mailto:sarah.mitchell@acme.example",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    events = load_calendar(ics)
    assert len(events) == 4
    assert {e.id for e in events if e.text == "Toolbox meeting"} == {
        "calendar:x1#20260601T070000",
        "calendar:x1#20260608T070000",
        "calendar:x1#20260615T070000",
    }
    report = next(e for e in events if e.text == "Report")
    assert report.id == "calendar:x2" and report.duration_min == 120 and report.attendees == 0


def test_detect_kind() -> None:
    assert detect_kind("x.ics", "BEGIN:VCALENDAR\n") == "calendar"
    assert detect_kind("a.csv", EMAILS) == "email"
    assert detect_kind("b.csv", "User,Action,Timestamp,System\n") == "activity"
    assert detect_kind("c.csv", "Ticket ID,Created,Subject,Assignee\n") == "ticket"


def test_mask_hides_the_parts_that_change() -> None:
    a = mask("FW: PO request PO-2041 ($1,240) for 12 Jun")
    b = mask("PO request PO-2077 ($310) for 3 July")
    assert a == b == "po request <ref> ( <amount> ) for <date>"
    assert mask("Catch-up Sarah / James", frozenset({"sarah", "james"})) == "catch-up <person> / <person>"


def test_person_key() -> None:
    assert person_key("Emma Wilson") == person_key("emma.wilson@acme.example") == person_key("Emma <emma@x.example>")


def test_working_minutes_skip_nights_and_weekends() -> None:
    friday = datetime(2026, 6, 5, 17, 30)
    monday = datetime(2026, 6, 8, 7, 20)
    assert working_minutes_between(friday, monday) == 50  # 30 on Friday + 20 on Monday
