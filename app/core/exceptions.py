"""서비스 계층에서 쓰는 단순 예외."""


class ServiceError(Exception):
    """비즈니스 규칙 위반."""


class NotFoundError(ServiceError):
    """대상이 존재하지 않음."""


class ConflictError(ServiceError):
    """현재 상태 때문에 요청을 처리할 수 없음."""


class ValidationError(ServiceError):
    """요청 값이 도메인 규칙에 맞지 않음."""
