from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.templates import router as templates_router
from app.api.v1.documents import router as documents_router
from app.api.v1.extractions import router as extractions_router
from app.api.v1.system import router as system_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(templates_router)
api_router.include_router(documents_router)
api_router.include_router(extractions_router)
api_router.include_router(system_router)
