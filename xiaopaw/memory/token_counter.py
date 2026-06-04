"""Token counting with 3-level fallback."""

from __future__ import annotations

import json
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

_tokenizer = None
_mode = "rough"


@lru_cache(maxsize=1)
def _init_tokenizer() -> str:
    global _tokenizer, _mode
    # DeepSeek uses similar tokenizer to Qwen, fallback to rough estimation
    try:
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained(
            "deepseek-ai/deepseek-llm-7b-base", local_files_only=True
        )
        _mode = "hf_deepseek"
        logger.info("token_counter: using hf_deepseek tokenizer")
        return _mode
    except Exception:
        pass

    _mode = "rough"
    logger.info("token_counter: using rough estimation (len // 2)")
    return _mode


def count_tokens(messages: list[dict]) -> int:
    _init_tokenizer()
    text = json.dumps(messages, ensure_ascii=False)
    if _mode == "rough" or _tokenizer is None:
        return len(text) // 2
    try:
        return len(_tokenizer.encode(text))
    except Exception:
        return len(text) // 2
