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

    # 인증 (구현은 후속 단계)
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_min: int = 60

    # 스케줄러 / 서버풀 메트릭 수집 (수집 구현은 후속 단계)
    scheduler_interval_sec: int = 60
    serverpool_host: str = "host.docker.internal"
    serverpool_base_port: int = 9101


settings = Settings()
