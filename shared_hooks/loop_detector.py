"""LoopDetector: state hash deduplication for tool call and turn loops."""

import hashlib

from xiaopaw.hook_framework.registry import DenyReason, GuardrailDeny


class LoopDetector:
    def __init__(self, threshold: int = 3):
        self._threshold = threshold
        self._tool_hashes: list[str] = []
        self._turn_hashes: list[str] = []
        self._loop_detections = 0
        self._total_tool_calls = 0
        self._total_turns = 0

    def after_tool_handler(self, ctx):
        self._total_tool_calls += 1
        state = f"{ctx.tool_name}:{ctx.metadata.get('tool_output', '')}"
        self._check_loop(self._tool_hashes, state, "tool_loop")

    def after_turn_handler(self, ctx):
        self._total_turns += 1
        state = ctx.metadata.get("output", "")
        self._check_loop(self._turn_hashes, state, "turn_loop")

    def _check_loop(self, hashes: list[str], state: str, detection_type: str):
        h = hashlib.md5(state.encode()).hexdigest()[:16]
        hashes.append(h)
        if len(hashes) > self._threshold * 2:
            del hashes[: len(hashes) - self._threshold * 2]
        if len(hashes) >= self._threshold:
            recent = hashes[-self._threshold :]
            if len(set(recent)) == 1:
                self._loop_detections += 1
                raise GuardrailDeny(
                    DenyReason.LOOP_DETECTED,
                    f"Loop detected ({detection_type}): identical state repeated {self._threshold} times",
                )

    def get_metrics(self) -> dict:
        unique_tool = len(set(self._tool_hashes))
        unique_turn = len(set(self._turn_hashes))
        return {
            "total_turns": self._total_turns,
            "total_tool_calls": self._total_tool_calls,
            "unique_tool_states": unique_tool,
            "unique_turn_states": unique_turn,
            "loop_detections": self._loop_detections,
        }
