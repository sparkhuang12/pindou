from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pindou.coloring import DEFAULT_COLORING_PROMPT
from pindou.stylize import DEFAULT_PIXEL_PROMPT


class AuthPayload(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=48)


class PasswordChangePayload(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountDeletePayload(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ProjectRenamePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProfilePayload(BaseModel):
    display_name: str
    bio: str = ""


class SelectionPayload(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class MaskRefinePoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class MaskRefinePayload(BaseModel):
    keep: list[MaskRefinePoint] = Field(default_factory=list, max_length=2000)
    remove: list[MaskRefinePoint] = Field(default_factory=list, max_length=2000)
    radius: int = Field(default=32, ge=2, le=256)


class StylizePayload(BaseModel):
    provider: Literal["local", "model"] = "local"
    prompt: str = Field(default=DEFAULT_PIXEL_PROMPT, max_length=1000)
    pixel_resolution: int = Field(default=72, ge=24, le=128)
    color_count: int = Field(default=20, ge=4, le=64)


class PatternPayload(BaseModel):
    cols: int = Field(default=36, ge=8, le=100)
    rows: int = Field(default=35, ge=8, le=100)
    coverage: float = Field(default=0.32, gt=0.0, le=1.0)
    padding: float = Field(default=0.04, ge=0.0, lt=0.45)
    smooth_cells: int = Field(default=0, ge=0, le=3)
    source: Literal["auto", "painted", "stylized", "cutout", "original"] = "auto"
    palette_codes: list[str] = Field(default_factory=list, max_length=221)


class ColoringCreatePayload(BaseModel):
    cols: int = Field(default=36, ge=8, le=100)
    rows: int = Field(default=35, ge=8, le=100)
    coverage: float = Field(default=0.32, gt=0.0, le=1.0)
    padding: float = Field(default=0.04, ge=0.0, lt=0.45)
    smooth_cells: int = Field(default=0, ge=0, le=3)
    source: Literal["auto", "stylized", "cutout"] = "auto"
    palette_codes: list[str] = Field(default_factory=list, max_length=221)


class ColoringSavePayload(BaseModel):
    cells: list[list[str | None]] = Field(max_length=100)


class ColoringAiPayload(BaseModel):
    prompt: str = Field(default=DEFAULT_COLORING_PROMPT, max_length=1000)
    palette_codes: list[str] = Field(default_factory=list, max_length=221)


class MessagePayload(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)


class AdminUserPayload(BaseModel):
    role: Literal["user", "admin"]
    status: Literal["active", "disabled"]


class AdminMessagePayload(BaseModel):
    status: Literal["open", "read", "resolved"]
    admin_note: str = Field(default="", max_length=2000)
