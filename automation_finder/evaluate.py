"""Measures the finder against the planted labels, next to the keyword-counting baseline.

For every candidate (an opportunity, or a baseline keyword) we look at its events:
- purity: the largest share of its events that belong to one planted pattern;
- a candidate "hits" pattern P when at least half of its events belong to P;
- a planted pattern counts as found when a candidate hits it and covers at least 25% of P's events.
Precision is strict: each planted pattern can be claimed by one candidate only; a second fragment of the same
pattern, a distractor or noise counts as a wrong candidate. Hours are compared for every found pattern:
the candidate's estimated hours per month against the planted truth.

Seed 0 is the development seed (thresholds were tuned on it); the reported numbers use seeds 1-5.
"""

from __future__ import annotations

import json
import statistics
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automation_finder.baseline import keyword_patterns, repeat_patterns
from automation_finder.events import Event
from automation_finder.ingest import detect_kind, load_all
from automation_finder.pipeline import analyse, embedding_texts
from automation_finder.sample import HARD, NORMAL, write_dataset
from automation_finder.similarity import Embedder

PURITY = 0.5
COVERAGE = 0.25


@dataclass
class Candidate:
    name: str
    events: set[str]
    hours: float


@dataclass
class Score:
    found: dict[str, str] = field(default_factory=dict)  # planted id -> candidate name
    hours: dict[str, tuple[float, float]] = field(default_factory=dict)  # planted id -> (estimate, truth)
    coverage: dict[str, float] = field(default_factory=dict)  # planted id -> share of its events captured
    correct: int = 0
    candidates: int = 0
    top5_correct: int = 0
    top5: int = 0
    distractor_hits: int = 0

    @property
    def recall(self) -> float:
        return len(self.found) / 8

    @property
    def precision(self) -> float:
        return self.correct / self.candidates if self.candidates else 0.0

    @property
    def hours_mape(self) -> float:
        errs = [abs(e - t) / t for e, t in self.hours.values() if t]
        return statistics.mean(errs) if errs else float("nan")


def score(candidates: list[Candidate], labels: dict[str, Any]) -> Score:
    owner: dict[str, str] = {}
    for group in (*labels["planted"], *labels["distractors"]):
        for eid in group["events"]:
            owner[eid] = group["id"]
    planted = {p["id"]: p for p in labels["planted"]}
    s = Score(candidates=len(candidates), top5=min(5, len(candidates)))
    claims: list[tuple[float, int, str]] = []
    for i, c in enumerate(candidates):
        counts = Counter(owner.get(e, "noise") for e in c.events)
        best, n = counts.most_common(1)[0]
        if best.startswith("D") and n / len(c.events) >= PURITY:
            s.distractor_hits += 1
        if best in planted and n / len(c.events) >= PURITY:
            coverage = n / len(planted[best]["events"])
            if coverage >= COVERAGE:
                claims.append((coverage, i, best))
    claimed: dict[str, int] = {}
    for _coverage, i, pid in sorted(claims, reverse=True):
        if pid not in claimed:
            claimed[pid] = i
    for coverage, i, pid in claims:
        if claimed.get(pid) == i:
            s.coverage[pid] = round(coverage, 3)
    for pid, i in claimed.items():
        s.found[pid] = candidates[i].name
        s.hours[pid] = (candidates[i].hours, float(planted[pid]["true_hours_per_month"]))
        s.correct += 1
        if i < 5:
            s.top5_correct += 1
    return s


def load_folder(folder: Path) -> list[Event]:
    files = {}
    for name in ("emails.csv", "tickets.csv", "calendar.ics", "activity.csv"):
        text = (folder / name).read_text(encoding="utf-8")
        files[name] = (detect_kind(name, text), text, None)
    return load_all(files)


def run_seed(seed: int, embedders: list[Embedder], workdir: Path, hard: bool = False) -> dict[str, Any]:
    folder = workdir / f"seed{seed}"
    write_dataset(folder, seed, HARD if hard else NORMAL)
    labels = json.loads((folder / "labels.json").read_text())
    out: dict[str, Any] = {"seed": seed, "truth": {p["id"]: p["true_hours_per_month"] for p in labels["planted"]}}
    for emb in embedders:
        events = load_folder(folder)
        analysis = analyse(events, emb)
        cands = [Candidate(o.id, set(o.events), o.hours_per_month) for o in analysis.opportunities]
        out[emb.name] = _as_dict(score(cands, labels))
    events = load_folder(folder)
    base = keyword_patterns(events, top=10)
    out["keyword_baseline"] = _as_dict(
        score([Candidate(k.keyword, set(k.events), k.hours_per_month) for k in base], labels)
    )
    rep = repeat_patterns(events, top=10)
    out["repeat_baseline"] = _as_dict(
        score([Candidate(k.keyword, set(k.events), k.hours_per_month) for k in rep], labels)
    )
    return out


def _as_dict(s: Score) -> dict[str, Any]:
    return {
        "recall": round(s.recall, 3),
        "precision": round(s.precision, 3),
        "top5_precision": round(s.top5_correct / s.top5, 3) if s.top5 else 0.0,
        "candidates": s.candidates,
        "found": s.found,
        "distractor_hits": s.distractor_hits,
        "hours": {k: [round(e, 2), t] for k, (e, t) in s.hours.items()},
        "coverage": s.coverage,
        "event_recall": round(sum(s.coverage.values()) / 8, 3),
        "hours_mape": round(s.hours_mape, 3) if s.hours else None,
    }


