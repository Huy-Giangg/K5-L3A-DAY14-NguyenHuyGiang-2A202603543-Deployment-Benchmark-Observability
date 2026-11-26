"""
Cost guard (tiêu chí 8) — theo dõi tổng chi phí LLM trong Redis.
"""
import logging
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

COST_REDIS_KEY = "cost:total"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget -> raise HTTPException(status_code=402)."""
    budget = settings.effective_budget_usd
    if budget <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Budget exceeded",
        )

    if r is None:
        return

    try:
        raw_total = r.get(COST_REDIS_KEY)
        current_spend = float(raw_total) if raw_total is not None else 0.0
    except RedisError as exc:
        logger.warning("Redis unavailable during budget check", extra={"event": "redis_error", "error": str(exc)})
        return

    if current_spend >= budget:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    request_cost = (
        (max(0, input_tokens) / 1000.0) * PRICE_INPUT_PER_1K
        + (max(0, output_tokens) / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    if r is None:
        return request_cost

    try:
        r.incrbyfloat(COST_REDIS_KEY, request_cost)
    except RedisError as exc:
        logger.warning("Redis unavailable while recording cost", extra={"event": "redis_error", "error": str(exc)})
    return request_cost
