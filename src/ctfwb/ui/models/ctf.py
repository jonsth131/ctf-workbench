"""CTF metadata model and persisted-record conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping

CTFTimeLookup = Callable[[str], Awaitable[Mapping[str, object]]]


@dataclass(frozen=True)
class CTF:
    """Display and persisted metadata for one CTF."""

    name: str
    year: int | None = None
    platform_url: str | None = None
    description: str = ""
    id: str | None = None
    source: str = "manual"
    created_at: str | None = None
    updated_at: str | None = None


async def _default_ctftime_lookup(url: str) -> Mapping[str, object]:
    """Import the optional event lookup only when the parse action is used."""
    from ctfwb.ctftime import fetch_ctftime_event

    return await fetch_ctftime_event(url)


def _ctf_from_record(record: Mapping[str, object]) -> CTF:
    year_value = record["year"]
    platform_url = record["platform_url"]
    return CTF(
        name=str(record["name"]),
        year=year_value if type(year_value) is int else None,
        platform_url=platform_url if isinstance(platform_url, str) else None,
        description=str(record["description"]),
        id=str(record["id"]),
        source=str(record["source"]),
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
    )


def _ctf_record(ctf: CTF) -> dict[str, object]:
    return {
        "id": ctf.id,
        "name": ctf.name,
        "year": ctf.year,
        "platform_url": ctf.platform_url,
        "description": ctf.description,
        "source": ctf.source,
        "created_at": ctf.created_at,
        "updated_at": ctf.updated_at,
    }
