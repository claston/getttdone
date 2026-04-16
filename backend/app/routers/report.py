from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.application import AnalysisNotFoundError, ReportService
from app.dependencies import get_report_service

router = APIRouter()


@router.get("/report/{analysis_id}")
def get_report(
    analysis_id: str,
    service: ReportService = Depends(get_report_service),
) -> FileResponse:
    try:
        report_path = service.get_report_path(analysis_id)
    except AnalysisNotFoundError:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return FileResponse(
        path=report_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"gettdone_report_{analysis_id}.xlsx",
    )


@router.get("/reconcile-report/{analysis_id}")
def get_reconcile_report(
    analysis_id: str,
    file_format: Literal["xlsx", "csv"] = Query(default="xlsx", alias="format"),
    service: ReportService = Depends(get_report_service),
) -> FileResponse:
    try:
        report_path = service.get_reconcile_report_path(analysis_id=analysis_id, file_format=file_format)
    except AnalysisNotFoundError:
        raise HTTPException(status_code=404, detail="Analysis not found")

    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if file_format == "xlsx"
        else "text/csv; charset=utf-8"
    )
    filename = f"gettdone_reconcile_{analysis_id}.{file_format}"
    return FileResponse(path=report_path, media_type=media_type, filename=filename)


@router.get("/convert-report/{processing_id}")
def get_convert_report(
    processing_id: str,
    file_format: Literal["ofx", "csv"] = Query(default="ofx", alias="format"),
    service: ReportService = Depends(get_report_service),
) -> FileResponse:
    try:
        report_path = service.get_convert_report_path(processing_id, file_format=file_format)
    except AnalysisNotFoundError:
        raise HTTPException(status_code=404, detail="Analysis not found")

    media_type = "application/x-ofx" if file_format == "ofx" else "text/csv; charset=utf-8"
    return FileResponse(
        path=report_path,
        media_type=media_type,
        filename=f"gettdone_convert_{processing_id}.{file_format}",
    )
