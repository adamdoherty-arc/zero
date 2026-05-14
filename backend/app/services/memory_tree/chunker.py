"""
Token-aware chunking for Memory Vault.

openhuman target is "â‰¤3k tokens per chunk". We approximate token count as
chars/4 (good middle for English + code, see tokenjuice_compactor.py for the
same convention). Chunks split on paragraph then sentence boundaries so the
LLM never sees a sentence cut in half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 3000

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@dataclass(frozen=True)
class Chunk:
    text: str
    token_count: int


def chunk_text(text: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[Chunk]:
    """Split a long text into ``Chunk`` instances, each â‰¤ ``max_tokens``.

    Splitting prefers paragraph boundaries, falls back to sentences, and as
    a last resort hard-cuts on a character boundary.
    """
    if not text:
        return []
    max_chars = max_tokens * CHARS_PER_TOKEN

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_chars = 0

    def flush() -> None:
        nonlocal buf, buf_chars
        if buf:
            body = "\n\n".join(buf).strip()
            chunks.append(Chunk(text=body, token_count=len(body) // CHARS_PER_TOKEN))
            buf = []
            buf_chars = 0

    for para in paragraphs:
        if len(para) > max_chars:
            # Paragraph itself is too big â€” split by sentence.
            flush()
            sentences = _SENTENCE_SPLIT.split(para)
            sub_buf: list[str] = []
            sub_chars = 0
            for sent in sentences:
                if sub_chars + len(sent) + 1 > max_chars and sub_buf:
                    body = " ".join(sub_buf).strip()
                    chunks.append(
                        Chunk(text=body, token_count=len(body) // CHARS_PER_TOKEN)
                    )
                    sub_buf = []
                    sub_chars = 0
                if len(sent) > max_chars:
                    # Last resort: hard cut the sentence by chars.
                    for i in range(0, len(sent), max_chars):
                        slab = sent[i:i + max_chars].strip()
                        if slab:
                            chunks.append(
                                Chunk(text=slab, token_count=len(slab) // CHARS_PER_TOKEN)
                            )
                else:
                    sub_buf.append(sent)
                    sub_chars += len(sent) + 1
            if sub_buf:
                body = " ".join(sub_buf).strip()
                chunks.append(
                    Chunk(text=body, token_count=len(body) // CHARS_PER_TOKEN)
                )
            continue

        if buf_chars + len(para) + 2 > max_chars and buf:
            flush()
        buf.append(para)
        buf_chars += len(para) + 2

    flush()
    return chunks
