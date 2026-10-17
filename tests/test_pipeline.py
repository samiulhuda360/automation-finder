"""End-to-end on the committed Acme Plumbing sample (rules mode, no model, no network)."""

from __future__ import annotations

from automation_finder.baseline import keyword_patterns, repeat_patterns
from automation_finder.evaluate import Candidate, rubric_score, score
from automation_finder.opportunities import TimeModel, assess_risk, build_opportunities, rank
from automation_finder.propose import rules_proposal


def candidates(analysis):
    return [Candidate(o.id, set(o.events), o.hours_per_month) for o in analysis.opportunities]


def test_every_planted_pattern_is_found_and_no_distractor(sample_analysis, sample_labels) -> None:
    s = score(candidates(sample_analysis), sample_labels)
    assert sorted(s.found) == [f"P{i}" for i in range(1, 9)]
    assert s.distractor_hits == 0
    assert s.top5_correct == 5


def test_hours_are_close_to_the_planted_truth(sample_analysis, sample_labels) -> None:
    s = score(candidates(sample_analysis), sample_labels)
    assert s.hours_mape < 0.35


def test_baselines_do_worse(sample_events, sample_labels, sample_analysis) -> None:
    ours = score(candidates(sample_analysis), sample_labels)
    for base in (keyword_patterns(sample_events), repeat_patterns(sample_events)):
        s = score([Candidate(k.keyword, set(k.events), k.hours_per_month) for k in base], sample_labels)
        assert s.recall < ours.recall and s.precision < ours.precision


def test_ids_are_ranked_and_editing_minutes_recomputes_hours(sample_analysis) -> None:
    opps = sample_analysis.opportunities
    assert [o.id for o in opps[:3]] == ["O1", "O2", "O3"]
    first = opps[0]
    rank(opps, {first.id: first.minutes_per_task * 2})
    assert abs(first.hours_per_month - first.occurrences_per_month * first.minutes_per_task / 60) < 0.01
    rank(opps, {first.id: first.default_minutes_per_task})


def test_time_model_changes_the_estimate(sample_analysis) -> None:
    a = sample_analysis
    cheap = build_opportunities(
        a.patterns, a.events, a.key_labels, TimeModel(copy=1, request=1, handoff_step=1, routine=1)
    )
    assert sum(o.hours_per_month for o in cheap) < sum(o.hours_per_month for o in a.opportunities)


def test_risk_rules() -> None:
    assert assess_risk([], approval=True)[0] == "high"
    assert assess_risk([("accounts", "create invoice")], approval=False)[0] == "medium"
    assert assess_risk([("jobs", "reschedule booking")], approval=False)[0] == "medium"
    assert assess_risk([("crm", "create lead")], approval=False)[0] == "low"
    assert assess_risk([("spreadsheet", "update kpi spreadsheet")], approval=False)[0] == "low"


def test_rules_proposals_score_well_on_the_rubric(sample_analysis, sample_labels) -> None:
    s = score(candidates(sample_analysis), sample_labels)
    by_id = {o.id: o for o in sample_analysis.opportunities}
    expected = {p["id"]: p["expected"] for p in sample_labels["planted"]}
    totals = []
    for pid, oid in s.found.items():
        r = rubric_score(rules_proposal(by_id[oid]), expected[pid])
        totals.append(sum(r.values()) / len(r))
        assert r["trigger"] == 1.0, pid
    assert sum(totals) / len(totals) > 0.75
