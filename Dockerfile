# 서버 예약/할당 관리 시스템 백엔드.
# api 서버와 스케줄러가 이 동일 이미지를 공유하고, compose에서 커맨드만 다르게 띄운다.
FROM python:3.12-slim

# uv (의존성 관리)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 가상환경은 소스 밖(/opt/venv)에 둔다. 개발 시 소스를 /code에 볼륨 마운트해도
# 가상환경이 가려지지 않게 하기 위함이다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONPATH=/code \
    PYTHONUNBUFFERED=1

WORKDIR /code

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 애플리케이션 코드
COPY . .

# 비루트 사용자
RUN useradd -m appuser && chown -R appuser:appuser /code /opt/venv
USER appuser

ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000

# 기본 커맨드. compose에서 api/scheduler 각각 덮어쓴다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
