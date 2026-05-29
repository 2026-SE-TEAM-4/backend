# backend 디렉토리 구조

본 레포는 FastAPI 기반 API 서버와 APScheduler 잡 컨테이너를 한 코드베이스에서
운영한다. 두 프로세스는 동일 이미지를 공유하며 entrypoint만 다르다.

파일은 기능 추가에 따라 계속 바뀌지만, 아래 디렉토리 구조는 가능한 고정한다.
새 파일을 추가하기 전에 어느 폴더에 속하는지 본 문서로 확인한다.
구조 자체를 바꿀 필요가 생기면 코드보다 먼저 본 문서를 갱신한다.

```text
backend/
├── app/                       # 애플리케이션 패키지 (모든 코드는 이 안)
│   ├── main.py                # FastAPI 앱 entrypoint
│   ├── scheduler.py           # APScheduler entrypoint (별도 컨테이너)
│   ├── config.py              # 환경 설정 (Pydantic Settings)
│   ├── database.py            # SQLAlchemy 엔진 / 세션
│   ├── api/                   # 도메인별 라우터 (1 도메인 = 1 파일 권장)
│   │                          # auth, users, teams, servers,
│   │                          # reservations, approvals, metrics ...
│   ├── models/                # SQLAlchemy ORM 모델
│   ├── schemas/               # Pydantic 입출력 스키마
│   ├── services/              # 비즈니스 로직 (라우터에서 호출)
│   ├── jobs/                  # APScheduler 잡 (UC14, 15, 16, 18, 19)
│   └── core/                  # 보안·예외·공통 의존성 (cross-cutting)
├── alembic/                   # DB 마이그레이션
│   └── versions/              # 생성된 리비전 파일
├── tests/
│   ├── unit/                  # 순수 로직 (DB 미접속)
│   └── integration/           # DB·Redis 포함 (testcontainers)
├── scripts/                   # 운영 스크립트 (seed, dump 등)
├── pyproject.toml             # uv 기반 의존성·도구 설정
├── alembic.ini                # alembic 설정
├── Dockerfile                 # api / scheduler 공통 이미지
├── docker-compose.yml         # api + scheduler + postgres + redis
├── README.md
├── CLAUDE.md                  # 작업 시작 시 참조
├── tree.md                    # 본 파일
└── rule.md                    # 코딩 규칙
```

## 레이어 책임 요약

- `api/` 는 입력 검증과 응답 직렬화만 담당한다. 로직은 `services/` 로 넘긴다.
- `services/` 는 도메인 로직을 가진다. ORM 객체를 직접 다루되, FastAPI 의존성은
  알지 않는다 (테스트 용이성).
- `models/` 와 `schemas/` 는 의도적으로 분리한다. ORM 모델을 그대로 응답으로
  내보내지 않는다 (직렬화·필드 제어를 위함).
- `jobs/` 는 `services/` 를 재사용한다. 잡 안에서 ORM·외부 호출을 직접 짜지 않는다.
- `core/` 는 여러 도메인이 공유하는 코드만 둔다. 한 도메인에만 쓰이면 해당
  도메인 폴더로 옮긴다.