def _prefetch(seeds: list[int], embedders: list[Embedder], root: Path, hard: bool) -> None:
    """Fetches all missing embeddings in a few large batches before the runs (live mode only)."""
    live = [e for e in embedders if getattr(e, "mode", "") == "live"]
    if not live:
        return
    texts: list[str] = []
    for seed in seeds:
        folder = root / f"prefetch{seed}"
        write_dataset(folder, seed, HARD if hard else NORMAL)
        texts += embedding_texts(load_folder(folder))
    for e in live:
        e.vectors(list(dict.fromkeys(texts)))


def run(
    seeds: list[int], embedders: list[Embedder], workdir: Path | None = None, hard: bool = False
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="af-eval-") as tmp:
        root = workdir or Path(tmp)
        _prefetch(seeds, embedders, root, hard)
        per_seed = [run_seed(s, embedders, root, hard) for s in seeds]
    methods = [e.name for e in embedders] + ["keyword_baseline", "repeat_baseline"]
    summary = {}
    for m in methods:
        rows = [r[m] for r in per_seed]
        found_counts = Counter(pid for r in rows for pid in r["found"])
        mapes = [r["hours_mape"] for r in rows if r["hours_mape"] is not None]
        summary[m] = {
            "recall_mean": round(statistics.mean(r["recall"] for r in rows), 3),
            "precision_mean": round(statistics.mean(r["precision"] for r in rows), 3),
            "top5_precision_mean": round(statistics.mean(r["top5_precision"] for r in rows), 3),
            "candidates_mean": round(statistics.mean(r["candidates"] for r in rows), 1),
            "event_recall_mean": round(statistics.mean(r["event_recall"] for r in rows), 3),
            "p4_coverage_mean": round(statistics.mean(r["coverage"].get("P4", 0.0) for r in rows), 3),
            "distractor_hits": sum(r["distractor_hits"] for r in rows),
            "hours_mape_mean": round(statistics.mean(mapes), 3) if mapes else None,
            "found_in_seeds": {pid: found_counts.get(pid, 0) for pid in [f"P{i}" for i in range(1, 9)]},
        }
    return {"seeds": seeds, "hard": hard, "summary": summary, "per_seed": per_seed}


# --------------------------------------------------------------------------------------------- proposal rubric
RUBRIC = ("trigger", "systems", "approval", "risk", "key_steps")


def rubric_score(p: Any, expected: dict[str, Any]) -> dict[str, float]:
    """Five checks, each worth 0-1, against the labelled expected automation for the planted pattern."""
    text = " ".join([p.title, p.trigger, *p.steps, *p.ai_help]).lower()
    risks = ["low", "medium", "high"]
    gap = abs(risks.index(p.risk) - risks.index(expected["risk"])) if p.risk in risks else 2
    return {
        "trigger": float(p.trigger_type == expected["trigger"]),
        "systems": len(set(expected["systems"]) & set(p.systems)) / len(expected["systems"]),
        "approval": float(bool(p.needs_approval) == bool(expected["approval"])),
        "risk": {0: 1.0, 1: 0.5}.get(gap, 0.0),
        "key_steps": sum(k in text for k in expected["keywords"]) / len(expected["keywords"]),
    }


def proposal_eval(seeds: list[int], client: Any) -> dict[str, Any]:
    """Scores the rule-based proposals and the model's (raw, and after the safety rules) on every found pattern."""
    from automation_finder.propose import apply_guard, model_proposal, rules_proposal

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="af-prop-") as tmp:
        for seed in seeds:
            folder = Path(tmp) / f"seed{seed}"
            write_dataset(folder, seed)
            labels = json.loads((folder / "labels.json").read_text())
            expected = {p["id"]: p["expected"] for p in labels["planted"]}
            analysis = analyse(load_folder(folder))
            cands = [Candidate(o.id, set(o.events), o.hours_per_month) for o in analysis.opportunities]
            found = score(cands, labels).found
            by_id = {o.id: o for o in analysis.opportunities}
            for pid, oid in sorted(found.items()):
                o = by_id[oid]
                rules = rules_proposal(o)
                raw = model_proposal(o, client, guard=False)
                guarded = model_proposal(o, client, guard=False)
                apply_guard(guarded, rules)
                rows.append(
                    {
                        "seed": seed,
                        "pattern": pid,
                        "model_used": raw.source == "model",
                        "model_fixes": [n for n in raw.notes if "read as a list" in n],
                        "guard_changes": [n for n in guarded.notes if "safety rules" in n],
                        "rules": rubric_score(rules, expected[pid]),
                        "model": rubric_score(raw, expected[pid]),
                        "model_guarded": rubric_score(guarded, expected[pid]),
                    }
                )
    summary: dict[str, Any] = {}
    for method in ("rules", "model", "model_guarded"):
        used = [r for r in rows if r["model_used"]] if method != "rules" else rows
        per = {c: round(statistics.mean(r[method][c] for r in used), 3) if used else None for c in RUBRIC}
        total = [sum(r[method].values()) / len(RUBRIC) for r in used]
        summary[method] = {"score": round(statistics.mean(total), 3) if total else None, "items": len(used), **per}
    return {
        "seeds": seeds,
        "summary": summary,
        "rows": rows,
        "answers_needing_list_fix": sum(bool(r["model_fixes"]) for r in rows),
        "answers_changed_by_guard": sum(bool(r["guard_changes"]) for r in rows),
        "model_answers_used": sum(r["model_used"] for r in rows),
        "items": len(rows),
    }
