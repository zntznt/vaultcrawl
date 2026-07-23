"""RoomProfiles — per-run learning: which room roles have traps, and where.
Berlin-compliant: every agent learns from rooms it enters. Cartographer learns
more because it explores more. No stat bonuses — just predictive safety."""
from __future__ import annotations


class RoomProfiles:
    """Tracks observed trap positions per room role across a single run.
    Stored on game.player._room_profiles."""

    def __init__(self):
        # role -> list of (dx, dy) trap positions relative to room center
        self.profiles: dict[str, list[tuple[int, int]]] = {}

    def record(self, role: str, trap_positions: list[tuple[int, int]], room_center: tuple[int, int]):
        """Record observed trap positions for a room role."""
        if role not in ("hub", "bridge", "leaf", "orphan", "cluster"):
            return
        cx, cy = room_center
        for tx, ty in trap_positions:
            self.profiles.setdefault(role, []).append((tx - cx, ty - cy))

    def predict(self, role: str, room_center: tuple[int, int]) -> list[tuple[int, int]]:
        """Predict trap positions for a room role based on past observations.
        Only predicts when the role has been seen at least once with traps."""
        if role not in self.profiles or not self.profiles[role]:
            return []
        cx, cy = room_center
        # Use the most common observed offset for each trap position
        predicted = []
        for dx, dy in self.profiles[role]:
            px, py = cx + dx, cy + dy
            if (px, py) not in predicted:
                predicted.append((px, py))
        return predicted[:2]  # max 2 predictions — conservative

    def role_for(self, manifest: dict, note_id: str) -> str:
        """Get the graph role for a note ID."""
        nodes = manifest.get("graph", {}).get("nodes", {})
        return nodes.get(note_id, {}).get("role", "leaf")
