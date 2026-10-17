"""Invented sample data: twelve weeks of activity at "Acme Plumbing", a 12-person plumbing business.

The generator writes the four kinds of export the tool reads (email metadata, helpdesk tickets, a calendar and an
activity log) plus a separate `labels.json` that says which rows belong to which planted pattern and how many
minutes each planted task really took. The labels are only used by the evaluation, never by the analysis.

Planted, automatable patterns:
  P1  supplier invoices re-typed from email into the accounts system      (copy between systems)
  P2  weekly timesheet chasing on Friday afternoons                         (periodic, weekly)
  P3  website quote requests copied into the CRM                            (copy between systems)
  P4  "please reschedule my visit" tickets, worded many different ways     (near-duplicate requests)
  P5  the monthly KPI report built by hand on the first working day         (periodic, monthly)
  P6  purchase-order requests forwarded to the owner for approval           (hand-off with approval)
  P7  next-day appointment reminder calls every afternoon                   (periodic, daily)
  P8  finished jobs invoiced by the accounts person                         (hand-off between people)

Distractors that recur but are not automatable work (a good finder must leave them out):
  D1  the weekly team toolbox meeting      D2  a supplier's weekly specials newsletter
  D3  the accounts system's daily summary  D4  the owner's weekly one-to-one with the office manager

Everything else is noise: customer enquiries and replies, internal chatter, one-off tickets, site visits, job
updates and bookkeeping done at irregular times.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

START = date(2026, 6, 1)  # a Monday
WEEKS = 12
DOMAIN = "acmeplumbing.example"


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    role: str

    @property
    def email(self) -> str:
        first, last = self.name.lower().split()
        return f"{first}.{last}@{DOMAIN}"


STAFF = [
    Person("sarah", "Sarah Mitchell", "owner"),
    Person("james", "James Carter", "office manager"),
    Person("emma", "Emma Wilson", "accounts"),
    Person("claire", "Claire Thompson", "customer service"),
    Person("tom", "Tom Baker", "plumber"),
    Person("jack", "Jack Harris", "plumber"),
    Person("mark", "Mark Evans", "plumber"),
    Person("olivia", "Olivia Brown", "plumber"),
    Person("hannah", "Hannah Clarke", "plumber"),
    Person("ben", "Ben Walker", "plumber"),
    Person("lucy", "Lucy Turner", "plumber"),
    Person("ryan", "Ryan Hughes", "plumber"),
]
BY_KEY = {p.key: p for p in STAFF}
PLUMBERS = [p for p in STAFF if p.role == "plumber"]

PATTERNS = {
    "P1": "Supplier invoices re-typed from email into the accounts system",
    "P2": "Weekly timesheet chasing",
    "P3": "Website quote requests copied into the CRM",
    "P4": "Reschedule requests handled by hand",
    "P5": "Monthly KPI report built by hand",
    "P6": "Purchase orders forwarded for approval",
    "P7": "Daily appointment reminder calls",
    "P8": "Finished jobs invoiced by hand",
}
DISTRACTORS = {
    "D1": "Weekly toolbox meeting",
    "D2": "Supplier specials newsletter",
    "D3": "Accounts system daily summary",
    "D4": "Weekly one-to-one meeting",
}
# What a sensible automation looks like for each planted pattern; the proposal rubric scores against this.
EXPECTED = {
    "P1": {
        "trigger": "email",
        "systems": ["email", "accounts"],
        "approval": True,
        "risk": "medium",
        "keywords": ["invoice", "bill", "extract"],
    },
    "P2": {
        "trigger": "schedule",
        "systems": ["payroll", "email"],
        "approval": False,
        "risk": "low",
        "keywords": ["timesheet", "remind"],
    },
    "P3": {
        "trigger": "email",
        "systems": ["email", "crm"],
        "approval": False,
        "risk": "low",
        "keywords": ["lead", "quote"],
    },
    "P4": {
        "trigger": "ticket",
        "systems": ["helpdesk", "jobs"],
        "approval": True,
        "risk": "medium",
        "keywords": ["reschedul", "booking"],
    },
    "P5": {
        "trigger": "schedule",
        "systems": ["jobs", "spreadsheet"],
        "approval": False,
        "risk": "low",
        "keywords": ["report", "export"],
    },
    "P6": {
        "trigger": "email",
        "systems": ["email", "accounts"],
        "approval": True,
        "risk": "high",
        "keywords": ["purchase order", "approv"],
    },
    "P7": {
        "trigger": "schedule",
        "systems": ["phone", "jobs"],
        "approval": False,
        "risk": "low",
        "keywords": ["reminder", "booking"],
    },
    "P8": {
        "trigger": "app_event",
        "systems": ["jobs", "accounts"],
        "approval": True,
        "risk": "medium",
        "keywords": ["invoice", "job"],
    },
}

SUPPLIERS = [
    ("accounts@plumbingworld.example", "Invoice INV-{n} from Plumbing World"),
    ("billing@pipelinesupplies.example", "Pipeline Supplies tax invoice INV-{n}"),
    ("invoices@hotwaterhub.example", "Your Hot Water Hub invoice INV-{n} is ready"),
    ("ar@drainpro.example", "DrainPro invoice INV-{n} - payment due in 20 days"),
]
SERVICES = [
    "Hot water cylinder replacement",
    "Blocked drain",
    "Leaking tap",
    "Bathroom renovation plumbing",
    "Toilet replacement",
    "Gas hob installation",
    "Burst pipe repair",
    "Heat pump water heater",
    "Outdoor tap install",
    "Kitchen sink install",
    "Water filter install",
    "Shower mixer replacement",
]
SUBURBS = [
    "Ponsonby",
    "Grey Lynn",
    "Mt Eden",
    "Remuera",
    "Epsom",
    "Onehunga",
    "Takapuna",
    "Devonport",
    "Henderson",
    "Howick",
    "Parnell",
    "Kingsland",
    "Avondale",
    "Glen Eden",
    "Mangere Bridge",
    "Northcote",
]
STREETS = ["Rata St", "Kauri Rd", "Queen St", "Beach Rd", "Hill Ave", "Park Tce", "Station Rd", "Church St"]
FIRST_NAMES = [
    "Olivia",
    "Liam",
    "Grace",
    "Noah",
    "Chloe",
    "Henry",
    "Amelia",
    "Oscar",
    "Isla",
    "Leo",
    "Ruby",
    "George",
    "Zoe",
    "Arthur",
    "Ella",
    "Harry",
    "Mia",
    "Charlie",
    "Lily",
    "Max",
    "Sophie",
    "Daniel",
    "Kate",
    "Luke",
    "Anna",
    "Peter",
]
LAST_NAMES = [
    "Grant",
    "Foster",
    "Bennett",
    "Ellis",
    "Ward",
    "Price",
    "Cole",
    "Reid",
    "Morgan",
    "Hayes",
    "Shaw",
    "Webb",
    "Palmer",
    "Lane",
    "Fraser",
    "Knight",
    "Stone",
    "Dean",
    "Barker",
    "Holland",
]
CUSTOMERS = [f"{f} {last}" for f in FIRST_NAMES for last in LAST_NAMES]
RESCHEDULE_SUBJECTS = [
    "Need to reschedule my appointment",
    "Can we move Thursday's booking?",
    "Change of booking time please",
    "Reschedule plumber visit to next week",
    "Can the plumber come another day?",
    "Won't be home on Tuesday - new time?",
    "Request to change appointment date",
    "Booking clash - please rebook",
    "Move my plumbing appointment",
    "Can we push the visit back?",
    "Need a different day for the job",
    "Please rebook my hot water visit",
]
RESCHEDULE_BODIES = [
    "Something came up at work, could you send someone on a different day?",
    "Sorry, I won't be home then. Is later in the week possible?",
    "We are away that day. Could we rebook for the week after?",
    "The tenant can't give access that morning, please pick another slot.",
    "Could the visit be moved to the afternoon or another day?",
    "Kids are sick so tomorrow doesn't suit. Any other time this week?",
    "My flight changed, please move the booking to next Monday if possible.",
    "Can you come Friday instead? The original time no longer works.",
]
TICKET_TOPICS = [
    ("Leaking under kitchen sink again", "The leak you fixed last month is back, water under the cabinet."),
    ("Warranty claim on hot water cylinder", "The cylinder you installed in March has stopped heating."),
    ("Question about invoice charges", "Why was there a call-out fee on top of the hourly rate?"),
    ("Plumber left gate open", "Our dog nearly got out, please remind the team to close gates."),
    ("Great job by Tom", "Just wanted to say thanks, very tidy work on the bathroom."),
    ("Low water pressure after repair", "Since the pipe repair the shower pressure is much weaker."),
    ("Need a copy of compliance certificate", "The council asked for the code compliance paperwork."),
    ("Toilet keeps running", "The new toilet cistern doesn't stop filling."),
    ("Smell of gas near hob", "There is a faint smell near the new gas hob, can someone check?"),
    ("Damage to driveway", "The van left an oil stain on our new driveway."),
    ("Request for itemised invoice", "Our insurer needs the parts and labour listed separately."),
    ("Noise from pipes at night", "Banging noise in the walls when the tap is turned off."),
    ("Price match request", "Another firm quoted less for the same cylinder, can you match it?"),
    ("Can you install a dishwasher?", "Do you also connect dishwashers or only the plumbing?"),
    ("Water heater thermostat setting", "What temperature should the cylinder be set to?"),
    ("Missing part on outdoor tap", "The handle on the outdoor tap came off after a week."),
    ("Booking confirmation not received", "I booked online but didn't get an email confirmation."),
    ("Rates for emergency call-outs", "What do you charge for a weekend emergency?"),
    ("Drain still slow", "The blocked drain was cleared but it's slow again."),
    ("Feedback on quote", "The quote seems high for a tap replacement, can you explain?"),
    ("Insurance job paperwork", "Our insurance company needs a report for the burst pipe."),
    ("Old cylinder removal", "Will you take the old cylinder away or do we arrange it?"),
    ("Heat pump noise", "The heat pump water heater hums loudly at night."),
    ("Tenant reporting leak", "My tenant says there is a drip in the laundry."),
]
ENQUIRY_SUBJECTS = [
    "Do you service {suburb}?",
    "Quick question about a {service_l}",
    "Availability next week",
    "Is Saturday work possible?",
    "Following up on my quote",
    "Photos of the problem attached",
    "Recommendation from a neighbour",
    "Do you do commercial work?",
    "Parking at our address",
    "Access instructions for {street}",
    "Strange noise from the hot water cupboard",
    "Do you offer a pensioner discount?",
    "Are you able to fit a bidet seat",
    "Rental property - landlord approval needed?",
    "Need a plumber for a new build in {suburb}",
    "Water coming through the ceiling!",
    "Who do I pay the deposit to?",
    "Is the call-out fee included",
    "Can I supply my own tapware",
    "How long does a cylinder swap take",
    "Thanks for the quick visit",
    "Earliest you could come to {street}?",
    "Moving house - transfer of gas account",
    "Warranty on parts you fitted",
    "Do you clean gutters and downpipes",
    "Insurance assessor wants a quote",
    "Neighbour's tree roots in our drain",
    "Upgrade to a mains pressure system?",
    "Smell from the laundry drain",
    "Retirement village job - access via office",
    "Body corporate approval for {street} works",
    "Can someone check our backflow preventer",
    "Do you install rainwater tanks",
    "Booking for my elderly mum in {suburb}",
    "Brown water from the cold tap",
    "Garden irrigation leak",
    "Need an invoice re-sent",
    "Spa pool plumbing question",
    "Swapping a bath for a shower",
    "Tap washer replacement cost",
    "Dishwasher connection in {suburb}",
    "Kitchen renovation timeline - when to book you",
    "Our toilet rocks on the floor",
    "Heat pump water heater rebates",
    "Feedback on the job at {street}",
    "Can you work around our dog?",
    "Will you be using the driveway?",
]
INTERNAL_SUBJECTS = [
    "Van {n} service booked",
    "Ladder missing from van {n}",
    "Leave request for {day}",
    "Site access code for {suburb} job",
    "New stock arrived",
    "Who has the drain camera?",
    "Fuel card PIN",
    "Safety glasses order",
    "Customer in {suburb} wants an earlier time",
    "Running late - traffic on the motorway",
    "Lunch order Friday?",
    "Christmas party ideas",
    "Parking ticket on {street}",
    "Updated price list",
    "Drain jetter needs repair",
    "Can someone cover my afternoon jobs",
    "Training day for gas certification",
    "Spare keys for the yard",
    "Supplier rep visiting {day}",
    "Uniform sizes",
    "Phone charger in van {n}",
    "Water damage photos from {suburb}",
]
SUPPLIER_QUERIES = [
    "Statement for June",
    "Credit note for returned fittings",
    "Delivery address change",
    "Account limit review",
    "Query on freight charge",
    "Missing items on delivery {n}",
]
MATERIALS = [
    "3x 25mm PEX coils",
    "hot water cylinder 180L",
    "2x mixer valves",
    "copper fittings kit",
    "drain camera hire",
    "pressure reducing valve",
    "gas hob connection kit",
    "50m 20mm PE pipe",
    "toilet suite",
    "heat pump water heater",
]


@dataclass
class Builder:
    rng: random.Random
    emails: list[dict[str, str]] = field(default_factory=list)
    tickets: list[dict[str, str]] = field(default_factory=list)
    calendar: list[dict[str, object]] = field(default_factory=list)
    activity: list[dict[str, str]] = field(default_factory=list)
    labels: dict[str, dict[str, list]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def next(self, kind: str, start: int) -> int:
        self.counters[kind] = self.counters.get(kind, start) + 1
        return self.counters[kind]

    def label(self, pid: str, event_id: str, minutes: float | None = None) -> None:
        entry = self.labels.setdefault(pid, {"events": [], "minutes": []})
        entry["events"].append(event_id)
        if minutes is not None:
            entry["minutes"].append(round(minutes, 2))

    def minutes(self, mean: float, spread: float = 0.2) -> float:
        return max(1.0, self.rng.gauss(mean, mean * spread))

    def email(self, when: datetime, sender: str, to: str, subject: str, folder: str = "Inbox") -> str:
        mid = f"M{self.next('email', 10000):05d}"
        self.emails.append(
            {
                "Message ID": mid,
                "From": sender,
                "To": to,
                "Subject": subject,
                "Date": when.strftime("%Y-%m-%d %H:%M"),
                "Folder": folder,
            }
        )
        return f"email:{mid}"

    def act(self, when: datetime, who: Person, action: str, system: str, record: str = "", details: str = "") -> str:
        aid = f"A{self.next('activity', 10000):05d}"
        self.activity.append(
            {
                "Event ID": aid,
                "User": who.name,
                "Action": action,
                "System": system,
                "Timestamp": when.strftime("%Y-%m-%d %H:%M"),
                "Record": record,
                "Details": details,
            }
        )
        return f"activity:{aid}"

    def ticket(self, when: datetime, requester: str, subject: str, body: str, assignee: Person) -> str:
        tid = f"T{self.next('ticket', 4000)}"
        closed = when + timedelta(hours=self.rng.uniform(1, 30))
        self.tickets.append(
            {
                "Ticket ID": tid,
                "Created": when.strftime("%Y-%m-%d %H:%M"),
                "Requester": requester,
                "Subject": subject,
                "Description": body,
                "Assignee": assignee.name,
                "Status": "Closed",
                "Closed": closed.strftime("%Y-%m-%d %H:%M"),
            }
        )
        return f"ticket:{tid}"

    def event(
        self,
        start: datetime,
        minutes: int,
        organizer: Person,
        summary: str,
        attendees: list[Person] | None = None,
        weekly_count: int = 0,
    ) -> str:
        uid = f"cal-{self.next('cal', 1000)}@{DOMAIN}"
        self.calendar.append(
            {
                "uid": uid,
                "start": start,
                "end": start + timedelta(minutes=minutes),
                "organizer": organizer,
                "summary": summary,
                "attendees": attendees or [],
                "weekly_count": weekly_count,
            }
        )
        return uid


def work_time(rng: random.Random, day: date, start_hour: float = 7.5, end_hour: float = 17.0) -> datetime:
    minutes = rng.uniform(start_hour * 60, end_hour * 60)
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=round(minutes))


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def add_work_minutes(t: datetime, minutes: float) -> datetime:
    """Adds minutes, carrying anything past 17:30 over to 07:30 on the next working day."""
    out = t + timedelta(minutes=minutes)
    while out.hour * 60 + out.minute > 17 * 60 + 30 or out.weekday() >= 5:
        overflow = (out - out.replace(hour=17, minute=30)) if out.weekday() < 5 else timedelta(0)
        nxt = out.date() + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        out = at(nxt, 7, 30) + max(overflow, timedelta(0))
    return out


def business_days() -> list[date]:
    days = [START + timedelta(days=i) for i in range(WEEKS * 7)]
    return [d for d in days if d.weekday() < 5]


@dataclass(frozen=True)
class Difficulty:
    """Knobs for a harder dataset: rarer patterns, slower follow-ups and less regular timing."""

    on_time: float = 0.85  # share of copies typed in within about half an hour
    volume: float = 1.0  # multiplier on how often the copy, request and approval patterns occur
    jitter_hours: float = 0.0  # spread added to the start time of the daily and weekly routines


NORMAL = Difficulty()
HARD = Difficulty(on_time=0.6, volume=0.5, jitter_hours=2.0)


def _count(rng: random.Random, choices: list[int], volume: float) -> int:
    n = rng.choice(choices)
    return sum(rng.random() < volume for _ in range(n)) if volume < 1 else n


def _jitter(rng: random.Random, t: datetime, hours: float) -> datetime:
    return t + timedelta(minutes=round(rng.uniform(-hours, hours) * 30)) if hours else t


def generate(seed: int = 0, level: Difficulty = NORMAL) -> Builder:
    rng = random.Random(seed)
    b = Builder(rng)
    days = business_days()
    sarah, james, emma, claire = (BY_KEY[k] for k in ("sarah", "james", "emma", "claire"))

    # D1 weekly toolbox meeting (one recurring calendar entry) and D4 weekly one-to-one.
    b.labels["D1"] = {"events": [], "minutes": []}
    b.labels["D4"] = {"events": [], "minutes": []}
    b.event(at(START, 7, 0), 30, james, "Toolbox meeting", [*PLUMBERS], weekly_count=WEEKS)
    b.event(at(START + timedelta(days=3), 15, 0), 45, sarah, "Catch-up Sarah / James", [james], weekly_count=WEEKS)

    first_days: dict[tuple[int, int], date] = {}
    for d in days:
        first_days.setdefault((d.year, d.month), d)

    for d in days:
        # ---------------------------------------------------------------- P8: jobs done, then invoiced by Emma
        for plumber in PLUMBERS:
            for _ in range(rng.choice([1, 1, 2, 2, 2, 3])):
                ref = f"J-{b.next('job', 5000)}"
                start = work_time(rng, d, 7.5, 14.5)
                service = rng.choice(SERVICES)
                ids = [b.act(start, plumber, "start job", "jobs", ref, f"{service}, {rng.choice(SUBURBS)}")]
                if rng.random() < 0.3:
                    b.act(
                        start + timedelta(minutes=rng.randint(20, 50)),
                        plumber,
                        "log materials",
                        "jobs",
                        ref,
                        rng.choice(MATERIALS),
                    )
                done = start + timedelta(minutes=rng.randint(50, 200))
                ids.append(b.act(done, plumber, "complete job", "jobs", ref, "Job sheet signed by customer"))
                for i in ids:
                    b.label("P8", i)
                if rng.random() < 0.92:
                    inv_at = add_work_minutes(done, rng.uniform(30, 600))
                    b.label(
                        "P8",
                        b.act(inv_at, emma, "create invoice", "accounts", ref, f"Invoice for {service}"),
                        b.minutes(6),
                    )

        # ---------------------------------------------------------------- P7: reminder calls each afternoon
        call_at = _jitter(rng, at(d, 15, rng.randint(40, 59)), level.jitter_hours)
        for _ in range(rng.randint(5, 9)):
            mins = b.minutes(3, 0.3)
            b.label(
                "P7",
                b.act(call_at, claire, "reminder call", "phone", "", "Called customer about tomorrow's booking"),
                mins,
            )
            call_at += timedelta(minutes=round(mins) + rng.randint(0, 3))

        # ---------------------------------------------------------------- P1: supplier invoices
        for _ in range(_count(rng, [0, 1, 1, 2, 2, 3], level.volume)):
            sender, template = rng.choice(SUPPLIERS)
            number = rng.randint(10000, 99999)
            got = work_time(rng, d, 7.0, 16.5)
            e = b.email(got, sender, emma.email, template.format(n=number))
            b.label("P1", e)
            if rng.random() < level.on_time:
                entered = add_work_minutes(got, rng.uniform(4, 35))
            else:
                entered = add_work_minutes(got, rng.uniform(70, 300))
            b.label(
                "P1",
                b.act(
                    entered,
                    emma,
                    "enter supplier bill",
                    "accounts",
                    f"INV-{number}",
                    sender.split("@")[1].split(".")[0],
                ),
                b.minutes(6),
            )

        # ---------------------------------------------------------------- P3: website quote requests
        for _ in range(_count(rng, [1, 1, 2, 2, 2, 3], level.volume)):
            service, suburb = rng.choice(SERVICES), rng.choice(SUBURBS)
            got = work_time(rng, d, 7.0, 17.0)
            b.label(
                "P3",
                b.email(got, "noreply@webforms.example", claire.email, f"New quote request: {service} - {suburb}"),
            )
            if rng.random() < min(1.0, level.on_time + 0.05):
                lead = f"L-{b.next('lead', 300)}"
                b.label(
                    "P3",
                    b.act(
                        add_work_minutes(got, rng.uniform(3, 30)),
                        claire,
                        "create lead",
                        "crm",
                        lead,
                        f"{service}, {suburb}",
                    ),
                    b.minutes(5),
                )

        # ---------------------------------------------------------------- P4: reschedule tickets (~6 a week)
        for _ in range(_count(rng, [0, 1, 1, 1, 2], level.volume)):
            customer = rng.choice(CUSTOMERS)
            got = work_time(rng, d, 7.0, 17.0)
            tid = b.ticket(
                got,
                f"{customer.lower().replace(' ', '.')}@mailbox.example",
                rng.choice(RESCHEDULE_SUBJECTS),
                rng.choice(RESCHEDULE_BODIES),
                claire,
            )
            b.label("P4", tid)
            if rng.random() < min(1.0, level.on_time + 0.05):
                b.label(
                    "P4",
                    b.act(
                        add_work_minutes(got, rng.uniform(5, 40)),
                        claire,
                        "reschedule booking",
                        "jobs",
                        "",
                        f"Moved booking for {customer}",
                    ),
                    b.minutes(7),
                )

        # ---------------------------------------------------------------- D3: accounts system daily summary
        b.label(
            "D3",
            b.email(
                at(d, 6, 0),
                "notify@ledgerly.example",
                emma.email,
                f"Your daily business snapshot - {d.strftime('%d %b')}",
            ),
        )

        # ---------------------------------------------------------------- noise
        for _ in range(rng.randint(1, 3)):  # customer enquiries, some answered
            customer = rng.choice(CUSTOMERS)
            addr = f"{customer.lower().replace(' ', '.')}@inbox.example"
            subject = rng.choice(ENQUIRY_SUBJECTS).format(
                suburb=rng.choice(SUBURBS), service_l=rng.choice(SERVICES).lower(), street=rng.choice(STREETS)
            )
            got = work_time(rng, d)
            b.email(got, addr, claire.email, subject)
            if rng.random() < 0.6:
                b.email(
                    got + timedelta(minutes=rng.randint(10, 240)), claire.email, addr, f"RE: {subject}", "Sent Items"
                )
        for _ in range(rng.randint(2, 6)):  # internal chatter
            a, z = rng.sample(STAFF, 2)
            subject = rng.choice(INTERNAL_SUBJECTS).format(
                n=rng.randint(1, 6),
                day=(d + timedelta(days=rng.randint(3, 30))).strftime("%d %B"),
                suburb=rng.choice(SUBURBS),
                street=rng.choice(STREETS),
            )
            b.email(work_time(rng, d, 6.5, 19.0), a.email, z.email, subject)
        if rng.random() < 0.35:
            sender, _ = rng.choice(SUPPLIERS)
            b.email(
                work_time(rng, d),
                emma.email,
                sender,
                rng.choice(SUPPLIER_QUERIES).format(n=rng.randint(100, 999)),
                "Sent Items",
            )
        if rng.random() < 0.45:
            title, body = rng.choice(TICKET_TOPICS)
            b.ticket(
                work_time(rng, d),
                f"{rng.choice(CUSTOMERS).lower().replace(' ', '.')}@mailbox.example",
                title,
                body,
                rng.choice([claire, james, emma]),
            )
        for _ in range(rng.randint(2, 5)):
            b.act(work_time(rng, d), claire, "book job", "jobs", "", f"{rng.choice(SERVICES)}, {rng.choice(SUBURBS)}")
        for _ in range(rng.randint(0, 3)):
            b.act(work_time(rng, d), claire, "update contact", "crm", "", rng.choice(CUSTOMERS))
        if rng.random() < 0.6:
            b.act(work_time(rng, d, 8, 17), emma, "reconcile bank", "accounts")
        if rng.random() < 0.3:
            b.act(work_time(rng, d, 8, 17), emma, "record payment", "accounts", "", rng.choice(CUSTOMERS))
        if rng.random() < 0.25:
            b.act(work_time(rng, d, 8, 17), james, "update roster", "spreadsheet")
        if rng.random() < 0.3:
            plumber = rng.choice(PLUMBERS)
            b.event(
                work_time(rng, d, 8, 16),
                60,
                plumber,
                f"Quote visit - {rng.randint(1, 140)} {rng.choice(STREETS)}, {rng.choice(SUBURBS)}",
            )

        # ---------------------------------------------------------------- weekly items
        if d.weekday() == 1:  # D2 supplier newsletter on Tuesdays
            for person in (sarah, james, emma):
                b.label(
                    "D2",
                    b.email(
                        at(d, 6, 30),
                        "news@plumbingworld.example",
                        person.email,
                        f"Plumbing World specials - week of {d.strftime('%d %b')}",
                    ),
                )
        if d.weekday() == 4:  # P2 timesheet chasing on Fridays
            check = _jitter(rng, at(d, 13, rng.randint(25, 45)), level.jitter_hours)
            b.label("P2", b.act(check, james, "check timesheet status", "payroll"), b.minutes(10))
            t = check + timedelta(minutes=rng.randint(10, 20))
            subjects = [
                "Timesheet reminder - week ending {d}",
                "Reminder: timesheet due today",
                "Please submit your timesheet for w/e {d}",
            ]
            for plumber in rng.sample(PLUMBERS, rng.randint(3, 6)):
                mins = b.minutes(4)
                b.label(
                    "P2",
                    b.email(
                        t,
                        james.email,
                        plumber.email,
                        rng.choice(subjects).format(d=d.strftime("%d %b")),
                        "Sent Items",
                    ),
                    mins,
                )
                t += timedelta(minutes=round(mins) + rng.randint(0, 4))

        # ---------------------------------------------------------------- P6: purchase-order approvals
        if rng.random() < 0.6 * level.volume:
            plumber = rng.choice(PLUMBERS)
            po = f"PO-{b.next('po', 2040)}"
            amount = rng.randint(400, 4800)
            material = rng.choice(MATERIALS)
            t0 = work_time(rng, d, 7.0, 13.0)
            subject = f"PO request {po}: {material}"
            b.label("P6", b.email(t0, plumber.email, james.email, subject), b.minutes(4))
            t1 = add_work_minutes(t0, rng.uniform(10, 90))
            b.label(
                "P6",
                b.email(t1, james.email, sarah.email, f"FW: {subject} - approval needed (${amount})"),
                b.minutes(3),
            )
            t2 = add_work_minutes(t1, rng.uniform(20, 240))
            approved = rng.random() < 0.9
            b.label(
                "P6",
                b.email(
                    t2, sarah.email, james.email, f"RE: FW: {subject} - {'approved' if approved else 'declined'}"
                ),
                b.minutes(2),
            )
            if approved:
                b.label(
                    "P6",
                    b.act(
                        add_work_minutes(t2, rng.uniform(10, 60)),
                        james,
                        "create purchase order",
                        "accounts",
                        po,
                        material,
                    ),
                    b.minutes(5),
                )

    # ---------------------------------------------------------------- P5: monthly report on the first working day
    for d in first_days.values():
        b.label("P5", b.event(at(d, 9, 0), 120, sarah, "Monthly KPI report"), b.minutes(120, 0.1))
        b.label("P5", b.act(at(d, 9, rng.randint(2, 10)), sarah, "export job report", "jobs"))
        b.label("P5", b.act(at(d, 9, rng.randint(25, 40)), sarah, "update KPI spreadsheet", "spreadsheet"))
        b.label(
            "P5",
            b.email(
                at(d, 10, rng.randint(45, 58)),
                sarah.email,
                james.email,
                f"Monthly KPI report - {(d - timedelta(days=3)).strftime('%B %Y')}",
                "Sent Items",
            ),
        )
    return b


# --------------------------------------------------------------------------------------------- writers
def _ics_time(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%M%S")


def write_ics(path: Path, entries: list[dict[str, object]], labels: dict[str, dict[str, list]]) -> None:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Acme Plumbing//Shared calendar//EN"]
    for e in entries:
        start, end = e["start"], e["end"]
        organizer = e["organizer"]
        assert isinstance(start, datetime) and isinstance(end, datetime) and isinstance(organizer, Person)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{e['uid']}",
            f"DTSTART:{_ics_time(start)}",
            f"DTEND:{_ics_time(end)}",
            f"SUMMARY:{e['summary']}",
            f"ORGANIZER;CN={organizer.name}:mailto:{organizer.email}",
        ]
        for person in e["attendees"]:  # type: ignore[attr-defined]
            lines.append(f"ATTENDEE;CN={person.name}:mailto:{person.email}")
        if e["weekly_count"]:
            lines.append(f"RRULE:FREQ=WEEKLY;COUNT={e['weekly_count']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    # Recurring entries become one event per occurrence when loaded; label each occurrence.
    for e in entries:
        if e["weekly_count"]:
            pid = "D1" if e["summary"] == "Toolbox meeting" else "D4"
            start = e["start"]
            assert isinstance(start, datetime)
            for i in range(int(e["weekly_count"])):  # type: ignore[call-overload]
                labels[pid]["events"].append(f"calendar:{e['uid']}#{_ics_time(start + timedelta(weeks=i))}")
    # Single events get their plain uid; rewrite plain labels to the loader's event ids.
    for entry in labels.values():
        entry["events"] = [
            x if x.startswith(("email:", "activity:", "ticket:", "calendar:")) else f"calendar:{x}"
            for x in entry["events"]
        ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r.get("Date") or r.get("Created") or r.get("Timestamp", "")))


def write_dataset(folder: Path, seed: int = 0, level: Difficulty = NORMAL) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    b = generate(seed, level)
    paths = {
        "email": folder / "emails.csv",
        "ticket": folder / "tickets.csv",
        "calendar": folder / "calendar.ics",
        "activity": folder / "activity.csv",
    }
    _write_csv(paths["email"], b.emails)
    _write_csv(paths["ticket"], b.tickets)
    _write_csv(paths["activity"], b.activity)
    write_ics(paths["calendar"], b.calendar, b.labels)
    months = WEEKS * 7 / 30.44
    planted = []
    for pid, name in PATTERNS.items():
        entry = b.labels[pid]
        planted.append(
            {
                "id": pid,
                "name": name,
                "expected": EXPECTED[pid],
                "events": entry["events"],
                "true_minutes_total": round(sum(entry["minutes"]), 1),
                "true_hours_per_month": round(sum(entry["minutes"]) / 60 / months, 2),
            }
        )
    distractors = [{"id": did, "name": name, "events": b.labels[did]["events"]} for did, name in DISTRACTORS.items()]
    labels = {
        "seed": seed,
        "hard": level == HARD,
        "start": START.isoformat(),
        "weeks": WEEKS,
        "planted": planted,
        "distractors": distractors,
    }
    (folder / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
    return paths
