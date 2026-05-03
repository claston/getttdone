import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException

from app.application import AccessControlService, InvalidUserTokenError
from app.dependencies import get_access_control_service
from app.schemas import (
    AdminActivatePlanRequest,
    AdminActivatePlanResponse,
    PlanCatalogItem,
    PlanCatalogResponse,
)

router = APIRouter()


@router.get("/plans", response_model=PlanCatalogResponse)
def list_plans(
    access_control_service: AccessControlService = Depends(get_access_control_service),
) -> PlanCatalogResponse:
    items = access_control_service.list_public_plans()
    return PlanCatalogResponse(items=[PlanCatalogItem(**item) for item in items])


@router.post("/admin/plans/activate", response_model=AdminActivatePlanResponse)
def activate_user_plan(
    payload: AdminActivatePlanRequest,
    x_admin_token: str | None = Header(default=None),
    access_control_service: AccessControlService = Depends(get_access_control_service),
) -> AdminActivatePlanResponse:
    expected_admin_token = os.getenv("PLANS_ADMIN_TOKEN", "").strip()
    if not expected_admin_token:
        raise HTTPException(status_code=503, detail="Admin plans endpoint is not configured.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected_admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    try:
        activated = access_control_service.activate_user_plan(
            user_id=payload.user_id.strip(),
            plan_code=payload.plan_code.strip(),
        )
    except InvalidUserTokenError:
        raise HTTPException(status_code=404, detail="User not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return AdminActivatePlanResponse(
        user_id=payload.user_id.strip(),
        plan_code=str(activated["code"]),
        plan_name=str(activated["name"]),
        plan_version=int(activated["version"]),
        quota_mode=str(activated["quota_mode"]),
        quota_limit=int(activated["quota_limit"]),
    )
