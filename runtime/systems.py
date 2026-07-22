"""Pluggable game systems.

game.py keeps an ordered list of System instances and calls these hooks at fixed points
in the turn loop. Every hook has a no-op default; a system overrides only what it needs.
Systems are self-contained: they read game state, mutate it through the public Game API,
and draw via render_overlay. They never edit each other or game.py.

Hook order per turn / event:
  end of Game.__init__       -> on_world_start(game)
  end of Game.descend()      -> on_floor_enter(game)      (floor built, spawns placed)
  end of Game.try_move()     -> on_player_act(game)        (after the player + enemies act)
  enemy reaches 0 hp         -> on_enemy_killed(game, enemy)
  inside Game.render()       -> render_overlay(game, grid) (grid[y][x] single chars)
  HUD assembly               -> status_line(game) -> str | None
"""
from __future__ import annotations


class System:
    name = "system"

    def on_world_start(self, game):
        pass

    def on_floor_enter(self, game):
        pass

    def on_player_act(self, game):
        pass

    def on_enemy_killed(self, game, enemy):
        pass

    def on_event(self, game, etype, data):
        """Cross-system bus. `etype` is an event name, `data` a dict payload.
        See INTERACTIONS_SPEC.md for the canonical events and the query API."""
        pass

    def render_overlay(self, game, grid):
        """grid is the final display buffer (tiles + items + actors + player already
        drawn) as a list of rows of single-char strings. Mutate in place. Convention:
        only overwrite floor cells ('.') unless you intentionally hide/reveal tiles."""
        pass

    def status_line(self, game):
        return None

    def on_interact(self, game) -> bool:
        """Called when the player presses the interact key. The tile under the player
        is checked against each system. Return True to consume the action and advance
        the turn; return False to pass to the next system."""
        return False

    def points_of_interest(self, game):
        """Tiles an autonomous agent may want to visit (sigils to grab, lore to read).
        Defaults to the keys of a `self.ground` dict if the system keeps one."""
        return list(getattr(self, "ground", {}) or {})

    def hazard_tiles(self, game):
        """Tiles an autonomous agent should avoid stepping on. Defaults to entries of a
        `self.props` dict whose property set intersects the damaging elements."""
        props = getattr(self, "props", None)
        if not props:
            return []
        damaging = {"fire", "acid", "charged"}
        return [xy for xy, kinds in props.items() if kinds & damaging]
