"""FastAPI 앱 진입점.

헬스 체크와 인증 라우터(회원가입·로그인)를 제공한다. 도메인 라우터는
기능 구현에 따라 app/api 아래에 추가한다(tree.md).
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import approval_requests, auth, notifications, reservations, teams, ws
from app.jobs.approval_jobs import auto_reject_timed_out_requests
from app.jobs.reservation_jobs import process_reservation_transitions


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    # UC16: 1분 주기로 예약 만료·사용 시작 자동 전이
    scheduler.add_job(process_reservation_transitions, "interval", minutes=1)
    # UC17: 1분 주기로 72시간 초과 PENDING 승인 요청 자동 거절
    scheduler.add_job(auto_reject_timed_out_requests, "interval", minutes=1)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="서버 예약/할당 관리 시스템 API", lifespan=lifespan)

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
