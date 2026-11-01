"""Typed models for the official PRC API v2 responses (apidocs.erlc.gg).

Only documented fields are modelled. Unknown extra fields are ignored so a
future API addition never breaks parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def split_player(value: str | None) -> tuple[str, str]:
    """Parse the API's ``"PlayerName:Id"`` format into (name, id)."""
    if not value:
        return "", ""
    name, sep, pid = str(value).rpartition(":")
    if not sep:
        return str(value), ""
    return name, pid


def ts_to_dt(ts: int | float | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class PlayerLocation(_M):
    x: Optional[float] = Field(default=None, alias="LocationX")
    z: Optional[float] = Field(default=None, alias="LocationZ")
    postal: Optional[str] = Field(default=None, alias="PostalCode")
    street: Optional[str] = Field(default=None, alias="StreetName")
    building: Optional[str] = Field(default=None, alias="BuildingNumber")


class Player(_M):
    raw: str = Field(alias="Player")
    team: str = Field(default="", alias="Team")
    callsign: Optional[str] = Field(default=None, alias="Callsign")
    permission: str = Field(default="Normal", alias="Permission")
    wanted_stars: int = Field(default=0, alias="WantedStars")
    location: Optional[PlayerLocation] = Field(default=None, alias="Location")

    @property
    def name(self) -> str:
        return split_player(self.raw)[0]

    @property
    def id(self) -> str:
        return split_player(self.raw)[1]

    def to_public(self) -> dict[str, Any]:
        loc = self.location
        return {
            "name": self.name, "id": self.id, "team": self.team, "callsign": self.callsign,
            "permission": self.permission, "wanted_stars": self.wanted_stars,
            "location": None if loc is None else {
                "x": loc.x, "z": loc.z, "postal": loc.postal, "street": loc.street, "building": loc.building,
            },
        }


class StaffLists(_M):
    admins: dict[str, str] = Field(default_factory=dict, alias="Admins")
    mods: dict[str, str] = Field(default_factory=dict, alias="Mods")
    helpers: dict[str, str] = Field(default_factory=dict, alias="Helpers")

    @field_validator("admins", "mods", "helpers", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> dict[str, str]:
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return {}


class JoinLog(_M):
    join: bool = Field(alias="Join")
    timestamp: int = Field(alias="Timestamp")
    player: str = Field(alias="Player")


class KillLog(_M):
    killed: str = Field(alias="Killed")
    killer: str = Field(alias="Killer")
    timestamp: int = Field(alias="Timestamp")


class CommandLog(_M):
    player: str = Field(alias="Player")
    command: str = Field(alias="Command")
    timestamp: int = Field(alias="Timestamp")


class ModCall(_M):
    caller: str = Field(alias="Caller")
    moderator: Optional[str] = Field(default=None, alias="Moderator")
    timestamp: int = Field(alias="Timestamp")


class EmergencyCall(_M):
    team: str = Field(default="", alias="Team")
    caller: int = Field(alias="Caller")
    players: list[int] = Field(default_factory=list, alias="Players")
    position: list[float] = Field(default_factory=list, alias="Position")
    started_at: int = Field(alias="StartedAt")
    call_number: int = Field(alias="CallNumber")
    description: str = Field(default="", alias="Description")
    position_descriptor: str = Field(default="", alias="PositionDescriptor")

    @property
    def dedupe_key(self) -> str:
        return f"{self.call_number}:{self.started_at}:{self.caller}"


class SpawnedVehicle(_M):
    name: str = Field(default="", alias="Name")
    owner: str = Field(default="", alias="Owner")
    plate: str = Field(default="", alias="Plate")
    texture: Optional[str] = Field(default=None, alias="Texture")
    color_hex: str = Field(default="", alias="ColorHex")
    color_name: str = Field(default="", alias="ColorName")


class ServerSnapshot(_M):
    name: str = Field(alias="Name")
    owner_id: int = Field(alias="OwnerId")
    co_owner_ids: list[int] = Field(default_factory=list, alias="CoOwnerIds")
    current_players: int = Field(alias="CurrentPlayers")
    max_players: int = Field(alias="MaxPlayers")
    join_key: str = Field(default="", alias="JoinKey")
    acc_verified_req: str = Field(default="", alias="AccVerifiedReq")
    team_balance: bool = Field(default=False, alias="TeamBalance")
    players: Optional[list[Player]] = Field(default=None, alias="Players")
    staff: Optional[StaffLists] = Field(default=None, alias="Staff")
    join_logs: Optional[list[JoinLog]] = Field(default=None, alias="JoinLogs")
    queue: Optional[list[int]] = Field(default=None, alias="Queue")
    kill_logs: Optional[list[KillLog]] = Field(default=None, alias="KillLogs")
    command_logs: Optional[list[CommandLog]] = Field(default=None, alias="CommandLogs")
    mod_calls: Optional[list[ModCall]] = Field(default=None, alias="ModCalls")
    emergency_calls: Optional[list[EmergencyCall]] = Field(default=None, alias="EmergencyCalls")
    vehicles: Optional[list[SpawnedVehicle]] = Field(default=None, alias="Vehicles")

    def team_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.players or []:
            counts[p.team or "Unknown"] = counts.get(p.team or "Unknown", 0) + 1
        return counts

    def to_public(self, *, include_join_key: bool = True) -> dict[str, Any]:
        """JSON-safe dict for the website/bot. Contains no credentials."""
        return {
            "name": self.name,
            "owner_id": self.owner_id,
            "co_owner_ids": self.co_owner_ids,
            "current_players": self.current_players,
            "max_players": self.max_players,
            "capacity_pct": round(100 * self.current_players / self.max_players, 1) if self.max_players else 0,
            "join_key": self.join_key if include_join_key else None,
            "acc_verified_req": self.acc_verified_req,
            "team_balance": self.team_balance,
            "teams": self.team_counts(),
            "players": [p.to_public() for p in self.players or []],
            "staff": None if self.staff is None else {
                "admins": self.staff.admins, "mods": self.staff.mods, "helpers": self.staff.helpers,
            },
            "queue": self.queue or [],
            "vehicles": [v.model_dump() for v in self.vehicles or []],
        }
