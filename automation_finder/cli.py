"""Command line.

python -m automation_finder sample                 # write the invented Acme Plumbing exports to data/
python -m automation_finder analyse data/acme-plumbing --out results/acme-plumbing
python -m automation_finder eval                   # pattern finding vs labels, with the baselines
python -m automation_finder eval-proposals         # proposal rubric: rules vs the model (replayed)
python -m automation_finder n8n-check results/acme-plumbing/workflows   # structure + test import
python -m automation_finder serve                  # the web app on http://127.0.0.1:8000
python -m automation_finder demo                   # sample data, analysis and the web app in one go
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from automation_finder.evaluate import load_folder, proposal_eval, run
from automation_finder.llm import ChatClient
from automation_finder.n8n import build_workflow, slug, test_import, validate_workflow
from automation_finder.pipeline import analyse
from automation_finder.propose import propose_all
from automation_finder.report import render_html, render_markdown
from automation_finder.sample import write_dataset
from automation_finder.similarity import Embedder, GeminiEmbedder, TfidfEmbedder

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "eval-cache"
SAMPLE = ROOT / "data" / "acme-plumbing"


def make_embedder(name: str, live: bool) -> Embedder:
    if name == "gemini":
        return GeminiEmbedder(CACHE / "embeddings", "live" if live else "replay")
    return TfidfEmbedder()


def make_client(mode: str) -> ChatClient | None:
    return None if mode == "off" else ChatClient(CACHE / "llm", mode)


def cmd_sample(args: argparse.Namespace) -> int:
    paths = write_dataset(Path(args.out), args.seed)
    for kind, path in paths.items():
        print(f"{kind:9s} {path}")
    print(f"labels    {Path(args.out) / 'labels.json'}")
    return 0


def write_outputs(folder: Path, out: Path, embedder: Embedder, model: str, business: str) -> dict[str, Any]:
    analysis = analyse(load_folder(folder), embedder)
    proposals = propose_all(analysis.opportunities, make_client(model))
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(analysis, proposals, business), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(analysis, proposals, business), encoding="utf-8")
    wf_dir = out / "workflows"
    wf_dir.mkdir(exist_ok=True)
    for old in wf_dir.glob("*.json"):
        old.unlink()
    by_id = {p.opportunity: p for p in proposals}
    problems = {}
    for o in analysis.opportunities[:5]:
        wf = build_workflow(o, by_id[o.id])
        problems[o.id] = validate_workflow(wf)
        (wf_dir / f"{o.id}-{slug(by_id[o.id].title)}.json").write_text(json.dumps(wf, indent=2), encoding="utf-8")
    data: dict[str, Any] = {
        "summary": analysis.summary(),
        "opportunities": [o.to_dict() for o in analysis.opportunities],
        "proposals": [p.to_dict() for p in proposals],
        "workflow_problems": problems,
    }
    (out / "opportunities.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return data


def cmd_analyse(args: argparse.Namespace) -> int:
    data = write_outputs(
        Path(args.folder), Path(args.out), make_embedder(args.embed, args.live), args.model, args.business
    )
    s = data["summary"]
    print(
        f"{s['events']} events, {s['months']} months, {s['opportunities']} opportunities "
        f"(similarity: {s['embedder']})"
    )
    for o in data["opportunities"][:10]:
        print(
            f"  {o['id']:4s} {o['kind']:15s} {o['hours_per_month']:6.1f} h/month"
            f"  saves {o['hours_saved_per_month']:5.1f}"
            f"  risk {o['risk']:6s}  {', '.join(o['actors'][:2])}: {o['examples'][0] if o['examples'] else ''}"
        )
    bad = {k: v for k, v in data["workflow_problems"].items() if v}
    print(
        f"report: {Path(args.out) / 'report.html'}   workflows: {Path(args.out) / 'workflows'}"
        f"   workflow problems: {bad or 'none'}"
    )
    return 0


def _seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def cmd_eval(args: argparse.Namespace) -> int:
    embedders = [make_embedder(name, args.live) for name in args.embed.split(",")]
    result = run(_seeds(args.seeds), embedders, hard=args.hard)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = "eval-hard.json" if args.hard else "eval.json"
    (out / name).write_text(json.dumps(result, indent=1), encoding="utf-8")
    from automation_finder.results import write_results

    write_results(out)
    print(json.dumps(result["summary"], indent=1))
    return 0


def cmd_eval_proposals(args: argparse.Namespace) -> int:
    client = ChatClient(CACHE / "llm", "live" if args.live else "replay")
    result = proposal_eval(_seeds(args.seeds), client)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "proposals.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    from automation_finder.results import write_results

    write_results(out)
    print(json.dumps(result["summary"], indent=1))
    print(f"model calls this run: {client.calls}, answers replayed: {client.hits}")
    return 0


def cmd_n8n_check(args: argparse.Namespace) -> int:
    files = sorted(Path(args.folder).glob("*.json"))
    workflows = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    failed = False
    for f, wf in zip(files, workflows, strict=True):
        problems = validate_workflow(wf)
        failed |= bool(problems)
        print(f"{'ok ' if not problems else 'BAD'} {f.name}" + "".join(f"\n    - {p}" for p in problems))
    if args.import_test:
        result = test_import(workflows)
        print(json.dumps(result, indent=1))
        if result.get("ran"):
            failed |= not result.get("ok")
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "n8n-import.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 1 if failed else 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from automation_finder.web.app import create_app

    uvicorn.run(create_app(model=args.model), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    if not (SAMPLE / "emails.csv").exists():
        write_dataset(SAMPLE, 0)
    write_outputs(SAMPLE, ROOT / "results" / "acme-plumbing", TfidfEmbedder(), args.model, "Acme Plumbing")
    print(f"sample report written to {ROOT / 'results' / 'acme-plumbing' / 'report.html'}")
    print(f"open http://127.0.0.1:{args.port} and press 'Use the Acme Plumbing sample'")
    return cmd_serve(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="automation-finder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sample", help="write the invented sample exports")
    p.add_argument("--out", default=str(SAMPLE))
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("analyse", help="analyse a folder of exports")
    p.add_argument("folder")
    p.add_argument("--out", default="results/analysis")
    p.add_argument("--embed", choices=["tfidf", "gemini"], default="tfidf")
    p.add_argument("--live", action="store_true", help="allow embedding API calls for uncached texts")
    p.add_argument("--model", choices=["off", "replay", "live"], default="replay")
    p.add_argument("--business", default="your business")
    p.set_defaults(func=cmd_analyse)

    p = sub.add_parser("eval", help="pattern recall/precision and hours error against the labels")
    p.add_argument("--seeds", default="1-5")
    p.add_argument("--embed", default="tfidf,gemini")
    p.add_argument("--live", action="store_true")
    p.add_argument("--hard", action="store_true", help="rarer patterns, slower follow-ups, irregular timing")
    p.add_argument("--out", default="results")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("eval-proposals", help="proposal rubric: rules vs the model")
    p.add_argument("--seeds", default="1-5")
    p.add_argument("--live", action="store_true")
    p.add_argument("--out", default="results")
    p.set_defaults(func=cmd_eval_proposals)

    p = sub.add_parser("n8n-check", help="validate workflow files and optionally test-import them into n8n")
    p.add_argument("folder")
    p.add_argument("--import-test", action="store_true")
    p.add_argument("--out", default="results")
    p.set_defaults(func=cmd_n8n_check)

    for name, func in (("serve", cmd_serve), ("demo", cmd_demo)):
        p = sub.add_parser(name)
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
        p.add_argument("--model", choices=["off", "replay", "live"], default="replay")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
