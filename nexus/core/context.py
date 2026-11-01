"""Request/command context shared by the website, API and Discord bot."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.core.permissions import has_permission


class NexusError(Exception):
    """Base error with a user-safe message."""

    status = 400
    code = "error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(NexusError):
    status = 404
    code = "not_found"


class Forbidden(NexusError):
    status = 403
    code = "forbidden"


class ValidationFailed(NexusError):
    status = 422
    code = "validation"


class Conflict(NexusError):
    status = 409
    code = "conflict"


@dataclass
class Actor:
    """Who is performing an action and what they may do (resolved server-side)."""

    user_id: int | None
    name: str = "system"
    permissions: frozenset[str] = field(default_factory=frozenset)
    department_ids: frozenset[int] = field(default_factory=frozenset)
    supervisor_department_ids: frozenset[int] = field(default_factory=frozenset)
    discord_id: str | None = None
    source: str = "web"  # web | discord | system | api
    ip: str = ""

    def can(self, perm: str) -> bool:
        return has_permission(self.permissions, perm)

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise Forbidden(f"You do not have permission to do that ({perm}).")

    def can_manage_department(self, department_id: int | None, perm: str = "dept.personnel.manage") -> bool:
        """Global admins manage everything; supervisors only their departments."""
        if self.can("cad.department.manage"):
            return True
        if not self.can(perm):
            return False
        return department_id is not None and department_id in self.supervisor_department_ids

    @property
    def is_system(self) -> bool:
        return self.user_id is None


SYSTEM = Actor(user_id=None, name="ERLC Nexus", permissions=frozenset({"*"}), source="system")
