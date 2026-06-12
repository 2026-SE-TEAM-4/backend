"""애플리케이션 환경 설정.

값은 .env 또는 환경 변수에서 읽는다. 인증·수집 관련 값은 후속 단계에서 쓰이며
지금은 보관만 한다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"

    # 데이터베이스 / 캐시
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    redis_url: str = "redis://redis:6379/0"

    # 인증 (JWT 단일 액세스 토큰)
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_min: int = 60

    # 로그인 실패 잠금 (UC23). 카운트는 Redis, 잠금만 user.locked_until에 영속화한다.
    login_fail_max: int = 5  # 연속 실패 임계. 도달 시 계정 잠금
    login_fail_window_sec: int = 300  # 실패 카운트 집계 창(Redis TTL)
    login_lock_min: int = 15  # 잠금 지속(분). UC20과 동일 값

    # 스케줄러 / 서버풀 메트릭 수집 (수집 구현은 후속 단계)
    scheduler_interval_sec: int = 60
    serverpool_host: str = "host.docker.internal"
    serverpool_base_port: int = 9101

    # LLM 원인 요약 잡(F34/UC25). 키는 환경 변수로만 주입한다(절대 하드코딩 금지).
    # 비어 있으면 요약 잡은 경고만 남기고 조용히 건너뛴다(키 없이도 앱은 정상 동작).
    gemini_api_key: str = ""
    # 인시던트당 1회 요약에 쓰는 비용 효율적 현행 Gemini 모델(필요 시 환경 변수로 교체).
    gemini_model: str = "gemini-3.1-flash-lite"


settings = Settings()
