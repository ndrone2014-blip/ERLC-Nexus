"""ERLC Nexus database models.

All records in the CAD/MDT/records modules are fictional ERLC roleplay data.
Important records are never hard-deleted through normal actions; they use
``is_archived`` (soft delete) and keep their history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus.db.base import Base, utcnow


def _ts() -> Mapped[datetime]:
    return mapped_column(default=utcnow, nullable=False)


def _uts() -> Mapped[datetime]:
    return mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Identity, access control
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    display_name: Mapped[str] = mapped_column(String(100), default="")
    avatar_url: Mapped[str] = mapped_column(String(300), default="")
    roblox_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    roblox_username: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()
    last_login_at: Mapped[Optional[datetime]] = mapped_column()

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="UserRole.user_id"
    )
    memberships: Mapped[list["DepartmentMembership"]] = relationship(
        back_populates="user", foreign_keys="DepartmentMembership.user_id"
    )

    @property
    def name(self) -> str:
        return self.display_name or self.username or f"User {self.discord_id}"


class DiscordAccount(Base):
    """Discord identity data verified server-side (OAuth or bot gateway)."""

    __tablename__ = "discord_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    global_name: Mapped[Optional[str]] = mapped_column(String(100))
    guild_role_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    in_guild: Mapped[bool] = mapped_column(Boolean, default=False)
    roles_synced_at: Mapped[Optional[datetime]] = mapped_column()
    roles_source: Mapped[str] = mapped_column(String(20), default="none")  # oauth | bot | none


class Permission(Base):
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(200))


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(300), default="")
    color: Mapped[str] = mapped_column(String(9), default="#5b8def")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    discord_role_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    granted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = _ts()

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship()


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[Optional[datetime]] = mapped_column()

    user: Mapped[User] = relationship()


class AuthEvent(Base):
    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # login, logout, failed, expired, denied
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    discord_id: Mapped[Optional[str]] = mapped_column(String(32))
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    abbreviation: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="law")  # law, fire, ems, dot, dispatch, civilian, other
    color: Mapped[str] = mapped_column(String(9), default="#3b82f6")
    logo_url: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    callsign_format: Mapped[str] = mapped_column(String(40), default="{abbr}-{num:02}")
    unit_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    discord_role_id: Mapped[Optional[str]] = mapped_column(String(32))
    notify_channel_id: Mapped[Optional[str]] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()

    ranks: Mapped[list["Rank"]] = relationship(back_populates="department", order_by="Rank.sort_order")


class Rank(Base):
    __tablename__ = "ranks"
    __table_args__ = (UniqueConstraint("department_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    abbreviation: Mapped[str] = mapped_column(String(12), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # lower = more senior
    is_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)
    is_command: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    department: Mapped[Department] = relationship(back_populates="ranks")


class DepartmentMembership(Base):
    __tablename__ = "department_memberships"
    __table_args__ = (UniqueConstraint("user_id", "department_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    rank_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ranks.id", ondelete="SET NULL"))
    callsign: Mapped[Optional[str]] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active, leave, inactive, removed
    notes: Mapped[str] = mapped_column(Text, default="")
    joined_at: Mapped[datetime] = _ts()
    left_at: Mapped[Optional[datetime]] = mapped_column()

    user: Mapped[User] = relationship(back_populates="memberships", foreign_keys=[user_id])
    department: Mapped[Department] = relationship()
    rank: Mapped[Optional[Rank]] = relationship()


class DepartmentHistory(Base):
    __tablename__ = "department_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # joined, promoted, demoted, callsign, removed, status
    old_value: Mapped[Optional[str]] = mapped_column(String(120))
    new_value: Mapped[Optional[str]] = mapped_column(String(120))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    callsign: Mapped[str] = mapped_column(String(24), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    unit_type: Mapped[str] = mapped_column(String(32), default="Patrol")
    vehicle_description: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(32), default="out_of_service", index=True)
    current_incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    location_text: Mapped[str] = mapped_column(String(160), default="")
    location_x: Mapped[Optional[float]] = mapped_column(Float)
    location_z: Mapped[Optional[float]] = mapped_column(Float)
    location_source: Mapped[str] = mapped_column(String(12), default="none")  # none, manual, preset, api
    location_updated_at: Mapped[Optional[datetime]] = mapped_column()
    dispatcher_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    status_changed_at: Mapped[datetime] = _ts()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()

    department: Mapped[Department] = relationship()
    members: Mapped[list["UnitMembership"]] = relationship(
        back_populates="unit", primaryjoin="and_(Unit.id==UnitMembership.unit_id, UnitMembership.left_at==None)"
    )


class UnitMembership(Base):
    __tablename__ = "unit_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = _ts()
    left_at: Mapped[Optional[datetime]] = mapped_column()

    unit: Mapped[Unit] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class UnitEvent(Base):
    __tablename__ = "unit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[Optional[str]] = mapped_column(String(160))
    new_value: Mapped[Optional[str]] = mapped_column(String(160))
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# CAD incidents
# ---------------------------------------------------------------------------


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)
    subtype: Mapped[str] = mapped_column(String(64), default="")
    priority: Mapped[int] = mapped_column(Integer, default=3, index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    # caller
    caller_name: Mapped[str] = mapped_column(String(100), default="")
    caller_identifier: Mapped[str] = mapped_column(String(64), default="")
    caller_contact: Mapped[str] = mapped_column(String(100), default="")
    caller_description: Mapped[str] = mapped_column(String(300), default="")
    caller_notes: Mapped[str] = mapped_column(Text, default="")
    # location
    location_name: Mapped[str] = mapped_column(String(160), default="")
    street: Mapped[str] = mapped_column(String(120), default="")
    intersection: Mapped[str] = mapped_column(String(120), default="")
    postal: Mapped[str] = mapped_column(String(16), default="")
    map_x: Mapped[Optional[float]] = mapped_column(Float)
    map_z: Mapped[Optional[float]] = mapped_column(Float)
    location_instructions: Mapped[str] = mapped_column(String(300), default="")
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    # incident
    description: Mapped[str] = mapped_column(Text, default="")
    circumstances: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[str] = mapped_column(Text, default="")
    disposition: Mapped[str] = mapped_column(String(200), default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    dispatcher_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    supervisor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(16), default="web")  # web, discord, erlc_api, map
    source_ref: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = _uts()
    dispatched_at: Mapped[Optional[datetime]] = mapped_column()
    on_scene_at: Mapped[Optional[datetime]] = mapped_column()
    resolved_at: Mapped[Optional[datetime]] = mapped_column()
    closed_at: Mapped[Optional[datetime]] = mapped_column()
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    department: Mapped[Optional[Department]] = relationship()
    assignments: Mapped[list["IncidentAssignment"]] = relationship(back_populates="incident")


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(500), default="")
    old_value: Mapped[Optional[str]] = mapped_column(String(300))
    new_value: Mapped[Optional[str]] = mapped_column(String(300))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class IncidentAssignment(Base):
    __tablename__ = "incident_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = _ts()
    cleared_at: Mapped[Optional[datetime]] = mapped_column()

    incident: Mapped[Incident] = relationship(back_populates="assignments")
    unit: Mapped[Unit] = relationship()


class IncidentNote(Base):
    __tablename__ = "incident_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class RecordLink(Base):
    """Generic association between records (incident ↔ person, vehicle, bolo …)."""

    __tablename__ = "record_links"
    __table_args__ = (UniqueConstraint("source_type", "source_id", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(16), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(32), default="landmark", index=True)
    description: Mapped[str] = mapped_column(String(400), default="")
    street: Mapped[str] = mapped_column(String(120), default="")
    postal: Mapped[str] = mapped_column(String(16), default="")
    x: Mapped[float] = mapped_column(Float, default=0)
    z: Mapped[float] = mapped_column(Float, default=0)
    icon: Mapped[str] = mapped_column(String(32), default="")
    color: Mapped[str] = mapped_column(String(9), default="")
    is_preset: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)  # False = position not yet confirmed by an admin
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()


# ---------------------------------------------------------------------------
# Records (fictional roleplay data)
# ---------------------------------------------------------------------------


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(60), index=True)
    last_name: Mapped[str] = mapped_column(String(60), default="", index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    date_of_birth: Mapped[str] = mapped_column(String(20), default="")  # user-provided, fictional
    gender: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(String(400), default="")
    address: Mapped[str] = mapped_column(String(160), default="")
    license_status: Mapped[str] = mapped_column(String(24), default="Valid")
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    discord_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    roblox_username: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_civilian_character: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    plate: Mapped[str] = mapped_column(String(16), index=True)
    make: Mapped[str] = mapped_column(String(48), default="", index=True)
    model: Mapped[str] = mapped_column(String(48), default="", index=True)
    color: Mapped[str] = mapped_column(String(32), default="", index=True)
    category: Mapped[str] = mapped_column(String(32), default="Sedan")
    year: Mapped[str] = mapped_column(String(8), default="")
    owner_person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    registration_status: Mapped[str] = mapped_column(String(24), default="Valid", index=True)
    insurance_status: Mapped[str] = mapped_column(String(24), default="Valid")
    description: Mapped[str] = mapped_column(String(300), default="")
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    owner: Mapped[Optional[Person]] = relationship()


class RecordRevision(Base):
    """Field-level history for editable records."""

    __tablename__ = "record_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(16), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(16))  # created, updated, archived, restored
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class Bolo(Base):
    __tablename__ = "bolos"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(16), default="general")  # person, vehicle, general
    subject_description: Mapped[str] = mapped_column(String(400), default="")
    vehicle_description: Mapped[str] = mapped_column(String(300), default="")
    plate: Mapped[str] = mapped_column(String(16), default="", index=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    last_known_location: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    issued_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column()
    expiry_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()
    closed_at: Mapped[Optional[datetime]] = mapped_column()


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open, active, closed, archived
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    lead_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()
    closed_at: Mapped[Optional[datetime]] = mapped_column()


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class Warrant(Base):
    __tablename__ = "warrants"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    warrant_type: Mapped[str] = mapped_column(String(16), default="arrest")  # arrest, search, bench
    case_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    subject_name: Mapped[str] = mapped_column(String(120), default="")
    charges: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    issued_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active, served, recalled, expired
    expires_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()


class TrafficStop(Base):
    __tablename__ = "traffic_stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    officer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    callsign: Mapped[str] = mapped_column(String(24), default="")
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    driver_name: Mapped[str] = mapped_column(String(120), default="")
    driver_person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    plate: Mapped[str] = mapped_column(String(16), default="", index=True)
    vehicle_description: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    map_x: Mapped[Optional[float]] = mapped_column(Float)
    map_z: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(300), default="")
    passengers: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = _ts()
    ended_at: Mapped[Optional[datetime]] = mapped_column()


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(String(32), default="incident")
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), index=True)
    author_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    callsign: Mapped[str] = mapped_column(String(24), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    incident_type: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    occurred_at: Mapped[Optional[datetime]] = mapped_column()
    involved_personnel: Mapped[str] = mapped_column(String(400), default="")
    summary: Mapped[str] = mapped_column(String(600), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column()
    submitted_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _uts()


class ReportRevision(Base):
    __tablename__ = "report_revisions"
    __table_args__ = (UniqueConstraint("report_id", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = _ts()


class ReportComment(Base):
    __tablename__ = "report_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(16), default="comment")  # comment, approve, return, review
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# Shifts, comms, notifications
# ---------------------------------------------------------------------------


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        # Database-level guarantee: one active shift per user.
        Index(
            "uq_shifts_one_active",
            "user_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    callsign: Mapped[str] = mapped_column(String(24), default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="active")  # active, ended, approved, rejected
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(12), default="web")
    adjusted_seconds: Mapped[Optional[int]] = mapped_column(Integer)  # manual override of duration
    adjusted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    adjust_reason: Mapped[str] = mapped_column(String(200), default="")
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column()
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class DispatchMessage(Base):
    __tablename__ = "dispatch_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), default="dispatch", index=True)  # dispatch, department, unit, broadcast
    kind: Mapped[str] = mapped_column(String(16), default="message")  # message, announcement, status, incident
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    sender_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sender_label: Mapped[str] = mapped_column(String(80), default="")
    body: Mapped[str] = mapped_column(Text)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(12), default="web")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    audience: Mapped[str] = mapped_column(String(48), default="all")  # all | perm:<key> | user
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(600), default="")
    link: Mapped[str] = mapped_column(String(200), default="")
    severity: Mapped[str] = mapped_column(String(12), default="info")
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (UniqueConstraint("notification_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# Configuration, audit, events, infrastructure
# ---------------------------------------------------------------------------


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = _uts()


class AuditLog(Base):
    """Append-only audit trail; each row is hash-chained to the previous one."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(16), index=True)  # erlc, cad, mdt, department, system
    action: Mapped[str] = mapped_column(String(48), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    target_type: Mapped[str] = mapped_column(String(24), default="")
    target_id: Mapped[Optional[str]] = mapped_column(String(48), index=True)
    target_ref: Mapped[str] = mapped_column(String(64), default="")
    department_id: Mapped[Optional[int]] = mapped_column(Integer)
    old_value: Mapped[Optional[Any]] = mapped_column(JSON)
    new_value: Mapped[Optional[Any]] = mapped_column(JSON)
    context: Mapped[Optional[Any]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(12), default="web")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class EventOutbox(Base):
    """Cross-process event stream (website WebSockets, Discord notifier)."""

    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(12), default="web")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Counter(Base):
    __tablename__ = "counters"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class LeaderLease(Base):
    __tablename__ = "leader_leases"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column()


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------------------
# ERLC API data
# ---------------------------------------------------------------------------


