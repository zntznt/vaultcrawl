"""Drive the real Game through the HistorySystem and assert lore + fragments work.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_history
"""
from runtime.game import Game, load_manifest
from runtime.history import HistorySystem
from runtime.systems import System


class Spy(System):
    """A bus spy: records every event other systems emit (guidance/INTERACTIONS_SPEC.md)."""
    name = "spy"

    def __init__(self):
        self.events = []

    def on_event(self, game, etype, data):
        self.events.append((etype, dict(data)))


def main():
    g = Game(load_manifest("examples/world.json"))
    s = HistorySystem()

    # --- chronicle synthesis ---
    s.on_world_start(g)
    assert isinstance(s.lore, list) and s.lore, "lore must be a non-empty list"
    blob = " ".join(s.lore)
    assert ("Schism" in blob) or ("Age," in blob), \
        "lore must contain a Schism or a founding (Age) line"
    assert s.status_line(g) == "Lore: 0 read", "status_line should start at 0 read"

    # --- a fragment is buried on this floor ---
    s.on_floor_enter(g)
    assert s.ground, "on_floor_enter should bury a lore fragment (self.ground non-empty)"
    frag_xy = next(iter(s.ground))

    # the fragment is drawn as '?' on a floor cell
    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    fx, fy = frag_xy
    assert grid[fy][fx] == "?", "fragment should render as '?' on the map"

    # --- stand on the fragment and read it ---
    before_read = s.read
    before_log = len(g.messages)
    g.player.x, g.player.y = fx, fy
    s.on_player_act(g)

    assert s.read == before_read + 1, "reading a fragment should increment self.read"
    assert len(g.messages) > before_log, "reading should grow the message log"
    assert frag_xy not in s.ground, "the fragment should be consumed once read"
    assert isinstance(s.status_line(g), str), "status_line must return a string"
    assert "Lore: 1 read" in s.status_line(g)

    # standing on an empty tile does nothing
    log_now = len(g.messages)
    s.on_player_act(g)
    assert len(g.messages) == log_now, "no fragment underfoot -> no new messages"

    # --- interaction: lore reveals the map (bus) ---
    # Register history + a Spy on a real Game so emit() actually fires hooks.
    hist2 = HistorySystem()
    spy = Spy()
    g2 = Game(load_manifest("examples/world.json"), systems=[hist2, spy])
    assert hist2.lore, "history needs a chronicle to bury"
    # Place the player on a fragment tile, then act so the fragment is read.
    hist2.ground[(g2.player.x, g2.player.y)] = hist2.lore[hist2.read]
    hist2.on_player_act(g2)

    lore_events = [d for (et, d) in spy.events if et == "lore_read"]
    assert lore_events, "reading a fragment must emit a lore_read event on the bus"
    payload = lore_events[-1]
    assert set(payload) >= {"note", "region_id"}, \
        "lore_read payload must carry 'note' and 'region_id'"
    real_notes = set(g2.m.get("graph", {}).get("nodes", {}))
    real_regions = {r["id"] for r in g2.m.get("regions", [])}
    assert payload["note"] in real_notes, \
        "lore_read 'note' must be a real graph note id"
    assert payload["region_id"] is None or payload["region_id"] in real_regions, \
        "lore_read 'region_id' must be a real region id (or None)"
    print("lore_read payload:", payload)

    print("lore lines:", len(s.lore))
    for line in s.lore:
        print("  -", line)
    print("OK")


if __name__ == "__main__":
    main()
