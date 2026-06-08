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
│   ├── api/                   # 도메인별 라우터 (1 도메인 = 1 파일 권장)│   │                          # auth, users, teams, servers,
│   │                          # reservations, approvals, metrics ...
│   │   ├── deps.py            # DB 세션 등 FastAPI 공통 의존성
│   │   ├── ops.py             # 운영 대시보드·가용성 조회 API
│   │   ├── servers.py         # 서버 등록·조회·삭제·점검·대안 조회 API
│   │   ├── users.py           # 계정 잠금 해제 API
│   │   ├── approvals.py
│   │   ├── notifications.py
│   │   └── reservations.py
│   ├── models/                # SQLAlchemy ORM 모델
│   ├── schemas/               # Pydantic 입출력 스키마
│   │   ├── ops.py             # 운영 API 스키마
│   │   ├── servers.py         # 서버 API 스키마
│   │   ├── users.py           # 사용자 운영 API 스키마
│   │   ├── approval_request.py
│   │   ├── notification.py
│   │   └── reservation.py
│   ├── services/              # 비즈니스 로직 (라우터에서 호출)
│   │   ├── monitoring.py      # 메트릭 수집·이상 탐지·건강 점수·자동 회수 로직
│   │   ├── ops.py             # 운영 집계·가용성 산출
│   │   ├── servers.py         # 서버·점검·대안 서버 로직
│   │   ├── users.py           # 사용자 운영 로직
│   │   ├── approval_service.py
│   │   ├── notification_service.py
│   │   └── reservation_service.py
│   ├── jobs/                  # APScheduler 잡 (UC14, 15, 16, 18, 19)
│   │   ├── health.py          # 서버 건강 점수 산출
│   │   ├── idle.py            # 유휴 서버 감지·자동 회수
│   │   └── monitoring.py      # 사용률 수집·이상 징후 탐지
│   └── core/                  # 보안·예외·공통 의존성 (cross-cutting)
│       ├── exceptions.py      # 서비스 계층 예외
│       ├── rate_limit.py      # 비정상 접근 감지·일시 잠금 미들웨어
│       └── deps.py
├── alembic/                   # DB 마이그레이션
│   └── versions/              # 생성된 리비전 파일
├── scripts/                   # 운영 스크립트 (seed, dump 등)
├── pyproject.toml             # uv 기반 의존성·도구 설정
├── uv.lock
├── alembic.ini                # alembic 설정
├── Dockerfile                 # api / scheduler 공통 이미지
├── docker-compose.yml         # api + scheduler + postgres + redis
├── README.md
├── tree.md                    # 본 파일
└── rule.md                    # 코딩 규칙
```

## 레이어 책임 요약

- `api/` 는 입력 검증과 응답 직렬화만 담당한다. 로직은 `services/` 로 넘긴다.
- `services/` 는 도메인 로직을 가진다. ORM 객체를 직접 다루되, FastAPI 의존성은
  알지 않는다 (테스트 용이성).
- `models/` 와 `schemas/` 는 의도적으로 분리한다. ORM 모델을 그대로 응답으로
  내보내지 않는다 (직렬화·필드 제어를 위함).
- `core/` 는 여러 도메인이 공유하는 코드만 둔다. 한 도메인에만 쓰이면 해당
  도메인 폴더로 옮긴다.
