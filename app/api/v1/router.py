from fastapi import APIRouter

from app.api.v1.endpoints import auth, companies, leads, me, workspace

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(workspace.router)
api_router.include_router(leads.router)
api_router.include_router(companies.router)
