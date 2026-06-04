"""Redis 클라이언트와 로그인 실패 카운터.

로그인 실패는 일시 상태라 DB가 아니라 Redis에 둔다(설계 D3).
키: login_fail:{email}, TTL=설정 창. 계정 잠금만 user.locked_until에 영속화한다.
"""

from redis.asyncio import Redis

from app.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    """프로세스당 하나의 클라이언트를 재사용한다."""
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _fail_key(email: str) -> str:
    return f"login_fail:{email}"


async def increment_login_fail(email: str) -> int:
    """실패 횟수를 1 늘리고 현재 값을 돌려준다. 창(window) 동안만 유지된다."""
    redis = get_redis()
    key = _fail_key(email)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.login_fail_window_sec)
    return count


async def reset_login_fail(email: str) -> None:
    await get_redis().delete(_fail_key(email))
