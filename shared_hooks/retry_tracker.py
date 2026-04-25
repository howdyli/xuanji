"""RetryTracker: pure observation — tracks consecutive tool failures and retry success rate."""

import sys


class RetryTracker:
    def __init__(self, max_retries: int = 5):
        self._max_retries = max_retries
        self._failures: dict[str, int] = {}
        self._total_retries = 0
        self._successful_retries = 0

    def after_tool_handler(self, ctx):
        if not ctx.tool_name:
            return

        if not ctx.success:
            prev = self._failures.get(ctx.tool_name, 0)
            self._failures[ctx.tool_name] = prev + 1
            if prev > 0:
                self._total_retries += 1
            if self._failures[ctx.tool_name] >= self._max_retries:
                print(
                    f"[RetryTracker] WARNING: {ctx.tool_name} failed {self._failures[ctx.tool_name]} times consecutively",
                    file=sys.stderr,
                )
        else:
            if self._failures.get(ctx.tool_name, 0) > 0:
                self._successful_retries += 1
            self._failures[ctx.tool_name] = 0

    def get_metrics(self) -> dict:
        active = {k: v for k, v in self._failures.items() if v > 0}
        rate = self._successful_retries / max(self._total_retries, 1) if self._total_retries > 0 else 0.0
        return {
            "active_failures": active,
            "total_retries": self._total_retries,
            "successful_retries": self._successful_retries,
            "retry_success_rate": rate,
        }
