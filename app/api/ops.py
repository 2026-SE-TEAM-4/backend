"""운영 조회 API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_session, require_admin
from app.schemas.ops import AvailabilityResponse, OpsDashboardResponse
from app.services import ops as ops_service

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/dashboard", response_model=OpsDashboardResponse)
async def get_dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(require_admin)],
) -> OpsDashboardResponse:
    return await ops_service.get_dashboard(session)


@router.get("/availabilty", response_model=AvailabilityResponse)
async def get_availability_with_typo(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(require_admin)],
) -> AvailabilityResponse:
    return await ops_service.get_availability(session)
