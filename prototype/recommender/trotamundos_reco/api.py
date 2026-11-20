"""Capa HTTP (FastAPI). Montable en el backend existente con
`app.include_router(create_router(service, settings))` o standalone con create_app()."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from .auth import AuthError, Principal, issue_token, verify_token
from .config import Settings
from .db import Database, SqlStore
from .service import RecommenderService, utcnow


class FeedbackIn(BaseModel):
    feedback_id: str = Field(min_length=1, max_length=64)
    accommodation_id: int
    kind: Literal["accept", "reject", "rating"]
    rating: Optional[int] = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _rating_required(self):
        if self.kind == "rating" and self.rating is None:
            raise ValueError("rating es obligatorio cuando kind='rating'")
        return self


class ConstraintsIn(BaseModel):
    max_price_per_night: Optional[float] = Field(default=None, ge=0)
    min_stars: Optional[int] = Field(default=None, ge=1, le=5)
    zones: list = []
    types: list = []
    required_amenities: list = []


class DevTokenIn(BaseModel):
    sub: str = Field(min_length=1)
    role: Literal["user", "admin"] = "user"


def create_router(service: RecommenderService, settings: Settings) -> APIRouter:
    router = APIRouter()

    def principal(authorization: Optional[str] = Header(default=None)) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "falta el token Bearer")
        try:
            return verify_token(authorization[7:].strip(), settings.jwt_secret, utcnow())
        except AuthError as exc:
            raise HTTPException(401, str(exc))

    def guarded(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    # La identidad sale SIEMPRE del token; ningún endpoint de usuario recibe user_id.
    @router.get("/recommendations/me")
    def my_recommendations(p: Principal = Depends(principal)):
        return service.get_recommendations(p.sub)

    @router.post("/feedback")
    def feedback(body: FeedbackIn, p: Principal = Depends(principal)):
        return guarded(service.submit_feedback, p.sub, body.feedback_id,
                       body.accommodation_id, body.kind, body.rating)

    @router.get("/me/constraints")
    def get_constraints(p: Principal = Depends(principal)):
        return service.get_constraints(p.sub)

    @router.put("/me/constraints")
    def put_constraints(body: ConstraintsIn, p: Principal = Depends(principal)):
        return guarded(service.set_constraints, p.sub, body.model_dump())

    @router.get("/me/profile")
    def my_profile(p: Principal = Depends(principal)):
        return service.profile_view(p.sub)

    @router.get("/admin/users/{user_id}/profile")
    def admin_profile(user_id: str, p: Principal = Depends(principal)):
        return guarded(service.admin_view_profile, p, user_id)

    @router.get("/admin/audit")
    def admin_audit(limit: int = 100, p: Principal = Depends(principal)):
        return guarded(service.admin_audit_log, p, min(max(limit, 1), 500))

    if settings.dev_token_endpoint:
        @router.post("/dev/token")
        def dev_token(body: DevTokenIn):
            return {"token": issue_token(body.sub, body.role, settings.jwt_secret,
                                         settings.token_ttl_seconds, utcnow())}

    @router.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return router


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = RecommenderService(SqlStore(Database(settings.db_path)), settings)
    app = FastAPI(title="Trotamundos – Recomendaciones")
    app.include_router(create_router(service, settings))
    return app
