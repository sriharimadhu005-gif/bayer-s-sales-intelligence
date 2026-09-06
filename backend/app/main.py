"""
Horeca Sales Intelligence — FastAPI Application.

Endpoints:
  GET  /api/health
  GET  /api/meta/routes
  GET  /api/meta/skus?branch=coffee|tea|others
  GET  /api/meta/customers?route_ids=1,3
  POST /api/chat
  POST /api/reports
"""
import os
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import FastAPI, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from .db import query
from .chat import chat as chat_engine
from . import memory as mem
from .reports import generate_excel, generate_pdf, generate_excel_from_spec, fetch_report_rows, fetch_financial_rows
from . import report_spec as report_spec_module
from . import bde_sop

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

app = FastAPI(title="Horeca Sales Intelligence API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ─────────────── Health ───────────────

@app.get("/api/health")
def health():
    try:
        rows = query("SELECT 1 AS ok")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(e)})


# ─────────────── Metadata ───────────────

@app.get("/api/meta/routes")
def get_routes():
    """Return the 7 fixed routes."""
    return [{"route_id": i, "route_name": f"Route {i}"} for i in range(1, 8)]


@app.get("/api/meta/skus")
def get_skus(branch: str | None = Query(None)):
    """
    Return SKUs from rate_cards with branch classification.
    Branch mapping:
      coffee  → category ILIKE '%coffee%' OR '%pure coffee%' OR '%filter%' OR '%instant%'
      tea     → category ILIKE '%tea%'
      others  → everything else (Badam Powder, Puliogare, Rava Idli, Cups, etc.)
    """
    rows = query("""
        SELECT DISTINCT ON (LOWER(TRIM(sku_name)))
            id AS sku_id,
            sku_name,
            category
        FROM rate_cards
        WHERE sku_name IS NOT NULL AND category IS NOT NULL
        ORDER BY LOWER(TRIM(sku_name)), id
    """)

    skus = []
    for r in rows:
        cat = (r.get("category") or "").lower()
        if "coffee" in cat or "filter" in cat or "instant" in cat or "chicory" in cat or "decoction" in cat:
            b = "coffee"
        elif "tea" in cat:
            b = "tea"
        else:
            b = "others"

        if branch and b != branch:
            continue

        skus.append({
            # This is a database identifier, not the transient position in the
            # response list.  Report queries resolve it back to the SKU name.
            "sku_id": r["sku_id"],
            "sku_name": r["sku_name"],
            "branch": b,
        })

    return skus


@app.get("/api/meta/customers")
def get_customers(route_ids: str = Query("")):
    """Return customers for given route IDs (comma-separated)."""
    if not route_ids.strip():
        return []

    ids = [int(x.strip()) for x in route_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return []

    placeholders = ", ".join(["%s"] * len(ids))
    rows = query(
        f"SELECT customer_id, name FROM customers WHERE route_number IN ({placeholders}) ORDER BY name",
        ids,
    )

    return [{"customer_id": r["customer_id"], "canonical_name": r["name"]} for r in rows]


# ─────────────── Chat ───────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    result = await chat_engine(req.message, req.conversation_id)
    return result


@app.delete("/api/chat/{conversation_id}")
async def delete_conversation(conversation_id: str = Path(..., description="Conversation ID to delete")):
    """Clear conversation memory for a chat session (used by 'New Chat' button)."""
    deleted = mem.delete_conversation(conversation_id)
    return {"deleted": deleted, "conversation_id": conversation_id}


@app.get("/api/chat/{conversation_id}/download-report/{report_id}")
async def download_chat_report(
    conversation_id: str = Path(..., description="Conversation ID"),
    report_id: str = Path(..., description="Report ID"),
):
    """Download an Excel report generated from conversation memory."""
    report_data = mem.get_conversation_report(conversation_id, report_id)
    if not report_data:
        return JSONResponse(
            status_code=404,
            content={"status": "not_found", "message": "Report expired or not found."},
        )
    file_bytes, filename = report_data
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'
        },
    )


# ─────────────── Reports ───────────────

class ReportRequest(BaseModel):
    date_from: str
    date_to: str
    days: list[str] | None = None
    route_ids: list[int] | None = None
    branches: list[str] | None = None
    sku_ids: list[int] | None = None
    customer_ids: list[str] | None = None
    generate_chart: bool = False
    chart_type: str | None = None
    output_format: str = "excel"
    notes: str | None = None


@app.post("/api/reports")
async def report_endpoint(req: ReportRequest):
    if req.output_format == "pdf":
        data, err = generate_pdf(
            req.date_from, req.date_to, req.days,
            req.route_ids, req.branches, req.sku_ids,
            req.customer_ids, req.notes,
        )
        if err:
            return JSONResponse(content={"status": "no_data", "message": err})
        filename = f"sales-report-{req.date_from.replace('/', '-')}.pdf"
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'},
        )
    else:
        # ── Canonical BDE Report path ──
        if req.notes and bde_sop.is_bde_report_request(req.notes):
            route_data = bde_sop.extract_bde_report_data()
            data = bde_sop.build_canonical_bde_workbook(route_data, sheet_title="Performance Report")
            filename = f"BDE_Performance_Report_{req.date_to.replace('/', '-')}.xlsx"
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'},
            )

        # ── AI-driven path: notes field is a natural language instruction ──
        if req.notes and req.notes.strip():
            # 1. Fetch data once (shared by spec builder and workbook generator)
            rows = fetch_report_rows(
                req.date_from, req.date_to, req.days,
                req.route_ids, req.branches, req.sku_ids, req.customer_ids,
            )
            if not rows:
                return JSONResponse(content={"status": "no_data", "message": "No data found for the selected filters."})

            fin_rows = fetch_financial_rows(
                req.date_from, req.date_to, req.route_ids, req.customer_ids,
            )

            # 2. Ask the LLM to interpret the instruction and produce a ReportSpec
            spec = await report_spec_module.build_spec(rows, fin_rows, req)

            # 3. Build the workbook from the spec
            data, err = generate_excel_from_spec(
                rows, fin_rows, spec,
                req.date_from, req.date_to, req,
            )
        else:
            # ── Default path: standard 4-tab layout, no LLM call ──
            data, err = generate_excel(
                req.date_from, req.date_to, req.days,
                req.route_ids, req.branches, req.sku_ids,
                req.customer_ids, req.notes,
            )

        if err:
            return JSONResponse(content={"status": "no_data", "message": err})
        filename = f"sales-report-{req.date_from.replace('/', '-')}.xlsx"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'},
        )


@app.get("/api/reports/bde")
async def get_bde_report(as_of_date: str | None = Query(None)):
    """Generate and download the canonical BDE Performance Report in Excel (.xlsx)."""
    route_data = bde_sop.extract_bde_report_data(report_date=as_of_date)
    sheet_name = f"Report {as_of_date}" if as_of_date else "Performance Report"
    data = bde_sop.build_canonical_bde_workbook(route_data, sheet_title=sheet_name)
    filename = f"BDE_Performance_Report_{as_of_date or 'latest'}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'},
    )


# ─────────────── Serve Built Frontend (Single Unified URL) ───────────────
frontend_dist = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
)
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

