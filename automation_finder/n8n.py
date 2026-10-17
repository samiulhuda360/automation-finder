"""Builds an importable n8n workflow skeleton for a proposal, checks its structure, and can test-import it.

The skeleton is a starting point, not a finished integration: it has the right trigger, a filter for this
pattern, the AI step (an HTTP call to an OpenAI-compatible API, key read from $env, falling back instead of
failing), an approval wait where the proposal needs one, and the write step as an HTTP request to the target
system's API (address from $env). It never stores credentials. A manual "Try with sample data" trigger feeds a
sample record through the same path, so the workflow can be opened and run in the editor straight away.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from automation_finder.events import num
from automation_finder.opportunities import Opportunity
from automation_finder.propose import Proposal

NS = uuid.UUID("6f1d8a52-3c47-4e2b-9a0e-5b7c2d9e1f43")
# Node types and the typeVersions used here; all exist in n8n 2.8 (tests check this against an installed n8n).
NODE_VERSIONS: dict[str, float] = {
    "n8n-nodes-base.manualTrigger": 1,
    "n8n-nodes-base.scheduleTrigger": 1.2,
    "n8n-nodes-base.webhook": 2,
    "n8n-nodes-base.emailReadImap": 2,
    "n8n-nodes-base.code": 2,
    "n8n-nodes-base.httpRequest": 4.2,
    "n8n-nodes-base.wait": 1.1,
    "n8n-nodes-base.if": 2,
    "n8n-nodes-base.set": 3.4,
    "n8n-nodes-base.stickyNote": 1,
}
TRIGGER_TYPES = {
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.emailReadImap",
}
SECRET_RE = re.compile(
    r"AIza[0-9A-Za-z_\-]{20,}|\bsk-[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|Bearer [A-Za-z0-9._\-]{20,}"
)
AI_URL = (
    "={{ ($env.AI_BASE_URL || 'https://generativelanguage.googleapis.com/v1beta/openai') + '/chat/completions' }}"
)


def _uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, ":".join(parts)))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "workflow"


def _env_name(system: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", system.upper()).strip("_") + "_API_URL"


class Flow:
    def __init__(self, name: str, key: str) -> None:
        self.name = name
        self.key = key
        self.nodes: list[dict[str, Any]] = []
        self.connections: dict[str, dict[str, list[list[dict[str, Any]]]]] = {}

    def add(self, name: str, type_: str, pos: tuple[int, int], params: dict[str, Any], **extra: Any) -> str:
        self.nodes.append(
            {
                "parameters": params,
                "id": _uid(self.key, name),
                "name": name,
                "type": type_,
                "typeVersion": NODE_VERSIONS[type_],
                "position": list(pos),
                **extra,
            }
        )
        return name

    def link(self, src: str, dst: str, output: int = 0) -> None:
        main = self.connections.setdefault(src, {"main": []})["main"]
        while len(main) <= output:
            main.append([])
        main[output].append({"node": dst, "type": "main", "index": 0})

    def to_json(self, description: str) -> dict[str, Any]:
        return {
            "id": _uid(self.key, "workflow").replace("-", "")[:16],
            "name": self.name,
            "nodes": self.nodes,
            "connections": self.connections,
            "active": False,
            "settings": {"executionOrder": "v1"},
            "pinData": {},
            "meta": {"templateCredsSetupCompleted": False, "description": description},
            "tags": [],
        }


def _match_code(o: Opportunity) -> str:
    """Keeps only items that look like this pattern: the fixed words of the examples."""
    words = sorted({w for ex in o.examples[:3] for w in re.findall(r"[a-z]{4,}", ex.lower())})[:8]
    pattern = "|".join(words) or "."
    return (
        "// Keep only the items that belong to this pattern (words taken from the examples found in the data).\n"
        f"const PATTERN = /{pattern}/i;\n"
        "return $input.all().filter((item) => {\n"
        "  const j = item.json;\n"
        "  const text = [j.subject, j.title, j.text, j.action, j.description].filter(Boolean).join(' ');\n"
        "  return text === '' || PATTERN.test(text);\n"
        "});\n"
    )


def _sample(o: Opportunity) -> dict[str, Any]:
    ex = o.examples[0] if o.examples else "sample"
    return {"subject": ex, "text": ex, "from": "sample@example.com", "reference": "REF-1001", "sample": True}


def build_workflow(o: Opportunity, p: Proposal) -> dict[str, Any]:
    name = f"{o.id} - {p.title}"[:120]
    f = Flow(name, f"{o.id}:{p.title}")
    x = 0
    sample = f.add("Try with sample data", "n8n-nodes-base.manualTrigger", (x, 0), {})
    f.add(
        "Sample record",
        "n8n-nodes-base.set",
        (x + 220, 0),
        {"mode": "raw", "jsonOutput": json.dumps(_sample(o), indent=1), "options": {}},
    )
    f.link(sample, "Sample record")

    if p.trigger_type == "schedule":
        hour = int(num(o.evidence.get("hour"), 9))
        if o.period == "weekly":
            day = (
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(o.anchor.split()[-1]) + 1
                if o.anchor.split()[-1] in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
                else 1
            )
            rule = {"field": "weeks", "weeksInterval": 1, "triggerAtDay": [day], "triggerAtHour": hour}
        elif o.period == "monthly":
            rule = {"field": "months", "monthsInterval": 1, "triggerAtDayOfMonth": 1, "triggerAtHour": hour}
        else:
            rule = {"field": "days", "daysInterval": 1, "triggerAtHour": hour}
        trigger = f.add("Schedule", "n8n-nodes-base.scheduleTrigger", (x, -200), {"rule": {"interval": [rule]}})
    elif p.trigger_type == "email":
        trigger = f.add(
            "New email (IMAP)",
            "n8n-nodes-base.emailReadImap",
            (x, -200),
            {"mailbox": "INBOX", "postProcessAction": "nothing", "options": {}},
        )
    else:
        path = slug(f"{o.id}-{p.trigger_type}")
        trigger = f.add(
            "Incoming event (webhook)",
            "n8n-nodes-base.webhook",
            (x, -200),
            {"httpMethod": "POST", "path": path, "responseMode": "onReceived", "options": {}},
            webhookId=_uid(f.key, "webhook"),
        )

    match = f.add(
        "Match this pattern",
        "n8n-nodes-base.code",
        (x + 440, -100),
        {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": _match_code(o)},
    )
    f.link(trigger, match)
    f.link("Sample record", match)
    last = match
    pos = x + 660

    if p.ai_help:
        prompt = (
            "You help automate this task: "
            + p.title
            + ". Steps: "
            + " | ".join(p.steps)
            + ". From the item below, return JSON with the fields needed and a confidence from 0 to 1."
        )
        body = (
            "={{ JSON.stringify({ model: $env.AI_MODEL || 'gemini-flash-lite-latest', temperature: 0, "
            "response_format: { type: 'json_object' }, messages: [ { role: 'system', content: "
            + json.dumps(prompt)
            + " }, { role: 'user', content: JSON.stringify($json) } ] }) }}"
        )
        ai = f.add(
            "AI: read and extract",
            "n8n-nodes-base.httpRequest",
            (pos, -100),
            {
                "method": "POST",
                "url": AI_URL,
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [{"name": "Authorization", "value": "=Bearer {{ $env.AI_API_KEY }}"}]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": body,
                "options": {"timeout": 30000},
            },
            onError="continueRegularOutput",
            retryOnFail=True,
            maxTries=2,
        )
        f.link(last, ai)
        parse = f.add(
            "Use AI answer or fall back",
            "n8n-nodes-base.code",
            (pos + 220, -100),
            {
                "mode": "runOnceForEachItem",
                "language": "javaScript",
                "jsCode": (
                    "// If the model call failed or answered badly, pass the item on for a person to handle.\n"
                    "let fields = {};\n"
                    "try { fields = JSON.parse($json.choices[0].message.content); } catch (e) { fields = {}; }\n"
                    "const original = $('Match this pattern').item.json;\n"
                    "const confidence = Number(fields.confidence || 0);\n"
                    "const needs_person = confidence < 0.8;\n"
                    "return { json: { ...original, extracted: fields, confidence, needs_person } };\n"
                ),
            },
        )
        f.link(ai, parse)
        last, pos = parse, pos + 440

    if p.needs_approval:
        ask = f.add(
            "Ask for approval",
            "n8n-nodes-base.httpRequest",
            (pos, -100),
            {
                "method": "POST",
                "url": "={{ $env.APPROVAL_WEBHOOK_URL }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ text: 'Please approve: ' + ($json.subject || $json.text || 'item')"
                " + ' (reply via ' + $execution.resumeUrl + ')' }) }}",
                "options": {},
            },
            onError="continueRegularOutput",
        )
        f.link(last, ask)
        wait = f.add(
            "Wait for the decision",
            "n8n-nodes-base.wait",
            (pos + 220, -100),
            {"resume": "webhook", "httpMethod": "POST", "options": {}},
            webhookId=_uid(f.key, "wait"),
        )
        f.link(ask, wait)
        decide = f.add(
            "Approved?",
            "n8n-nodes-base.if",
            (pos + 440, -100),
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                    "conditions": [
                        {
                            "id": _uid(f.key, "approved"),
                            "leftValue": "={{ $json.body ? $json.body.approved : false }}",
                            "rightValue": True,
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        )
        f.link(wait, decide)
        last, pos = decide, pos + 660

    target = p.systems[-1] if p.systems else "target"
    action_label = f"Do the routine in {target}" if p.trigger_type == "schedule" else f"Write to {target}"
    write = f.add(
        action_label,
        "n8n-nodes-base.httpRequest",
        (pos, -100),
        {
            "method": "POST",
            "url": f"={{{{ $env.{_env_name(target)} }}}}/records",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json) }}",
            "options": {},
        },
    )
    f.link(last, write)

    note = "\n".join(
        [
            f"## {p.title}",
            f"Today: {p.today}",
            f"Estimated time saved: {p.hours_saved_per_month} hours a month (an estimate; see the report).",
            f"Risk: {p.risk} - {p.risk_reason}",
            "",
            "Before switching on: set the trigger's credentials, "
            + _env_name(target)
            + (", APPROVAL_WEBHOOK_URL" if p.needs_approval else "")
            + (" and AI_API_KEY" if p.ai_help else "")
            + " in the n8n environment.",
        ]
    )
    f.add(
        "About this workflow",
        "n8n-nodes-base.stickyNote",
        (x, 200),
        {"content": note, "height": 300, "width": 620, "color": 4},
    )
    return f.to_json(p.today)


# --------------------------------------------------------------------------------------------- validation
def validate_workflow(wf: dict[str, Any]) -> list[str]:
    """Structural checks against n8n's workflow format, plus this project's safety rules."""
    problems: list[str] = []
    for key, kind in (("name", str), ("nodes", list), ("connections", dict), ("settings", dict)):
        if not isinstance(wf.get(key), kind):
            problems.append(f"top-level '{key}' missing or not a {kind.__name__}")
    if problems:
        return problems
    nodes = {}
    ids = set()
    for n in wf["nodes"]:
        for key, kind in (("id", str), ("name", str), ("type", str), ("parameters", dict), ("position", list)):
            if not isinstance(n.get(key), kind):
                problems.append(f"node {n.get('name')!r}: '{key}' missing or not a {kind.__name__}")
        if not isinstance(n.get("typeVersion"), int | float):
            problems.append(f"node {n.get('name')!r}: typeVersion missing")
        if len(n.get("position", [])) != 2:
            problems.append(f"node {n.get('name')!r}: position must be [x, y]")
        if n.get("type") not in NODE_VERSIONS:
            problems.append(f"node {n.get('name')!r}: unknown node type {n.get('type')}")
        elif n.get("typeVersion") != NODE_VERSIONS[n["type"]]:
            problems.append(f"node {n.get('name')!r}: unexpected typeVersion {n.get('typeVersion')}")
        if n.get("name") in nodes:
            problems.append(f"duplicate node name {n.get('name')!r}")
        if n.get("id") in ids:
            problems.append(f"duplicate node id {n.get('id')!r}")
        nodes[n.get("name")] = n
        ids.add(n.get("id"))
        if "credentials" in n:
            problems.append(f"node {n['name']!r} stores credentials")
        for h in n.get("parameters", {}).get("headerParameters", {}).get("parameters", []):
            if h.get("name", "").lower() == "authorization" and "$env." not in h.get("value", ""):
                problems.append(f"node {n['name']!r}: Authorization must be read from $env")
    targets: dict[str, list[str]] = {}
    for src, outs in wf["connections"].items():
        if src not in nodes:
            problems.append(f"connection from unknown node {src!r}")
        if not isinstance(outs.get("main"), list):
            problems.append(f"connections of {src!r} need a 'main' list")
            continue
        for branch in outs["main"]:
            for edge in branch:
                if edge.get("node") not in nodes:
                    problems.append(f"connection to unknown node {edge.get('node')!r}")
                if edge.get("type") != "main" or not isinstance(edge.get("index"), int):
                    problems.append(f"bad connection entry from {src!r}")
                targets.setdefault(src, []).append(edge.get("node"))
    real = {k: v for k, v in nodes.items() if v.get("type") != "n8n-nodes-base.stickyNote"}
    starts = [k for k, v in real.items() if v.get("type") in TRIGGER_TYPES]
    if not any(real[s]["type"] != "n8n-nodes-base.manualTrigger" for s in starts):
        problems.append("no production trigger (schedule, webhook or email)")
    seen, queue = set(starts), deque(starts)
    while queue:
        for nxt in targets.get(queue.popleft(), []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    for name in real:
        if name not in seen:
            problems.append(f"node {name!r} is not reachable from a trigger")
    if SECRET_RE.search(json.dumps(wf)):
        problems.append("possible secret in the workflow")
    return problems


# --------------------------------------------------------------------------------------------- test import
def find_n8n() -> list[str] | None:
    configured = os.environ.get("N8N_BIN")
    if configured:
        path = Path(configured)
        if path.suffix.lower() in (".cmd", ".exe", ".bat") or path.name == "n8n":
            return [str(path)] if path.suffix else ["node", str(path)]
        return ["node", str(path)]
    found = shutil.which("n8n")
    return [found] if found else None


def test_import(
    workflows: list[dict[str, Any]], command: list[str] | None = None, timeout: int = 600
) -> dict[str, Any]:
    """Imports the workflows into a throwaway n8n data folder, exports them again, and compares the nodes."""
    command = command or find_n8n()
    if not command:
        return {"ran": False, "reason": "n8n not found (set N8N_BIN or install n8n)"}
    with tempfile.TemporaryDirectory(prefix="af-n8n-") as tmp:
        root = Path(tmp)
        src, out = root / "in", root / "out"
        src.mkdir()
        out.mkdir()
        for i, wf in enumerate(workflows):
            (src / f"wf{i}.json").write_text(json.dumps(wf), encoding="utf-8")
        env = {
            **os.environ,
            "N8N_USER_FOLDER": str(root / "home"),
            "N8N_DIAGNOSTICS_ENABLED": "false",
            "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
            "N8N_RUNNERS_ENABLED": "false",
        }

        def run(args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [*command, *args],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )

        imp = run(["import:workflow", "--separate", f"--input={src}"])
        if imp.returncode != 0:
            return {"ran": True, "ok": False, "step": "import", "output": (imp.stdout + imp.stderr)[-2000:]}
        exp = run(["export:workflow", "--all", "--separate", f"--output={out}"])
        if exp.returncode != 0:
            return {"ran": True, "ok": False, "step": "export", "output": (exp.stdout + exp.stderr)[-2000:]}
        exported = {}
        for path in out.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            exported[data["name"]] = sorted(n["name"] for n in data["nodes"])
        results = []
        for wf in workflows:
            want = sorted(n["name"] for n in wf["nodes"])
            results.append({"name": wf["name"], "imported": exported.get(wf["name"]) == want})
        version = run(["--version"]).stdout.strip().splitlines()[-1:] or [""]
        return {
            "ran": True,
            "ok": all(r["imported"] for r in results),
            "n8n_version": version[0],
            "workflows": results,
        }
