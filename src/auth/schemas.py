from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AuthRole = Literal["admin", "seller", "anonymous", "disabled"]


@dataclass(frozen=True)
class AuthContext:
    authenticated: bool
    role: AuthRole
    auth_mode: str
    subject_id: str | None = None

