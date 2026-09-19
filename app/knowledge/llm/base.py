"""Provider-independent structured extraction contract."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class StructuredExtractionRequest:
    task: str
    prompt_version: str
    model: str
    instructions: str
    input_text: str
    output_model: type[BaseModel]
    timeout_seconds: int = 180


class LLMProvider(Protocol):
    name: str

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        """Return schema-validated structured output or raise explicitly."""
