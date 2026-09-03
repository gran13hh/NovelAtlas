"""Hierarchical merge and final-outline skill."""

from .skill import (
    FINAL_OUTLINE_INSTRUCTIONS,
    MERGE_SUMMARY_INSTRUCTIONS,
    HierarchicalOutlineOutputError,
    build_final_outline_prompt,
    build_merge_summary_prompt,
    parse_final_outline_response,
    parse_merge_summary_response,
)

__all__ = [
    "FINAL_OUTLINE_INSTRUCTIONS",
    "MERGE_SUMMARY_INSTRUCTIONS",
    "HierarchicalOutlineOutputError",
    "build_final_outline_prompt",
    "build_merge_summary_prompt",
    "parse_final_outline_response",
    "parse_merge_summary_response",
]
