"""유휴 서버 감지·자동 회수 잡."""

from app.services import monitoring as monitoring_service


async def reclaim_idle_servers() -> None:
    await monitoring_service.reclaim_idle_servers()
