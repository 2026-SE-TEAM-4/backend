# backend

서버 예약/할당 관리 시스템의 **백엔드**. FastAPI API 서버와 APScheduler 스케줄러를
한 코드베이스(동일 이미지, 다른 entrypoint)로 운영한다.

> **현재 상태: 기초공사 단계.** 부팅·헬스 체크·DB 스키마까지만 구성돼 있다.
> 유스케이스 기능(라우터·서비스·잡), 인증(JWT), 테스트는 후속 단계다.
> 전체 설계는 `diagram-and-docs`의 설계 문서와 Notion 페이지를 참조한다.

## 구성

| 서비스 | 내용 | 포트 |
| --- | --- | --- |
| api | FastAPI + Uvicorn | 8000 |
| scheduler | APScheduler (별도 컨테이너, 동일 이미지) | - |
| postgres | PostgreSQL 16 | 5432 |
| redis | Redis 7 | 6379 |

## 빠른 시작

```bash
cp .env.example .env       # 필요하면 값 수정
docker compose up --build
```

- postgres·redis가 healthy 해진 뒤, api 컨테이너가 `alembic upgrade head`로 13개
  테이블을 만들고 uvicorn을 띄운다(마이그레이션은 api에서만 수행).
- 헬스 확인: `curl localhost:8000/health` → `{"status":"ok"}`
- 소스를 볼륨 마운트하고 `--reload`로 띄우므로 코드 수정이 즉시 반영된다.

## 환경 변수 (`.env`)

| 키 | 기본 | 설명 |
| --- | --- | --- |
| APP_ENV | dev | 환경 구분 |
| POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB | app / app / app | postgres 서비스 |
| DATABASE_URL | postgresql+asyncpg://app:app@postgres:5432/app | 앱 DB 접속 |
| REDIS_URL | redis://redis:6379/0 | 캐시/락 |
| JWT_SECRET / JWT_EXPIRE_MIN | dev-secret… / 60 | 인증(후속) |
| SCHEDULER_INTERVAL_SEC | 60 | 스케줄러 주기(후속) |
| SERVERPOOL_HOST / SERVERPOOL_BASE_PORT | host.docker.internal / 9101 | 메트릭 수집 대상(후속) |

`.env`는 git에 올리지 않는다(`.gitignore`). 예시는 `.env.example`.

## DB 스키마

단일 출처(Notion `데이터 모델 (ERD)`)의 **13개 엔티티**를 SQLAlchemy 모델로 둔다
(`app/models/`). 규약:

- 컬럼 **snake_case**, PK **BIGINT identity**, 시간 **timestamptz(UTC)**.
- enum은 **VARCHAR 컬럼 + 파이썬 `Enum`**(`app/models/enums.py`). 값이 미확정인
  `notification.type`·`audit_log.action`은 평문 문자열(후속 Enum화).
- 낙관적 잠금: `server.version`, `quota.version`. JSON 필드는 **JSONB**.
- API의 camelCase(`serverId` 등)는 후속 schemas 단계에서 Pydantic alias로 노출.

엔티티: `team`, `user`, `quota`, `server`, `reservation`, `approval_request`,
`notification`, `server_metric`, `anomaly_record`, `maintenance_schedule`,
`queue_entry`, `scheduler_log`, `audit_log`.

### 마이그레이션 (Alembic)

- 적용: api 컨테이너 시작 시 자동(`alembic upgrade head`).
- 베이스라인 `alembic/versions/0001_initial.py`는 ORM 메타데이터로 13개 테이블을
  생성한다(모델이 단일 출처이므로 모델·마이그레이션이 어긋나지 않음).
- 이후 변경: 모델 수정 → `alembic revision --autogenerate -m "설명"` → 다음 기동에 자동 적용.

### 시드 (개발용)

```bash
docker compose exec api python -m scripts.seed
```

팀 1·사용자 2·서버 2를 넣는다. 수동 실행이며 자동으로 돌지 않는다.

## 두 진입점

- API: `uvicorn app.main:app` — `app/main.py`
- 스케줄러: `python -m app.scheduler` — `app/scheduler.py` (현재 등록된 잡 없음)

## 디렉터리

구조는 `tree.md`를 따른다. 이번 단계에서 만든 것: `app/`(main·scheduler·config·
database·models), `alembic/`, `scripts/`, Docker/compose/env. `api/`·`schemas/`·
`services/`·`jobs/`·`core/`는 후속 단계에서 채운다.

## 후속(미구현)

도메인 라우터·서비스·스케줄러 잡, 인증(JWT), 메트릭 수집, 개발도구
(ruff·mypy·bandit·import-linter·pytest), 테스트.
