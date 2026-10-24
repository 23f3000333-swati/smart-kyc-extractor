"""Pydantic models for validating the LLM's JSON answer."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LLMField(BaseModel):
    """One field as returned by the LLM."""
    value: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    is_handwritten: bool = False

    @field_validator("value", mode="before")
    @classmethod
    def _to_str(cls, v):
        return "" if v is None else str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v / 100 if v > 1 else v))


class LLMResponse(BaseModel):
    """Whole answer: optional classification plus the requested fields."""
    doc_type: str = ""
    doc_type_confidence: float = 0.0
    fields: dict[str, LLMField] = Field(default_factory=dict)
