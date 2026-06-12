"""FastAPI 앱 진입점.

헬스 체크와 인증 라우터(회원가입·로그인)를 제공한다. 도메인 라우터는
기능 구현에 따라 app/api 아래에 추가한다(tree.md).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    approval_requests,
    auth,
    notifications,
    ops,
    reservations,
    servers,
    teams,
    ws,
)

# 주기 잡은 스케줄러 컨테이너(app/scheduler.py)가 단독으로 돌린다. API 프로세스는
# 잡을 등록하지 않는다(잡 이중 실행 방지). 잡 목록은 app/jobs/scheduling.py 참조.

app = FastAPI(title="서버 예약/할당 관리 시스템 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(reservations.router)
app.include_router(approval_requests.router)
app.include_router(notifications.router)
app.include_router(teams.router)
app.include_router(ws.router)
app.include_router(ops.router)
app.include_router(servers.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
