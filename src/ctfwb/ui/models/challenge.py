"""Challenge metadata model and persisted-record conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Challenge:
    """Display and persisted metadata for one challenge."""

    name: str
    category: str | None = None
    points: int | None = None
    description: str = ""
    id: str | None = None
    artifacts: tuple[Mapping[str, object], ...] = ()
    status: str = "unsolved"
    flag: str | None = None
    source: str = "manual"
    remote_id: str | None = None
    solver: Mapping[str, object] | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _challenge_from_record(record: Mapping[str, object]) -> Challenge:
    points_value = record["points"]
    artifacts_value = record["artifacts"]
    solver_value = record["solver"]
    return Challenge(
        name=str(record["name"]),
        category=record["category"] if isinstance(record["category"], str) else None,
        points=points_value if type(points_value) is int else None,
        description=str(record["description"]),
        id=str(record["id"]),
        artifacts=(tuple(artifacts_value) if isinstance(artifacts_value, list) else ()),
        status=str(record["status"]),
        flag=record["flag"] if isinstance(record["flag"], str) else None,
        source=str(record["source"]),
        remote_id=(
            record["remote_id"] if isinstance(record["remote_id"], str) else None
        ),
        solver=solver_value if isinstance(solver_value, Mapping) else None,
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
    )


def _challenge_record(challenge: Challenge) -> dict[str, object]:
    return {
        "id": challenge.id,
        "name": challenge.name,
        "category": challenge.category,
        "points": challenge.points,
        "description": challenge.description,
        "artifacts": [dict(artifact) for artifact in challenge.artifacts],
        "status": challenge.status,
        "flag": challenge.flag,
        "source": challenge.source,
        "remote_id": challenge.remote_id,
        "solver": dict(challenge.solver) if challenge.solver is not None else None,
        "created_at": challenge.created_at,
        "updated_at": challenge.updated_at,
    }
