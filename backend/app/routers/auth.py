from fastapi import APIRouter, Depends, HTTPException

from app.application import AccessControlService, InvalidCredentialsError, InvalidUserTokenError, UserAlreadyExistsError
from app.dependencies import get_access_control_service
from app.schemas import AuthMeResponse, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse

router = APIRouter()


@router.post("/auth/register", response_model=RegisterResponse)
def register(
    payload: RegisterRequest,
    service: AccessControlService = Depends(get_access_control_service),
) -> RegisterResponse:
    try:
        user = service.register_user(name=payload.name, email=payload.email, password=payload.password)
    except UserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Email already registered.")

    identity = service.resolve_identity(anonymous_fingerprint=None, user_token=user.token)
    return RegisterResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        user_token=user.token,
        quota_remaining=service.get_remaining_quota(identity),
        quota_limit=identity.quota_limit,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    service: AccessControlService = Depends(get_access_control_service),
) -> LoginResponse:
    try:
        user = service.authenticate_user(email=payload.email, password=payload.password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    identity = service.resolve_identity(anonymous_fingerprint=None, user_token=user.token)
    return LoginResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        user_token=user.token,
        quota_remaining=service.get_remaining_quota(identity),
        quota_limit=identity.quota_limit,
    )


@router.get("/auth/me", response_model=AuthMeResponse)
def me(
    user_token: str,
    service: AccessControlService = Depends(get_access_control_service),
) -> AuthMeResponse:
    try:
        user = service.get_user_by_token(user_token=user_token)
    except InvalidUserTokenError:
        raise HTTPException(status_code=401, detail="Invalid user token.")

    identity = service.resolve_identity(anonymous_fingerprint=None, user_token=user_token)
    return AuthMeResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        quota_remaining=service.get_remaining_quota(identity),
        quota_limit=identity.quota_limit,
    )
