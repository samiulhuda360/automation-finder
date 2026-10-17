from __future__ import annotations

import copy
import os
import re
from pathlib import Path

import pytest

from automation_finder.llm import ChatClient
from automation_finder.n8n import NODE_VERSIONS, build_workflow, validate_workflow
from automation_finder.propose import model_proposal, rules_proposal, validate_model_answer

# Set N8N_NODES_DIR to an n8n install's n8n-nodes-base/dist/nodes folder to check the node versions.
N8N_NODES = Path(os.environ.get("N8N_NODES_DIR", "no-n8n-install"))


class FakeClient(ChatClient):
    def __init__(self, answer: dict) -> None:
        super().__init__(Path("unused"), "off")
        self.answer = answer

    def json_chat(self, messages):  # type: ignore[override]
        return copy.deepcopy(self.answer)


GOOD = {
    "title": "Enter supplier bills from email",
    "trigger_type": "email",
    "trigger": "A supplier invoice arrives",
    "steps": ["Read the invoice", "Draft the bill", "Save it"],
    "ai_help": ["Extract fields"],
    "human_approval": [],
    "needs_approval": False,
    "risk": "low",
    "risk_reason": "small",
    "systems": ["Email", "Accounts"],
}


def test_every_top_workflow_passes_validation(sample_analysis) -> None:
    for o in sample_analysis.opportunities:
        wf = build_workflow(o, rules_proposal(o))
        assert validate_workflow(wf) == [], o.id
        assert wf["nodes"][0]["name"] == "Try with sample data"
        assert not any("credentials" in n for n in wf["nodes"])


def test_validation_catches_broken_workflows(sample_analysis) -> None:
    o = sample_analysis.opportunities[0]
    wf = build_workflow(o, rules_proposal(o))
    broken = copy.deepcopy(wf)
    broken["nodes"][3]["type"] = "n8n-nodes-base.doesNotExist"
    broken["connections"]["Ghost"] = {"main": [[{"node": "Nowhere", "type": "main", "index": 0}]]}
    broken["nodes"][2]["credentials"] = {"imap": {"id": "1"}}
    broken["nodes"].append({**broken["nodes"][3], "id": "x", "name": "Island", "type": "n8n-nodes-base.code"})
    problems = " | ".join(validate_workflow(broken))
    for expected in ("unknown node type", "unknown node 'Ghost'", "Nowhere", "stores credentials", "not reachable"):
        assert expected in problems
    leaked = copy.deepcopy(wf)
    leaked["nodes"][1]["parameters"]["jsonOutput"] = "AIza" + "x" * 30
    assert "possible secret in the workflow" in validate_workflow(leaked)


def test_approval_proposals_get_a_wait_node(sample_analysis) -> None:
    risky = next(o for o in sample_analysis.opportunities if o.risk == "high")
    wf = build_workflow(risky, rules_proposal(risky))
    types = [n["type"] for n in wf["nodes"]]
    assert "n8n-nodes-base.wait" in types and "n8n-nodes-base.if" in types


def installed_versions(folder: Path) -> set[float]:
    """Every typeVersion a node folder declares: versioned-node keys and description version lists."""
    versions: set[float] = set()
    for js in folder.rglob("*.js"):
        text = js.read_text(encoding="utf-8", errors="replace")
        versions |= {float(v) for v in re.findall(r"^\s+(\d+(?:\.\d+)?): new ", text, flags=re.M)}
        for group in re.findall(r"version: \[([^\]]+)\]", text):
            versions |= {float(v) for v in group.split(",") if v.strip()}
        versions |= {float(v) for v in re.findall(r"version: (\d+(?:\.\d+)?)\b", text)}
    return versions


@pytest.mark.skipif(not N8N_NODES.exists(), reason="no local n8n install")
def test_node_versions_exist_in_installed_n8n() -> None:
    folders = {
        "manualTrigger": "ManualTrigger",
        "scheduleTrigger": "Schedule",
        "webhook": "Webhook",
        "emailReadImap": "EmailReadImap",
        "code": "Code",
        "httpRequest": "HttpRequest",
        "wait": "Wait",
        "if": "If",
        "set": "Set",
        "stickyNote": "StickyNote",
    }
    for node, version in NODE_VERSIONS.items():
        assert float(version) in installed_versions(N8N_NODES / folders[node.split(".")[1]]), node


def test_model_answer_is_used_and_the_safety_rules_still_hold(sample_analysis) -> None:
    risky = next(o for o in sample_analysis.opportunities if o.risk == "high")
    p = model_proposal(risky, FakeClient(GOOD))
    assert p.source == "model" and p.title == GOOD["title"]
    assert p.risk == "high" and p.needs_approval and p.human_approval
    assert any("raised" in n for n in p.notes)
    assert p.systems == ["email", "accounts"]


def test_bad_model_answers_fall_back_to_the_rules(sample_analysis) -> None:
    o = sample_analysis.opportunities[0]
    bad = {**GOOD, "trigger_type": "carrier pigeon", "steps": "do it"}
    assert len(validate_model_answer(bad)) == 2
    p = model_proposal(o, FakeClient(bad))
    assert p.source == "rules" and p.notes


def test_replay_mode_never_calls_the_api(tmp_path, sample_analysis, monkeypatch) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    client = ChatClient(tmp_path, "replay")
    p = model_proposal(sample_analysis.opportunities[0], client)
    assert p.source == "rules" and client.calls == 0
    assert "no stored answer" in p.notes[0]
