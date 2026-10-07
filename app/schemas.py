from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_RECIPIENTS = 1000


class Recipient(BaseModel):
    """Ek recipient ka data. Har recipient ko alag se validate karte hain."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    achievement: Optional[str] = Field(default=None, max_length=200)


class JobCreate(BaseModel):
    """Poori request. Recipients ko dict rakha hai taaki ek galat recipient
    poori request ko reject na kare (unko hum job ke andar failed mark karenge)."""

    event_name: str = Field(min_length=1, max_length=200)
    issued_by: str = Field(min_length=1, max_length=100)
    issue_date: date
    recipients: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_RECIPIENTS)


def validate_recipient(raw: dict) -> tuple[Optional[Recipient], Optional[str]]:
    """(recipient, None) agar sahi hai, warna (None, error_message)."""
    try:
        return Recipient.model_validate(raw), None
    except ValidationError as e:
        msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        return None, msg
