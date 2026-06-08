"""서버 사용률 수집·이상 징후 탐지 잡."""

from app.services import monitoring as monitoring_service


async def collect_metrics() -> None:
    await monitoring_service.collect_metrics()


async def detect_anomalies() -> None:
    await monitoring_service.detect_anomalies()
