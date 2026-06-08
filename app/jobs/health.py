"""서버 건강 점수 산출 잡."""

from app.services import monitoring as monitoring_service


async def calculate_health_scores() -> None:
    await monitoring_service.calculate_health_scores()
