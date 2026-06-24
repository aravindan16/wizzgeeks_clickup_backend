"""Report generation + Excel/PDF export endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, get_report_service, make_actor, require
from app.schemas.report import REPORT_TYPES, ReportData
from app.services.export_service import to_excel, to_pdf
from app.services.report_service import ReportFilters, ReportService

router = APIRouter()

ServiceDep = Annotated[ReportService, Depends(get_report_service)]

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"


def _filters(date, date_from, date_to, ref_date, user_id, project_id, manager_id, status, priority):
    return ReportFilters(
        date=date, date_from=date_from, date_to=date_to, ref_date=ref_date,
        user_id=user_id, project_id=project_id, manager_id=manager_id,
        status=status, priority=priority,
    )


@router.get("/types")
async def report_types(_: Annotated[CurrentUser, Depends(require("report.view.self"))]):
    return {"types": REPORT_TYPES}


@router.get("", response_model=ReportData)
async def generate_report(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("report.view.self"))],
    type: str = Query(..., description="Report type"),
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    ref_date: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    manager_id: str | None = None,
    status: str | None = None,
    priority: str | None = None,
):
    filters = _filters(date, date_from, date_to, ref_date, user_id, project_id, manager_id, status, priority)
    return await service.build(type, filters, make_actor(actor, request))


@router.get("/export")
async def export_report(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("report.view.self"))],
    type: str = Query(...),
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    ref_date: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    manager_id: str | None = None,
    status: str | None = None,
    priority: str | None = None,
):
    filters = _filters(date, date_from, date_to, ref_date, user_id, project_id, manager_id, status, priority)
    report = await service.build(type, filters, make_actor(actor, request))

    if format == "pdf":
        content = to_pdf(report)
        media, ext = PDF_MIME, "pdf"
    else:
        content = to_excel(report)
        media, ext = XLSX_MIME, "xlsx"

    filename = f"{type}_{report['generated_at'][:10]}.{ext}"

    def _iter():
        yield content

    return StreamingResponse(
        _iter(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