class ApiSyncRecord(Base):
    __tablename__ = "api_sync_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    error_code: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[str] = mapped_column(String(300), default="")
    players: Mapped[Optional[int]] = mapped_column(Integer)
    rate_remaining: Mapped[Optional[int]] = mapped_column(Integer)


class ErlcState(Base):
    """Latest cached API payloads, shared by bot and website."""

    __tablename__ = "erlc_state"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[Any] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = _uts()


class PlayerCountSample(Base):
    __tablename__ = "player_count_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    players: Mapped[int] = mapped_column(Integer)
    max_players: Mapped[int] = mapped_column(Integer)
    queue: Mapped[int] = mapped_column(Integer, default=0)
    teams: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)


class ErlcPlayer(Base):
    """Players observed by Nexus (history is Nexus-recorded, not from the API)."""

    __tablename__ = "erlc_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    roblox_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    first_seen: Mapped[datetime] = _ts()
    last_seen: Mapped[datetime] = _ts()
    last_team: Mapped[str] = mapped_column(String(32), default="")
    last_callsign: Mapped[str] = mapped_column(String(32), default="")
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class PlayerAction(Base):
    __tablename__ = "player_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    roblox_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(16))  # kick, ban, unban, warn, note, command
    reason: Mapped[str] = mapped_column(String(300), default="")
    command: Mapped[str] = mapped_column(String(300), default="")
    result: Mapped[str] = mapped_column(String(120), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(12), default="web")
    created_at: Mapped[datetime] = _ts()


class ServerLogEntry(Base):
    """Deduplicated join/kill/command/modcall logs collected from the API."""

    __tablename__ = "server_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # join, kill, command, modcall
    ts: Mapped[datetime] = mapped_column(index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    dedupe: Mapped[str] = mapped_column(String(64), unique=True)


class ErlcEmergencyCall(Base):
    __tablename__ = "erlc_emergency_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe: Mapped[str] = mapped_column(String(64), unique=True)
    call_number: Mapped[int] = mapped_column(Integer)
    team: Mapped[str] = mapped_column(String(32), default="")
    caller_roblox_id: Mapped[str] = mapped_column(String(32), default="")
    caller_name: Mapped[str] = mapped_column(String(64), default="")
    players: Mapped[list[int]] = mapped_column(JSON, default=list)
    x: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    position_descriptor: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending, accepted, dismissed
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    handled_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class DiscordPanel(Base):
    """Persistent interactive Discord panels (auto-refreshing embeds)."""

    __tablename__ = "discord_panels"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))  # server, incidents, units, bolos, shifts
    channel_id: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str] = mapped_column(String(32), unique=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
