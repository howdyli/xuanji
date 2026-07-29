"""Vision-model OCR for scanned PDF pages.

Uses DashScope-compatible API (qwen-vl-plus) to extract text from
page images. Designed for the ingestion pipeline — does NOT go through
the Agent/CrewAI layer.
"""
from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_LIMIT = 50
_DEFAULT_TIMEOUT = 30


class VisionOCR:
    """Extract text from PDF page images using a vision LLM."""

    def __init__(
        self,
        model: str = "qwen-vl-plus",
        *,
        page_limit: int = _DEFAULT_PAGE_LIMIT,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self._model = model
        self._page_limit = page_limit
        self._timeout = timeout
        self._api_key = (
            os.environ.get("KNOWLEDGE_EMBED_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY", "")
        )
        self._base_url = os.environ.get(
            "KNOWLEDGE_VISION_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def ocr_pages(
        self,
        page_images: list[bytes],
        *,
        max_pages: int | None = None,
    ) -> list[str]:
        """OCR a list of page images (PNG bytes). Returns text per page."""
        if not self._api_key:
            logger.warning("vision OCR: no API key configured")
            return [""] * len(page_images)

        limit = max_pages or self._page_limit
        pages = page_images[:limit]
        if len(page_images) > limit:
            logger.warning(
                "vision OCR: %d pages exceed limit %d, truncating",
                len(page_images),
                limit,
            )

        results: list[str] = []
        for i, img_bytes in enumerate(pages):
            try:
                text = self._call_api(img_bytes)
                results.append(text)
            except Exception as exc:
                logger.warning("vision OCR page %d failed: %s", i + 1, exc)
                results.append("")

        if len(results) < len(page_images):
            results.extend([""] * (len(page_images) - len(results)))

        logger.info("vision OCR: processed %d pages", len(results))
        return results

    def _call_api(self, image_bytes: bytes) -> str:
        """Call the vision model API for a single image. Returns extracted text."""
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("vision OCR: openai package not installed")
            return ""

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )
        b64 = base64.b64encode(image_bytes).decode()
        resp = client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请提取这张图片中的所有文字内容，保持原始格式和结构。如果没有文字内容，返回空字符串。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=4096,
            timeout=self._timeout,
        )
        return (resp.choices[0].message.content or "").strip()
