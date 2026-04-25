"""CostGuard: real-time token cost tracking + budget hard stop."""

import os
import sys

from xiaopaw.hook_framework.registry import DenyReason, GuardrailDeny

MODEL_PRICES = {
    "qwen-plus": {"input": 0.80, "output": 2.00},
    "qwen-turbo": {"input": 0.30, "output": 0.60},
    "qwen-max": {"input": 2.40, "output": 9.60},
}

_DEFAULT_PRICE = {"input": 1.0, "output": 3.0}


class CostGuard:
    def __init__(self, budget_usd: float = 1.0, model: str = "qwen-plus", token_counter=None):
        env_budget = os.environ.get("COST_GUARD_BUDGET")
        if env_budget is not None:
            try:
                budget_usd = float(env_budget)
            except ValueError:
                print(f"[CostGuard] invalid COST_GUARD_BUDGET value: {env_budget!r}, using default", file=sys.stderr)
        if budget_usd < 0:
            raise ValueError("budget_usd must be non-negative")
        self._budget = budget_usd
        self._model = model
        self._token_counter = token_counter
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._estimated_cost = 0.0
        self._deny_count = 0

    def after_turn_handler(self, ctx):
        self._total_input_tokens += ctx.input_tokens
        self._total_output_tokens += ctx.output_tokens
        self._estimated_cost = self._calculate_cost()
        if self._estimated_cost >= self._budget:
            self._deny_count += 1
            raise GuardrailDeny(
                DenyReason.BUDGET_EXCEEDED,
                f"Budget exceeded: ${self._estimated_cost:.4f} >= ${self._budget:.4f}",
            )

    def before_tool_handler(self, ctx):
        if self._estimated_cost >= self._budget:
            self._deny_count += 1
            raise GuardrailDeny(
                DenyReason.BUDGET_EXCEEDED,
                f"Budget exceeded: ${self._estimated_cost:.4f} >= ${self._budget:.4f}",
            )

    def _calculate_cost(self) -> float:
        model = self._model
        prices = MODEL_PRICES.get(model, _DEFAULT_PRICE)
        return (
            self._total_input_tokens * prices["input"] / 1_000_000
            + self._total_output_tokens * prices["output"] / 1_000_000
        )

    def get_metrics(self) -> dict:
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "estimated_cost_usd": self._estimated_cost,
            "budget_usd": self._budget,
            "deny_count": self._deny_count,
        }
