from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseSchema(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    data: T
    message: str | None = None
