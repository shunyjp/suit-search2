"""Admin routes – reports, recheck, health (Phase 2+ stub)."""

from __future__ import annotations

from fastapi import APIRouter

from app.workflows.report_job import run_report_job

router = APIRouter()


@router.get("/report")
async def get_report() -> dict[str, str]:
    """Phase 2+ stub."""
    report = await run_report_job()
    return {"report": report}
