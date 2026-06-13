"""메트릭 히스토리 읽기 전용 서비스(프론트 시각화용, §5).

server_metric 을 윈도우 기준으로 읽어 차트가 가볍게 그려지도록 시간 버킷으로
평균을 내려준다. 모델·스키마 변경 없이 기존 테이블만 조회한다.

- 서버별 시계열: GET /servers/{id}/metrics
- 플릿 히트맵(서버×시간): GET /ops/metrics/heatmap
- 서버별 최근 이상: GET /servers/{id}/anomalies
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnomalyRecord, Server, ServerMetric

# 허용 윈도우 → timedelta. 잘못된 값은 라우터에서 400 으로 막는다.
_WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
}

# 히트맵 셀에 쓸 수 있는 메트릭 종류. 키는 쿼리 값, 값은 ServerMetric 컬럼명.
_HEATMAP_METRICS: dict[str, str] = {
    "CPU": "cpu_usage",
    "MEM": "mem_usage",
    "GPU": "gpu_usage",
    "NET": "net_usage",
}

# 차트가 가볍게 유지되도록 버킷 상한을 둔다.
_SERIES_MAX_BUCKETS = 90
_HEATMAP_MAX_BUCKETS = 24


def window_options() -> list[str]:
    """허용 윈도우 키 목록(라우터의 400 메시지에 쓴다)."""
    return list(_WINDOWS)


def heatmap_metric_options() -> list[str]:
    """허용 히트맵 메트릭 목록(라우터의 400 메시지에 쓴다)."""
    return list(_HEATMAP_METRICS)


def _resolve_window(window: str) -> timedelta:
    """윈도우 문자열을 timedelta 로. 모르는 값이면 KeyError."""
    return _WINDOWS[window]


def _bucket_index(ts: datetime, start: datetime, step: timedelta) -> int:
    """수집 시각이 몇 번째 버킷에 속하는지 계산한다."""
    return int((ts - start).total_seconds() // step.total_seconds())


def _as_utc(ts: datetime) -> datetime:
    """tz 없는 값이 섞여도 UTC 기준으로 다루도록 보정한다."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


async def build_server_series(
    db: AsyncSession, server_id: int, window: str, max_buckets: int = _SERIES_MAX_BUCKETS
) -> dict:
    """서버 1대의 사용률 시계열을 버킷 평균으로 만든다.

    단일 쿼리로 윈도우 안의 메트릭을 읽고 파이썬에서 균등 버킷에 평균낸다(이 규모면 충분).
    데이터가 없으면 points 는 빈 배열이다. gpu 는 미탑재 노드에서 null 일 수 있다.
    """
    span = _resolve_window(window)
    now = datetime.now(tz=timezone.utc)
    start = now - span
    step = span / max_buckets

    rows = (
        await db.execute(
            select(
                ServerMetric.collected_at,
                ServerMetric.cpu_usage,
                ServerMetric.mem_usage,
                ServerMetric.gpu_usage,
                ServerMetric.net_usage,
            )
            .where(
                ServerMetric.server_id == server_id,
                ServerMetric.collected_at >= start,
            )
            .order_by(ServerMetric.collected_at)
        )
    ).all()

    # 버킷별 합계·개수를 모은다. gpu 는 null 이 섞이므로 따로 센다.
    buckets: dict[int, dict] = {}
    for collected_at, cpu, mem, gpu, net in rows:
        idx = _bucket_index(_as_utc(collected_at), start, step)
        if idx < 0 or idx >= max_buckets:
            continue
        agg = buckets.setdefault(
            idx, {"cpu": 0.0, "mem": 0.0, "net": 0.0, "gpu": 0.0, "n": 0, "gpu_n": 0}
        )
        agg["cpu"] += cpu
        agg["mem"] += mem
        agg["net"] += net
        agg["n"] += 1
        if gpu is not None:
            agg["gpu"] += gpu
            agg["gpu_n"] += 1

    points = []
    for idx in sorted(buckets):
        agg = buckets[idx]
        bucket_ts = start + step * idx
        points.append(
            {
                "ts": bucket_ts,
                "cpu": round(agg["cpu"] / agg["n"], 1),
                "mem": round(agg["mem"] / agg["n"], 1),
                "net": round(agg["net"] / agg["n"], 1),
                "gpu": round(agg["gpu"] / agg["gpu_n"], 1) if agg["gpu_n"] else None,
            }
        )

    return {"server_id": server_id, "window": window, "points": points}


async def build_heatmap(
    db: AsyncSession, metric: str, window: str, max_buckets: int = _HEATMAP_MAX_BUCKETS
) -> dict:
    """서버×시간 히트맵. cells[i][j] = 서버 i 의 j 버킷 평균(0~100, 없으면 null).

    삭제되지 않은 서버를 행으로 두고, 윈도우를 균등 버킷으로 나눠 선택 메트릭의 평균을 채운다.
    한 번의 메트릭 쿼리로 전 서버 데이터를 읽고 파이썬에서 집계한다.
    """
    span = _resolve_window(window)
    now = datetime.now(tz=timezone.utc)
    start = now - span
    step = span / max_buckets
    column = getattr(ServerMetric, _HEATMAP_METRICS[metric])

    server_rows = (
        await db.execute(
            select(Server.id, Server.name)
            .where(Server.deleted_at.is_(None))
            .order_by(Server.id)
        )
    ).all()
    server_ids = [row[0] for row in server_rows]
    server_names = [row[1] for row in server_rows]
    row_of = {server_id: i for i, server_id in enumerate(server_ids)}

    metric_rows = (
        await db.execute(
            select(ServerMetric.server_id, ServerMetric.collected_at, column).where(
                ServerMetric.collected_at >= start,
                column.is_not(None),
            )
        )
    ).all()

    # (행, 열) 별 합계·개수. 누락 셀은 null 로 남긴다.
    sums: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for server_id, collected_at, value in metric_rows:
        row = row_of.get(server_id)
        if row is None:
            continue
        col = _bucket_index(_as_utc(collected_at), start, step)
        if col < 0 or col >= max_buckets:
            continue
        key = (row, col)
        sums[key] = sums.get(key, 0.0) + value
        counts[key] = counts.get(key, 0) + 1

    cells: list[list[float | None]] = []
    for row in range(len(server_ids)):
        line: list[float | None] = []
        for col in range(max_buckets):
            count = counts.get((row, col))
            line.append(round(sums[(row, col)] / count, 1) if count else None)
        cells.append(line)

    buckets = [start + step * col for col in range(max_buckets)]
    return {
        "metric": metric,
        "server_ids": server_ids,
        "server_names": server_names,
        "buckets": buckets,
        "cells": cells,
    }


async def list_recent_anomalies(db: AsyncSession, server_id: int, window: str) -> list[AnomalyRecord]:
    """서버 1대의 최근 이상 목록(최신순). anomaly_record 를 그대로 읽는다."""
    span = _resolve_window(window)
    start = datetime.now(tz=timezone.utc) - span
    rows = (
        await db.execute(
            select(AnomalyRecord)
            .where(
                AnomalyRecord.server_id == server_id,
                AnomalyRecord.detected_at >= start,
            )
            .order_by(AnomalyRecord.detected_at.desc())
        )
    ).scalars().all()
    return list(rows)
