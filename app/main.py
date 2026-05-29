"""FastAPI 앱 진입점.

현재는 헬스 체크만 제공한다. 도메인 라우터(api/)는 후속 단계에서 추가한다.
"""

from fastapi import FastAPI

app = FastAPI(title="서버 예약/할당 관리 시스템 API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
