"""Tokenizer-backed, character-addressable sliding text windows."""

from dataclasses import dataclass
from hashlib import sha256

import tiktoken
from tiktoken import Encoding

from novelatlas.schemas.parsing import SourceReference, TextChunk


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Validated limits for a deterministic chunking run."""

    tokenizer_name: str
    max_tokens: int
    overlap_tokens: int

    def __post_init__(self) -> None:
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative")
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")


class TokenChunker:
    """Split exact source ranges without losing their global character offsets."""

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config
        self.encoding: Encoding = tiktoken.get_encoding(config.tokenizer_name)

    def count(self, text: str) -> int:
        """Count tokens with ordinary encoding so source text is never special input."""

        return len(self.encoding.encode_ordinary(text))

    def chunk_range(
        self,
        *,
        text: str,
        task_id: str,
        chapter_id: str,
        start_char: int,
        end_char: int,
        first_ordinal: int,
    ) -> list[TextChunk]:
        """Create overlapping windows for one half-open source character range."""

        if start_char < 0 or end_char > len(text) or end_char < start_char:
            raise ValueError("invalid source range")
        if start_char == end_char or not text[start_char:end_char]:
            return []

        chunks: list[TextChunk] = []
        window_start = start_char
        previous_end = start_char

        while window_start < end_char:
            window_end = self._largest_safe_end(text, window_start, end_char)
            if window_end < end_char:
                window_end = self._prefer_natural_boundary(
                    text,
                    window_start,
                    window_end,
                )

            source = text[window_start:window_end]
            token_count = self.count(source)
            if not source or token_count == 0:
                break

            ordinal = first_ordinal + len(chunks)
            chunk_id = self._stable_id(
                "chunk",
                task_id,
                chapter_id,
                str(window_start),
                str(window_end),
                self.config.tokenizer_name,
            )
            citation_id = self._stable_id(
                "cite",
                task_id,
                str(window_start),
                str(window_end),
            )
            overlap = (
                self.count(text[window_start:previous_end])
                if chunks and window_start < previous_end
                else 0
            )
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    chapter_id=chapter_id,
                    ordinal=ordinal,
                    token_count=token_count,
                    overlap_with_previous_tokens=overlap,
                    reference=SourceReference(
                        citation_id=citation_id,
                        task_id=task_id,
                        chapter_id=chapter_id,
                        start_char=window_start,
                        end_char=window_end,
                        preview=self._preview(source),
                    ),
                )
            )

            if window_end >= end_char:
                break
            previous_end = window_end
            next_start = self._overlap_start(text, window_start, window_end)
            window_start = max(window_start + 1, next_start)

        return chunks

    def _largest_safe_end(self, text: str, start: int, limit: int) -> int:
        low = start
        high = min(limit, start + max(self.config.max_tokens * 4, 32))
        high_token_count = self.count(text[start:high])
        if high == limit and high_token_count <= self.config.max_tokens:
            return limit

        if high_token_count <= self.config.max_tokens:
            step = high - start
            low = high
            while high < limit:
                candidate = min(limit, high + step)
                candidate_token_count = self.count(text[start:candidate])
                if candidate_token_count > self.config.max_tokens:
                    high = candidate
                    break
                low = candidate
                high = candidate
                step *= 2
            if high == limit and low == limit:
                return limit

        while low + 1 < high:
            middle = (low + high) // 2
            if self.count(text[start:middle]) <= self.config.max_tokens:
                low = middle
            else:
                high = middle

        if low == start:
            # A single unusual Unicode scalar can span multiple tokens. Keeping it
            # intact is safer than dropping source text or looping forever.
            return start + 1
        return low

    @staticmethod
    def _prefer_natural_boundary(text: str, start: int, safe_end: int) -> int:
        minimum = start + int((safe_end - start) * 0.6)
        candidates = [
            text.rfind("\n\n", minimum, safe_end),
            text.rfind("\n", minimum, safe_end),
        ]
        for punctuation in "。！？；.!?;":
            position = text.rfind(punctuation, minimum, safe_end)
            if position >= 0:
                candidates.append(position + 1)
        boundary = max(candidates, default=-1)
        return boundary if boundary > start else safe_end

    def _overlap_start(self, text: str, start: int, end: int) -> int:
        if self.config.overlap_tokens == 0:
            return end

        low = start + 1
        high = end
        while low < high:
            middle = (low + high) // 2
            if self.count(text[middle:end]) <= self.config.overlap_tokens:
                high = middle
            else:
                low = middle + 1
        return low

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = sha256("\x1f".join(parts).encode()).hexdigest()[:16]
        return f"{prefix}_{digest}"

    @staticmethod
    def _preview(text: str, limit: int = 120) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit]}…"
