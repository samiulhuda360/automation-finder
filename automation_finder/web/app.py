"""The web app: upload exports, review what was found, edit the minutes, download the report and n8n files."""

from __future__ import annotations

import io
import json
import secrets
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from automation_finder.ingest import FIELDS, detect_kind, guess_mapping, load_all, missing_fields, read_csv
from automation_finder.llm import ChatClient
from automation_finder.n8n import build_workflow, slug, validate_workflow
from automation_finder.opportunities import KIND_NAMES, TimeModel, rank
from automation_finder.pipeline import Analysis, analyse
from automation_finder.propose import Proposal, propose_all
from automation_finder.report import render_html, render_markdown

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "acme-plumbing"
MAX_BYTES = 20 * 1024 * 1024
MAX_SESSIONS = 20


class Session:
    def __init__(self, analysis: Analysis, proposals: list[Proposal], business: str) -> None:
        self.analysis = analysis
        self.proposals = proposals
        self.business = business


class MinutesUpdate(BaseModel):
    minutes: dict[str, float]


def create_app(model: str = "replay") -> FastAPI:
    app = FastAPI(title="automation-finder", docs_url=None, redoc_url=None)
    sessions: OrderedDict[str, Session] = OrderedDict()
    client = None if model == "off" else ChatClient(ROOT / "eval-cache" / "llm", model)

    def store(s: Session) -> str:
        sid = secrets.token_urlsafe(9)
        sessions[sid] = s
        while len(sessions) > MAX_SESSIONS:
            sessions.popitem(last=False)
        return sid

    def get(sid: str) -> Session:
        if sid not in sessions:
            raise HTTPException(404, "this analysis has expired; please run it again")
        return sessions[sid]

    def payload(sid: str, s: Session) -> dict[str, Any]:
        by_id = {p.opportunity: p for p in s.proposals}
        opps = []
        for rank_no, o in enumerate(s.analysis.opportunities, 1):
            p = by_id[o.id]
            wf_problems = validate_workflow(build_workflow(o, p))
            opps.append(
                {
                    **o.to_dict(),
                    "rank": rank_no,
                    "kind_name": KIND_NAMES[o.kind],
                    "proposal": p.to_dict(),
                    "workflow_ok": not wf_problems,
                    "workflow_problems": wf_problems,
                }
            )
        return {
            "session": sid,
            "business": s.business,
            "summary": s.analysis.summary(),
            "opportunities": opps,
            "time_model": s.analysis.time_model.__dict__,
        }

    def run(files: Mapping[str, tuple[str, str, dict[str, str] | None]], business: str) -> dict[str, Any]:
        try:
            events = load_all(files)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"could not read the files: {exc}") from exc
        if len(events) < 20:
            raise HTTPException(400, "too few records to find patterns (need at least 20)")
        analysis = analyse(events, time_model=TimeModel())
        proposals = propose_all(analysis.opportunities, client)
        s = Session(analysis, proposals, business or "your business")
        sid = store(s)
        return payload(sid, s)

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/fields")
    def fields() -> dict[str, Any]:
        return {k: {f: {"required": r} for f, (r, _) in v.items()} for k, v in FIELDS.items()}

    @app.post("/api/inspect")
    async def inspect(files: list[UploadFile] = File(...)) -> list[dict[str, Any]]:  # noqa: B008
        out = []
        for f in files:
            text = (await f.read(MAX_BYTES + 1)).decode("utf-8", errors="replace")
            if len(text) > MAX_BYTES:
                raise HTTPException(413, f"{f.filename} is larger than 20 MB")
            kind = detect_kind(f.filename or "", text)
            item: dict[str, Any] = {"name": f.filename, "kind": kind}
            if kind != "calendar":
                headers, rows = read_csv(text)
                mapping = guess_mapping(kind, headers)
                item.update(headers=headers, rows=len(rows), mapping=mapping, missing=missing_fields(kind, mapping))
            else:
                item.update(headers=[], rows=text.count("BEGIN:VEVENT"), mapping={}, missing=[])
            out.append(item)
        return out

    @app.post("/api/analyse")
    async def analyse_upload(
        files: list[UploadFile] = File(...),  # noqa: B008
        config: str = Form("{}"),
        business: str = Form(""),
    ) -> dict[str, Any]:
        settings = json.loads(config or "{}")
        loaded: dict[str, tuple[str, str, dict[str, str] | None]] = {}
        for f in files:
            text = (await f.read(MAX_BYTES + 1)).decode("utf-8", errors="replace")
            if len(text) > MAX_BYTES:
                raise HTTPException(413, f"{f.filename} is larger than 20 MB")
            name = f.filename or f"file{len(loaded)}"
            chosen = settings.get(name, {})
            kind = chosen.get("kind") or detect_kind(name, text)
            mapping = chosen.get("mapping") or None
            if kind != "calendar":
                headers, _ = read_csv(text)
                mapping = mapping or guess_mapping(kind, headers)
                if missing := missing_fields(kind, mapping):
                    raise HTTPException(400, f"{name}: choose the columns for {', '.join(missing)}")
            loaded[name] = (kind, text, mapping)
        return run(loaded, business)

    @app.post("/api/sample")
    def sample() -> dict[str, Any]:
        files = {}
        for name in ("emails.csv", "tickets.csv", "calendar.ics", "activity.csv"):
            text = (SAMPLE / name).read_text(encoding="utf-8")
            files[name] = (detect_kind(name, text), text, None)
        return run(files, "Acme Plumbing")

    @app.post("/api/session/{sid}/minutes")
    def minutes(sid: str, update: MinutesUpdate) -> dict[str, Any]:
        s = get(sid)
        for value in update.minutes.values():
            if not 0 < value <= 600:
                raise HTTPException(400, "minutes per task must be between 0 and 600")
        rank(s.analysis.opportunities, update.minutes)
        saved = {o.id: o.hours_saved_per_month for o in s.analysis.opportunities}
        for p in s.proposals:
            p.hours_saved_per_month = saved[p.opportunity]
        return payload(sid, s)

    @app.get("/api/session/{sid}/report.html")
    def report_html(sid: str) -> Response:
        s = get(sid)
        html = render_html(s.analysis, s.proposals, s.business)
        return Response(
            html,
            media_type="text/html",
            headers={"Content-Disposition": 'attachment; filename="automation-report.html"'},
        )

    @app.get("/api/session/{sid}/report.md")
    def report_md(sid: str) -> Response:
        s = get(sid)
        return Response(
            render_markdown(s.analysis, s.proposals, s.business),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="automation-report.md"'},
        )

    @app.get("/api/session/{sid}/workflow/{oid}.json")
    def workflow(sid: str, oid: str) -> JSONResponse:
        s = get(sid)
        o = next((x for x in s.analysis.opportunities if x.id == oid), None)
        if o is None:
            raise HTTPException(404, "no such opportunity")
        p = next(x for x in s.proposals if x.opportunity == oid)
        name = f"{oid}-{slug(p.title)}.json"
        return JSONResponse(build_workflow(o, p), headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/session/{sid}/workflows.zip")
    def workflows_zip(sid: str) -> Response:
        s = get(sid)
        by_id = {p.opportunity: p for p in s.proposals}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for o in s.analysis.opportunities[:5]:
                p = by_id[o.id]
                z.writestr(f"{o.id}-{slug(p.title)}.json", json.dumps(build_workflow(o, p), indent=2))
        return Response(
            buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="n8n-workflows.zip"'},
        )

    return app


app = create_app()
