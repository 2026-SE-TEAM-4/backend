"""FastAPI 앱 진입점.

헬스 체크와 인증 라우터(회원가입·로그인)를 제공한다. 도메인 라우터는
기능 구현에 따라 app/api 아래에 추가한다(tree.md).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth

app = FastAPI(title="서버 예약/할당 관리 시스템 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
