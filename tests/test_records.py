"""Records: persons, vehicles, BOLOs, warrants/cases, traffic stops, search, civilian scoping."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from nexus.core.context import Forbidden, ValidationFailed
from nexus.db.base import utcnow
from nexus.db.models import Bolo, Person
from nexus.services import records, search as search_svc

pytestmark = pytest.mark.anyio


async def test_person_and_vehicle_with_revisions(rt, admin):
    async with rt.db.session() as s:
        p = await records.create_person(s, admin, {"first_name": "John", "last_name": "Doe", "aliases": "JD, Johnny", "flags": ["Armed"]})
        v = await records.create_vehicle(s, admin, {"plate": "abc 123", "make": "Falcon", "model": "Stallion", "color": "Red",
                                                    "owner_person_id": p.id})
        await s.commit()
        assert p.number.startswith("P-") and p.aliases == ["JD", "Johnny"]
        assert v.plate == "ABC123" and v.owner_name == "John Doe"
        with pytest.raises(ValidationFailed):
            await records.create_vehicle(s, admin, {"plate": "ABC123"})  # duplicate plate
        with pytest.raises(ValidationFailed):
            await records.create_vehicle(s, admin, {"plate": "BAD$$"})
        await records.update_person(s, admin, p.id, {"license_status": "Suspended"})
        await s.commit()
        hist = await records.revisions(s, "person", p.id)
        assert [h["action"] for h in hist] == ["updated", "created"]
        assert hist[0]["changes"]["license_status"] == {"old": "Valid", "new": "Suspended"}
        prof = await records.person_profile(s, admin, p.id)
        assert prof["vehicles"][0]["plate"] == "ABC123" and prof["record_type"].startswith("Fictional")


async def test_archive_is_soft(rt, admin):
    async with rt.db.session() as s:
        p = await records.create_person(s, admin, {"first_name": "Gone"})
        await s.commit()
        await records.set_archived(s, admin, "person", p.id, True)
        await s.commit()
        assert (await s.get(Person, p.id)) is not None
        assert await records.search_persons(s, admin, "Gone") == []
        assert await records.search_persons(s, admin, "Gone", include_archived=True)


async def test_plate_check_alerts_and_bolo_lifecycle(rt, admin):
    async with rt.db.session() as s:
        await records.create_vehicle(s, admin, {"plate": "XYZ9", "registration_status": "Stolen", "flags": "Wanted"})
        b = await records.create_bolo(s, admin, {"category": "vehicle", "plate": "xyz 9", "reason": "Stolen vehicle"})
        await s.commit()
        res = await records.plate_check(s, admin, "xyz9")
        assert "Registration: Stolen" in res["alerts"] and any("BOLO" in a for a in res["alerts"]) and "Flag: Wanted" in res["alerts"]
        assert b.expires_at is not None  # default expiry applied
        await records.update_bolo(s, admin, b.id, {"last_known_location": "Highway"})
        assert b.status == "updated"
        await records.update_bolo(s, admin, b.id, {"status": "resolved"})
        await s.commit()
        assert b.closed_at and (await records.list_bolos(s, admin)) == []


async def test_bolo_expiry(rt, admin):
    async with rt.db.session() as s:
        b = await records.create_bolo(s, admin, {"category": "general", "subject_description": "Man in red", "reason": "Theft"})
        b.expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
        expired = await records.expire_bolos(s)
        await s.commit()
        assert [x.id for x in expired] == [b.id]
        assert (await s.get(Bolo, b.id)).status == "expired"


async def test_bolo_requires_reason(rt, admin):
    async with rt.db.session() as s:
        with pytest.raises(ValidationFailed):
            await records.create_bolo(s, admin, {"category": "person", "subject_description": "x"})


async def test_warrants_and_cases(rt, admin, make_user):
    officer = await make_user("200000000000000010", ["officer"], "Off")
    async with rt.db.session() as s:
        p = await records.create_person(s, admin, {"first_name": "Wanted", "last_name": "Person"})
        c = await records.create_case(s, admin, {"title": "Bank job", "restricted": True})
        w = await records.create_warrant(s, admin, {"person_id": p.id, "charges": "Armed robbery", "case_id": c.id})
        await s.commit()
        assert w.subject_name == "Wanted Person" and w.status == "active"
        await records.update_warrant(s, admin, w.id, {"status": "served"})
        await records.add_case_note(s, admin, c.id, "Suspect identified")
        await s.commit()
        detail = await records.case_detail(s, admin, c.id)
        assert detail["notes"][0]["body"] == "Suspect identified" and detail["warrants"][0]["status"] == "served"
        with pytest.raises(Forbidden):
            await records.create_warrant(s, officer, {"subject_name": "x", "charges": "y"})
        with pytest.raises(Forbidden):
            await records.case_detail(s, officer, c.id)  # restricted case
        assert await records.list_cases(s, officer) == []


async def test_traffic_stop_lifecycle(rt, admin, make_user):
    async with rt.db.session() as s:
        v = await records.create_vehicle(s, admin, {"plate": "TS1", "make": "Chevlon", "model": "Camion", "color": "Blue", "owner_name": "Joe"})
        await s.commit()
        t = await records.start_traffic_stop(s, admin, {"plate": "ts 1", "location": "Main St", "reason": "Speeding"})
        await s.commit()
        assert t.vehicle_id == v.id and t.driver_name == "Joe" and t.status == "active"
        with pytest.raises(ValidationFailed):
            await records.end_traffic_stop(s, admin, t.id)  # outcome required
        await records.end_traffic_stop(s, admin, t.id, outcome="Citation")
        await s.commit()
        assert t.status == "completed" and t.ended_at
        other = await make_user("200000000000000011", ["officer"], "Other")
        t2 = await records.start_traffic_stop(s, admin, {"vehicle_description": "Red car", "location": "Elm"})
        await s.commit()
        with pytest.raises(Forbidden):
            await records.update_traffic_stop(s, other, t2.id, {"notes": "x"})


async def test_civilians_only_manage_own_records(rt, admin, make_user):
    civ = await make_user("300000000000000010", ["civilian"], "Civ")
    async with rt.db.session() as s:
        mine = await records.create_person(s, civ, {"first_name": "My", "last_name": "Character"})
        theirs = await records.create_person(s, admin, {"first_name": "Police", "last_name": "Record"})
        await s.commit()
        assert mine.owner_user_id == civ.user_id and mine.is_civilian_character
        await records.update_person(s, civ, mine.id, {"notes": "edited"})
        with pytest.raises(Forbidden):
            await records.update_person(s, civ, theirs.id, {"notes": "hack"})
        results = await records.search_persons(s, civ, "")
        assert [r["id"] for r in results] == [mine.id]
        with pytest.raises(Forbidden):
            await records.create_vehicle(s, civ, {"plate": "CIV1", "owner_person_id": theirs.id})
        v = await records.create_vehicle(s, civ, {"plate": "CIV2", "owner_person_id": mine.id})
        assert v.owner_user_id == civ.user_id


async def test_central_search_respects_permissions(rt, admin, make_user):
    viewer = await make_user("400000000000000001", ["viewer"], "Viewer")
    async with rt.db.session() as s:
        await records.create_person(s, admin, {"first_name": "Searchable", "last_name": "Doe"})
        await s.commit()
        full = await search_svc.search(s, admin, "doe")
        assert full["results"]["people"]
        limited = await search_svc.search(s, viewer, "doe")
        assert "people" not in limited["results"]
        with pytest.raises(ValidationFailed):
            await search_svc.search(s, admin, "d")
        await s.commit()
        recent = await search_svc.recent_searches(s, admin)
        assert recent[0]["query"] == "doe"


async def test_discord_lookup_requires_permission(rt, admin, make_user):
    officer = await make_user("200000000000000012", ["officer"], "Off2")
    async with rt.db.session() as s:
        await records.create_person(s, admin, {"first_name": "Linked", "discord_id": "555555555555555555"})
        await s.commit()
        assert await records.search_persons(s, admin, "555555555555555555", by="discord")
        with pytest.raises(Forbidden):
            await records.search_persons(s, officer, "555555555555555555", by="discord")


async def test_record_links(rt, admin):
    from nexus.services import incidents

    async with rt.db.session() as s:
        p = await records.create_person(s, admin, {"first_name": "Linked"})
        inc = await incidents.create(s, admin, {"category": "crime", "description": "x"})
        await s.flush()
        await incidents.link_record(s, admin, inc.id, "person", p.id)
        await s.commit()
        links = await incidents.linked_records(s, "person", p.id)
        assert links[0]["type"] == "incident" and links[0]["id"] == inc.id
        assert (await s.execute(select(Person).where(Person.id == p.id))).scalar_one()
