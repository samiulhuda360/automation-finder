from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_finder.evaluate import load_folder
from automation_finder.events import Event
from automation_finder.pipeline import Analysis, analyse

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "acme-plumbing"


@pytest.fixture(scope="session")
def sample_events() -> list[Event]:
    return load_folder(SAMPLE)


@pytest.fixture(scope="session")
def sample_labels() -> dict:
    return json.loads((SAMPLE / "labels.json").read_text())


@pytest.fixture(scope="session")
def sample_analysis() -> Analysis:
    return analyse(load_folder(SAMPLE))
