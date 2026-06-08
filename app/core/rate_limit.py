"""비정상 접근 감지·일시 잠금 미들웨어."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.database import SessionLocal
from app.models import User


class RateLimitMiddleware(BaseHTTPMiddleware):
    """짧은 시간 과다 요청을 막고, 식별된 사용자는 15분 잠근다."""

    def __init__(self, app, limit: int = 120, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = timedelta(seconds=window_seconds)
        self.requests: dict[str, deque[datetime]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        current_time = datetime.now(timezone.utc)
        user_id = request.headers.get("X-User-Id")
        key = f"user:{user_id}" if user_id else f"ip:{request.client.host if request.client else 'unknown'}"

        if user_id and user_id.isdigit():
            try:
                async with SessionLocal() as session:
                    user = await session.get(User, int(user_id))
                    if user and user.locked_until and user.locked_until > current_time:
                        return JSONResponse(
                            status_code=423,
                            content={"detail": "계정이 일시 잠금 상태입니다."},
                        )
            except Exception:
                pass

        history = self.requests[key]
        while history and current_time - history[0] > self.window:
            history.popleft()
        history.append(current_time)

        if len(history) > self.limit:
            if user_id and user_id.isdigit():
                try:
                    async with SessionLocal() as session:
                        user = await session.get(User, int(user_id))
                        if user:
                            user.locked_until = current_time + timedelta(minutes=15)
                            await session.commit()
                except Exception:
                    pass
            return JSONResponse(
                status_code=429,
                content={"detail": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."},
            )

        return await call_next(request)
