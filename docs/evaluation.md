# Evaluation method

## Data

There is no public dataset of a small business's email, ticket, calendar and system logs with labelled automatable
work, so the evaluation uses invented data with known answers. `automation_finder/sample.py` generates twelve weeks
(1 June to 23 August 2026) of activity for **Acme Plumbing**, an invented 12-person business. The data and the
generator are part of this repository (MIT licence); no real person or company appears in it.

Each seed produces about 5,000 records:

| File | Contents |
|---|---|
| `emails.csv` | Message ID, From, To, Subject, Date, Folder (no bodies) |
| `tickets.csv` | Ticket ID, Created, Requester, Subject, Description, Assignee, Status, Closed |
| `calendar.ics` | Shared calendar, including two weekly repeating entries |
| `activity.csv` | Event ID, User, Action, System, Timestamp, Record, Details |
| `labels.json` | Which records belong to which planted pattern, and the minutes each planted task took |

**Planted patterns** (automatable, the finder should report them):

| Id | Pattern | Kind |
|---|---|---|
| P1 | Supplier invoices re-typed from email into the accounts system | copy between systems |
| P2 | Timesheet chasing every Friday afternoon | weekly routine |
| P3 | Website quote requests copied into the CRM | copy between systems |
| P4 | Reschedule requests, worded in 12 different ways | repeated request (+ copy into jobs) |
| P5 | Monthly KPI report built by hand on the first working day | monthly routine |
| P6 | Purchase-order requests forwarded for the owner's approval | approval chain |
| P7 | Next-day reminder calls every afternoon | daily routine |
| P8 | Finished jobs invoiced by the accounts person | hand-off between people |

**Distractors** (they recur, but are not automatable work, so reporting them is a mistake): the weekly toolbox
meeting, a supplier's weekly newsletter, the accounts system's daily summary email, and the owner's weekly
one-to-one.

**Noise:** customer enquiries in about 50 different wordings (60% get replies), internal chatter, one-off tickets,
quote visits in the calendar, job start and completion records, and bookkeeping done at irregular times.

**True hours:** each planted task draws its own duration (for example about 6 minutes per supplier bill, 4 per
timesheet reminder, 120 for the monthly report). The true hours per month for a pattern are the sum of those
minutes divided by the number of months. The finder never sees them.

**Harder variant** (`--hard`): the copy, request and approval patterns happen half as often, only 60% of copies are
typed in within about half an hour, and the daily and weekly routines start up to an hour earlier or later.

## Scoring

For every candidate the finder reports (an opportunity) we count which labelled pattern its records belong to.

- A candidate **hits** a planted pattern when at least 50% of its records belong to it, and **finds** it when it
  also covers at least 25% of that pattern's records.
- **Pattern recall** = planted patterns found / 8.
- **Precision** = candidates that found a planted pattern / all candidates. Each planted pattern can be claimed
  once (by the candidate with the highest coverage); a second fragment, a distractor or noise counts as wrong.
- **Top-5 precision** = the same, among the five highest-ranked candidates (what the owner reads first).
- **Event recall** = the share of planted records captured by the claiming candidates, averaged over the 8 patterns
  (0 for a missed one).
- **Hours error** = mean absolute percentage error between the claiming candidate's hours per month (with the
  default time model) and the planted truth.
- **Distractors reported** = candidates made mostly of distractor records.

The same scoring is applied to two baselines over the same events:

- **Keyword counts:** the 10 most frequent words (after masking and removing common words); each word's records are
  one candidate, at 5 minutes per record.
- **Exact repeats:** the 10 most frequent identical masked subjects or system actions, at 5 minutes per record.

Similarity thresholds were tuned on seed 0 (TF-IDF 0.70, embeddings 0.20 cosine distance). Every reported number is
the mean over seeds 1-5, which were not used for tuning.

## Proposal rubric

For each planted pattern the labels hold an expected automation: the trigger type, the systems involved, whether a
person must approve, the risk level and two or three key words the steps should contain. Each proposal for a found
pattern scores five checks, each from 0 to 1:

| Check | Score |
|---|---|
| Trigger | 1 if the trigger type matches |
| Systems | share of the expected systems named |
| Approval | 1 if "needs approval" matches |
| Risk | 1 for the same level, 0.5 for one level apart |
| Key steps | share of the key words present in the title, trigger, steps and AI help |

Three writers are compared on the same 40 opportunities (8 patterns x 5 seeds): the rule-based writer, Gemini's raw
answer, and Gemini's answer after the safety rules (risk never lower than the rules say; medium or high risk always
keeps a person's approval). The model sees only masked facts, never raw records. Its answers are stored in
`eval-cache/llm/` and replay offline. When the model gave a single sentence where a list was asked for, the sentence
is read as a one-item list; this happened in all 40 answers and is recorded in `results/proposals.json`.

The rubric reflects the same approval policy as the rule-based writer, so it measures whether the model's proposals
are structurally right, not whether they read better.

## Limits

- The data is generated, so the patterns are cleaner than real life. The harder variant shows how the numbers move
  when patterns are rarer and less regular.
- The time model is a stated assumption per kind of work, not a measurement; the page shows it and lets the owner
  change it.
- The n8n workflows are skeletons: they import and pass structural checks, but connecting them to real systems
  (credentials, API addresses, field mapping) is still a person's job.

## Reproduce

```bash
python -m automation_finder eval --seeds 1-5            # replays the stored embeddings, no key needed
python -m automation_finder eval --seeds 1-5 --hard
python -m automation_finder eval-proposals --seeds 1-5
```

With `AI_API_KEY` set, `--live` fetches embeddings or model answers that are not cached yet.
