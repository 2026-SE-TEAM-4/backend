"""값이 고정된 도메인 열거형.

DB에는 문자열(VARCHAR)로 저장하고, 이 Enum은 값 검증(후속 schemas 단계)과
코드 가독성을 위해 둔다. 용어는 ERD/상태 다이어그램과 일치시킨다.
값 목록이 아직 확정되지 않은 항목(Notification.type, AuditLog.action)은
모델에서 평문 문자열로 두고, 확정되면 여기에 Enum을 추가한다.
"""

from enum import Enum


class UserRole(str, Enum):
    STU = "STU"
    MGR = "MGR"
    ADM = "ADM"


class ServerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    CANCELED = "CANCELED"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"
    RECLAIMED = "RECLAIMED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_REJECTED = "AUTO_REJECTED"


class MetricStatus(str, Enum):
    """ServerMetric 수집 품질 상태(서버풀 /metrics 계약과 일치).

    에이전트는 응답하는 한 항상 OK만 보낸다. MISSING(무응답)·NA(항목 미지원)는
    백엔드 수집기가 수집 시점에 판정해 기록한다.
    """

    OK = "OK"
    MISSING = "MISSING"
    NA = "NA"


class MetricType(str, Enum):
    """이상탐지가 다루는 메트릭 종류(UC18). AnomalyRecord.metric 값."""

    CPU = "CPU"
    MEM = "MEM"
    NET = "NET"
    GPU = "GPU"


class IncidentSeverity(str, Enum):
    """인시던트 심각도(UC24). 이상 개수·서버 수·최고 편차로 산출."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    """인시던트 생애주기(UC24). 새 이상이 한동안 없으면 RESOLVED 로 자동 종료."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
