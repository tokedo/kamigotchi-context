"""Tests for executor/rooms_graph.py — pure pathfinding module."""

import sys
from pathlib import Path

import pytest

# Allow running `pytest tests/test_rooms_graph.py` from the executor/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rooms_graph  # noqa: E402


def _xy_adjacent(a: dict, b: dict) -> bool:
    """Return True if two room_info dicts are xy-adjacent on the same z."""
    if a["z"] != b["z"]:
        return False
    dx = abs(a["x"] - b["x"])
    dy = abs(a["y"] - b["y"])
    return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)


def test_trivial():
    assert rooms_graph.shortest_path(47, 47) == [47]


def test_simple_adjacent():
    # Room 3 is (3,4,1) Torii Gate, Room 2 is (3,3,1) Tunnel of Trees.
    # Adjacent on z=1 (y differs by 1), should be a 2-room path.
    assert rooms_graph.shortest_path(3, 2) == [3, 2]


def test_known_route_47_to_13():
    # 47 (3,7,1) Scrap Paths → 13 (4,3,2) Convenience Store.
    # Only z=1→z=2 entry to 13 is the special exit from room 2.
    path = rooms_graph.shortest_path(47, 13)
    assert path[0] == 47
    assert path[-1] == 13
    assert path[-2] == 2  # must enter 13 via the 2→13 special exit
    assert len(path) == 6  # 5 hops


def test_z_transition_requires_special_exit():
    # Any path crossing z-planes must include a non-xy-adjacent step.
    # Use 1 (z=1) → 88 (z=4) — definitely multi-plane.
    path = rooms_graph.shortest_path(1, 88)
    assert len(path) >= 2
    # At least one consecutive pair in the path must NOT be xy-adjacent
    # (i.e. a special-exit hop, which is the only way to change z).
    has_special = False
    for a_idx, b_idx in zip(path, path[1:]):
        a = rooms_graph.room_info(a_idx)
        b = rooms_graph.room_info(b_idx)
        if not _xy_adjacent(a, b):
            has_special = True
            break
    assert has_special, f"No special-exit hop in cross-z path: {path}"


def test_move_cost():
    assert rooms_graph.move_cost([47, 4, 30, 3, 2, 13]) == 25
    assert rooms_graph.move_cost([47]) == 0
    assert rooms_graph.move_cost([]) == 0


def test_unknown_room():
    with pytest.raises(ValueError):
        rooms_graph.shortest_path(47, 9999)
    with pytest.raises(ValueError):
        rooms_graph.shortest_path(9999, 47)


def test_all_rooms_reachable_from_room_1():
    # Sanity check: from the starting room, BFS must reach every
    # "In Game" room. If this fails, either a special exit is missing
    # from the CSV or there's a genuine gate-locked pocket — flag it.
    all_rs = rooms_graph.all_rooms()
    unreachable = []
    for r in all_rs:
        try:
            rooms_graph.shortest_path(1, r)
        except ValueError:
            unreachable.append(r)
    assert not unreachable, f"Rooms unreachable from room 1: {unreachable}"
