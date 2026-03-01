"""Pydantic request/response models for the web API."""

from pydantic import BaseModel, Field, field_validator


class QualifyRequest(BaseModel):
    popis_skutku: str = Field(min_length=20, max_length=64000)
    typ: str = Field(pattern="^(TC|PR)$")

    @field_validator("popis_skutku")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class QualifyResponse(BaseModel):
    qualification_id: int
    message: str = "Kvalifikace zahájena"


class QualificationResult(BaseModel):
    id: int
    popis_skutku: str
    typ: str
    stav: str
    vysledek: dict | None = None
    error_message: str | None = None


class AgentEvent(BaseModel):
    agent_name: str
    stav: str
    zprava: str
