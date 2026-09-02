"""Decode uploaded TXT bytes without silently replacing invalid content."""

from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE
from dataclasses import dataclass

from charset_normalizer import from_bytes


class TextDecodeError(ValueError):
    """Raised when uploaded bytes cannot be treated as readable text."""


@dataclass(frozen=True, slots=True)
class DecodedText:
    """Normalized text and the encoding used to decode it."""

    content: str
    encoding: str


def _has_too_many_control_characters(text: str) -> bool:
    controls = sum(
        1 for character in text if ord(character) < 32 and character not in "\n\t"
    )
    return controls > max(5, len(text) // 100)


def _decode_with_encoding(data: bytes, encoding: str) -> DecodedText | None:
    try:
        content = data.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError):
        return None

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip() or _has_too_many_control_characters(normalized):
        return None

    return DecodedText(content=normalized, encoding=encoding.lower())


def decode_txt(data: bytes) -> DecodedText:
    """Decode common Chinese TXT encodings and normalize line endings."""

    if not data:
        raise TextDecodeError("TXT 文件为空")

    bom_encodings: tuple[tuple[bytes, str], ...] = (
        (BOM_UTF8, "utf-8-sig"),
        (BOM_UTF16_LE, "utf-16"),
        (BOM_UTF16_BE, "utf-16"),
    )
    for marker, encoding in bom_encodings:
        if data.startswith(marker):
            decoded = _decode_with_encoding(data, encoding)
            if decoded is not None:
                return decoded

    for encoding in ("utf-8", "gb18030", "big5"):
        decoded = _decode_with_encoding(data, encoding)
        if decoded is not None:
            return decoded

    best_match = from_bytes(data).best()
    if best_match is not None and best_match.encoding:
        decoded = _decode_with_encoding(data, best_match.encoding)
        if decoded is not None:
            return decoded

    raise TextDecodeError("无法识别 TXT 编码，建议转换为 UTF-8 后重试")
