"""Drive the real Game through the WeatherSystem and assert the contract holds.

Weather is an ambient process keyed off the region ``element``: it names a mood
(static storm / rising damp / ember drift / cold snap / hallowed calm / acrid
haze / still air) and, on a slow cadence, nudges the reactions substrate on a
few random floor tiles. The example world's floor 1 is the corrosive region
(``acrid haze``), which sows acid — but the test is written generically so it
holds for whatever substrate-affecting element the sample floor happens to be.

We run a real descent with [ReactionSystem(), WeatherSystem()] so reactions
seeds the floor *before* weather names it, then:
  * assert ``current`` returns a non-empty word matching the region's element;
  * assert ``status_line`` echoes it;
  * cross the cadence and assert a NEW prop the weather is known to sow appeared
    in ``reactions.props`` (skipped only for the calm/still weathers, which by
    contract touch nothing).
Deterministic (seeded rng, no wall-clock); prints OK and exits 0.
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.weather import WeatherSystem, _WEATHER, WEATHER_PROPS, _CADENCE


def _triples(props):
    """Flatten {pos: {prop, ...}} into a set of (pos, prop) pairs."""
    return {(pos, p) for pos, s in props.items() for p in s}


def _check_mapping():
    """Every element resolves to its documented, non-empty weather word."""
    expected = {
        "charged": "static storm", "wet": "rising damp", "flammable": "ember drift",
        "frozen": "cold snap", "sacred": "hallowed calm", "corrosive": "acrid haze",
        "inert": "still air",
    }
    for element, word in expected.items():
        assert _WEATHER.get(element) == word, f"{element} -> {_WEATHER.get(element)}"
        assert word, "weather word must be non-empty"


def _check_guard_no_reactions():
    """With no reactions partner, weather still names itself and never raises."""
    g = Game(load_manifest("examples/world.json"), systems=[WeatherSystem()])
    w = g.system("weather")
    assert w.current(g), "weather must name itself even without a substrate"
    for _ in range(_CADENCE + 2):                # cross the cadence with no reactions present
        g.try_move(1, 0)
    assert w.current(g), "weather word survived turns without reactions"


def main():
    _check_mapping()
    _check_guard_no_reactions()

    # Real descent: reactions seeds the floor first, then weather names it.
    g = Game(load_manifest("examples/world.json"),
             systems=[ReactionSystem(), WeatherSystem()])
    reactions = g.system("reactions")
    weather = g.system("weather")

    element = g.region_for(g.floor).get("element", "inert")
    word = weather.current(g)

    # --- current() is a non-empty word that matches the region element ---
    assert word, "current(game) returned an empty weather word"
    assert word == _WEATHER.get(element, "still air"), (
        f"weather {word!r} does not match element {element!r}")
    assert weather.status_line(g) == f"Weather: {word}", weather.status_line(g)

    # --- cross the cadence and look for a substrate change attributable to weather ---
    before = _triples(reactions.props)
    # Drive the weather's own hook directly so the only writer to reactions.props is
    # the weather itself (reactions doesn't evolve the substrate here) — that makes the
    # new prop unambiguously the weather's doing. Plenty of ticks to clear the cadence.
    for _ in range(_CADENCE * 4):
        weather.on_player_act(g)
    after = _triples(reactions.props)
    new = after - before

    sows = WEATHER_PROPS.get(word, set())
    if sows:
        assert new, f"{word} produced no substrate change after {_CADENCE * 4} turns"
        assert any(prop in sows for (_pos, prop) in new), (
            f"{word} changed the substrate but with none of its props {sows}; saw {new}")
    else:
        # hallowed calm / still air are contractually inert — they must touch nothing
        assert not new, f"calm weather {word} should not change the substrate; saw {new}"

    print("OK")


if __name__ == "__main__":
    main()
