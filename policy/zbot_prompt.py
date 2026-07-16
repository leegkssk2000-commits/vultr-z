from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

POLICY_OWNER = "policy/zbot_prompt.py"
RUNTIME_ENABLED = False


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    version: str
    task_kind: str
    response_schema_id: str
    template_hash: str


PROMPT_REGISTRY = MappingProxyType({
    "market_context_review": PromptSpec(
        "zbot.market_context_review", "r53.1", "market_context_review",
        "zbot.review.v1", "sha256:market-context-r53-1",
    ),
    "strategy_counterargument": PromptSpec(
        "zbot.strategy_counterargument", "r53.1", "strategy_counterargument",
        "zbot.review.v1", "sha256:strategy-counterargument-r53-1",
    ),
    "risk_review": PromptSpec(
        "zbot.risk_review", "r53.1", "risk_review",
        "zbot.review.v1", "sha256:risk-review-r53-1",
    ),
    "optimization_candidate_review": PromptSpec(
        "zbot.optimization_candidate_review", "r53.1", "optimization_candidate_review",
        "zbot.review.v1", "sha256:optimization-review-r53-1",
    ),
    "post_trade_explanation": PromptSpec(
        "zbot.post_trade_explanation", "r53.1", "post_trade_explanation",
        "zbot.explanation.v1", "sha256:post-trade-explanation-r53-1",
    ),
})


def get_prompt(task_kind: str) -> PromptSpec | None:
    return PROMPT_REGISTRY.get(task_kind)


def validate_prompt_registry() -> tuple[str, ...]:
    reasons: list[str] = []
    seen: set[tuple[str, str]] = set()
    for task_kind, prompt in PROMPT_REGISTRY.items():
        if prompt.task_kind != task_kind:
            reasons.append("PROMPT_TASK_MISMATCH")
        identity = (prompt.prompt_id, prompt.version)
        if identity in seen:
            reasons.append("PROMPT_VERSION_DUPLICATE")
        seen.add(identity)
        if not prompt.prompt_id or not prompt.version or not prompt.response_schema_id:
            reasons.append("PROMPT_METADATA_MISSING")
        if not prompt.template_hash.startswith("sha256:"):
            reasons.append("PROMPT_HASH_INVALID")
    return tuple(sorted(set(reasons)))
