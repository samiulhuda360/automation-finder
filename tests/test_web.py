from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from automation_finder.web.app import create_app
from tests.conftest import SAMPLE


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(model="off"))


def test_sample_analysis_and_downloads(client: TestClient) -> None:
    r = client.post("/api/sample")
    assert r.status_code == 200
    data = r.json()
    assert data["business"] == "Acme Plumbing" and len(data["opportunities"]) >= 8
    assert all(o["workflow_ok"] for o in data["opportunities"])
    sid = data["session"]
    html = client.get(f"/api/session/{sid}/report.html").text
    assert "Where Acme Plumbing loses time" in html and "These hours are estimates" in html
    assert client.get(f"/api/session/{sid}/report.md").text.startswith("# Where Acme Plumbing loses time")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/session/{sid}/workflows.zip").content))
    assert len(z.namelist()) == 5
    wf = client.get(f"/api/session/{sid}/workflow/O1.json").json()
    assert wf["nodes"] and wf["connections"]


def test_editing_minutes_recalculates(client: TestClient) -> None:
    data = client.post("/api/sample").json()
    o = data["opportunities"][1]
    r = client.post(f"/api/session/{data['session']}/minutes", json={"minutes": {o["id"]: 1}})
    after = next(x for x in r.json()["opportunities"] if x["id"] == o["id"])
    assert after["minutes_per_task"] == 1
    assert after["hours_per_month"] == pytest.approx(o["occurrences_per_month"] / 60, abs=0.02)
    bad = client.post(f"/api/session/{data['session']}/minutes", json={"minutes": {o["id"]: -5}})
    assert bad.status_code == 400


def test_upload_with_renamed_columns_and_mapping(client: TestClient) -> None:
    activity = (SAMPLE / "activity.csv").read_text(encoding="utf-8").replace("User,Action", "Staff member,Did", 1)
    files = [
        ("files", ("mail.csv", (SAMPLE / "emails.csv").read_bytes(), "text/csv")),
        ("files", ("log.csv", activity.encode(), "text/csv")),
        ("files", ("cal.ics", (SAMPLE / "calendar.ics").read_bytes(), "text/calendar")),
    ]
    inspected = client.post("/api/inspect", files=files).json()
    log = next(f for f in inspected if f["name"] == "log.csv")
    assert log["kind"] == "activity" and log["mapping"]["user"] == "Staff member"
    assert log["missing"] == ["action"]  # "Did" is not a known name, so the person picks it in the page
    log["mapping"]["action"] = "Did"
    config = {f["name"]: {"kind": f["kind"], "mapping": f["mapping"]} for f in inspected}
    r = client.post("/api/analyse", files=files, data={"config": json.dumps(config), "business": "Test Co"})
    assert r.status_code == 200 and r.json()["opportunities"]


def test_unreadable_upload_gives_a_clear_error(client: TestClient) -> None:
    files = [("files", ("x.csv", b"Foo,Bar\n1,2\n", "text/csv"))]
    r = client.post("/api/analyse", files=files, data={"config": "{}"})
    assert r.status_code == 400 and "choose the columns" in r.json()["detail"]


def test_expired_session(client: TestClient) -> None:
    assert client.get("/api/session/nope/report.html").status_code == 404
