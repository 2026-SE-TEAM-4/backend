"""모든 ORM 모델을 한곳에서 import 해 Base.metadata에 등록한다.

이 패키지를 import 하면 19개 엔티티가 모두 메타데이터에 잡혀
마이그레이션·create_all이 빠짐없이 인식한다.
"""

from app.models.anomaly_record import AnomalyRecord
from app.models.approval_request import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.forecast import Forecast
from app.models.incident import Incident
from app.models.incident_summary import IncidentSummary
from app.models.maintenance_schedule import MaintenanceSchedule
from app.models.notification import Notification
from app.models.queue_entry import QueueEntry
from app.models.quota import Quota
from app.models.reservation import Reservation
from app.models.scheduler_log import SchedulerLog
from app.models.security_alert import SecurityAlert
from app.models.security_event import SecurityEvent
from app.models.server import Server
from app.models.server_health_history import ServerHealthHistory
from app.models.server_metric import ServerMetric
from app.models.team import Team
from app.models.user import User

__all__ = [
    "Team",
    "User",
    "Quota",
    "Server",
    "ServerHealthHistory",
    "Reservation",
    "ApprovalRequest",
    "Notification",
    "ServerMetric",
    "AnomalyRecord",
    "Incident",
    "IncidentSummary",
    "Forecast",
    "MaintenanceSchedule",
    "QueueEntry",
    "SchedulerLog",
    "AuditLog",
    "SecurityEvent",
    "SecurityAlert",
]
