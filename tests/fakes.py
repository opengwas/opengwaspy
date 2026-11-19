"""Test doubles shared by the unit tests."""

from __future__ import annotations


class FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self, start: float = 1000.0, wall: float = 1_800_000_000.0) -> None:
        self.now = start
        self.wall = wall
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        self.wall += seconds
