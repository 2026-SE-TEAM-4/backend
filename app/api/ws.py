"""WebSocket 엔드포인트."""

import asyncio
import json
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from sqlalchemy import select

from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models.notification import Notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws")


@router.websocket("/notifications")
async def ws_notifications(
    websocket: WebSocket,
    token: str = Query(...),
) -> None:
    """실시간 알림 채널 [UC03-a, UC03-d].

    연결 시 미읽음 알림을 즉시 전송하고, 이후 Redis pub/sub으로 신규 알림을 중계한다.
    인증 실패 시 4001 코드로 즉시 종료한다.
    """
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # 미읽음 알림을 접속 직후 전송한다
    async with SessionLocal() as db:
        rows = await db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .order_by(Notification.created_at.asc())
        )
        for notification in rows.scalars().all():
            await websocket.send_text(_serialize(notification))

    # Redis pub/sub으로 신규 알림을 중계한다
    redis = get_redis()
    pubsub = redis.pubsub()
    channel = f"notifications:{user_id}"
    await pubsub.subscribe(channel)

    redis_task = asyncio.create_task(_relay_redis(pubsub, websocket))
    ws_task = asyncio.create_task(_wait_disconnect(websocket))
    try:
        # 둘 중 하나라도 끝나면(disconnect or Redis 오류) 나머지를 정리한다
        done, pending = await asyncio.wait(
            [redis_task, ws_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        # CancelledError를 삼키고 완전히 종료될 때까지 기다린다
        await asyncio.gather(*pending, return_exceptions=True)
        # 완료된 태스크에서 발생한 예외를 로깅한다(WebSocketDisconnect 제외)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.warning("ws_notifications 태스크 종료: %s", exc)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def _relay_redis(pubsub, websocket: WebSocket) -> None:
    """Redis 채널 메시지를 WebSocket으로 포워딩한다."""
    async for message in pubsub.listen():
        if message["type"] == "message":
            await websocket.send_text(message["data"])


async def _wait_disconnect(websocket: WebSocket) -> None:
    """클라이언트 disconnect를 감지한다. 메시지 내용은 사용하지 않는다."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


def _serialize(notification: Notification) -> str:
    return json.dumps(
        {
            "id": notification.id,
            "type": notification.type,
            "message": notification.message,
            "payload": notification.payload,
            "created_at": notification.created_at.isoformat(),
        },
        ensure_ascii=False,
    )
