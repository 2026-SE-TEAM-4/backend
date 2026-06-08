"""FastAPI 앱 진입점.

현재는 헬스 체크만 제공한다. 도메인 라우터(api/)는 후속 단계에서 추가한다.
"""

from fastapi import FastAPI

from app.api.ops import router as ops_router
from app.api.servers import router as servers_router
from app.api.users import router as users_router
from app.core.rate_limit import RateLimitMiddleware

app = FastAPI(title="서버 예약/할당 관리 시스템 API")

app.add_middleware(RateLimitMiddleware)

app.include_router(servers_router)
app.include_router(ops_router)
app.include_router(users_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
