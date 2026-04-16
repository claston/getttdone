from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.application import AnalyzeService, InvalidFileContentError, UnsupportedFileTypeError
from app.dependencies import get_analyze_service
from app.schemas import ConvertResponse

MAX_CONVERT_FILE_SIZE_BYTES = 2 * 1024 * 1024

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(
    file: UploadFile = File(...),
    service: AnalyzeService = Depends(get_analyze_service),
) -> ConvertResponse:
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF.")

    data = await file.read()
    if len(data) > MAX_CONVERT_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 2MB.")

    try:
        analysis = service.analyze(filename=filename, raw_bytes=data)
    except UnsupportedFileTypeError:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF.")
    except InvalidFileContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ConvertResponse(
        processing_id=analysis.analysis_id,
        quota_remaining=None,
        quota_limit=None,
        analysis=analysis,
        mode="convert",
    )
