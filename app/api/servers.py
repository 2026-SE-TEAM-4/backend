"""서버 관리 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_session, require_admin
from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.servers import (
    MaintenanceCreate,
    MaintenanceCreateResponse,
    ServerAlternativeResponse,
    ServerCreate,
    ServerCreateResponse,
    ServerDeleteResponse,
    ServerDetailResponse,
    ServerListResponse,
    ServerSort,
)
from app.services import servers as server_service

router = APIRouter(prefix="/servers", tags=["servers"])


def _raise_api_error(error: Exception) -> None:
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise error


@router.post("", response_model=ServerCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    data: ServerCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(require_admin)],
) -> ServerCreateResponse:
    try:
        return await server_service.create_server(session, data)
    except ConflictError as error:
        _raise_api_error(error)
        raise


@router.get("", response_model=ServerListResponse)
async def list_servers(
    session: Annotated[AsyncSession, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    status_value: Annotated[str | None, Query(alias="status")] = None,
    group_name: Annotated[str | None, Query(alias="group")] = None,
    scope_group_name: Annotated[str | None, Header(alias="X-Group-Name")] = None,
    sort: Annotated[ServerSort, Query()] = "id",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ServerListResponse:
    return await server_service.list_servers(
        session=session,
        status=status_value,
        group_name=group_name,
        user_role=auth.role,
        scope_group_name=scope_group_name,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/alternatives", response_model=ServerAlternativeResponse)
async def list_alternatives(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(get_auth_context)],
    server_id: Annotated[int, Query(alias="serverId")],
) -> ServerAlternativeResponse:
    try:
        return await server_service.list_alternative_servers(session, server_id)
    except NotFoundError as error:
        _raise_api_error(error)
        raise


@router.get("/{server_id}", response_model=ServerDetailResponse)
async def get_server(
    server_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(get_auth_context)],
) -> ServerDetailResponse:
    try:
        return await server_service.get_server(session, server_id)
    except NotFoundError as error:
        _raise_api_error(error)
        raise


@router.delete("/{server_id}", response_model=ServerDeleteResponse)
async def delete_server(
    server_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(require_admin)],
) -> ServerDeleteResponse:
    try:
        return await server_service.soft_delete_server(session, server_id)
    except (ConflictError, NotFoundError) as error:
        _raise_api_error(error)
        raise


@router.post(
    "/{server_id}/maintenances",
    response_model=MaintenanceCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_maintenance(
    server_id: int,
    data: MaintenanceCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> MaintenanceCreateResponse:
    try:
        return await server_service.create_maintenance(session, server_id, data, auth.user_id)
    except (ConflictError, NotFoundError) as error:
        _raise_api_error(error)
        raise
