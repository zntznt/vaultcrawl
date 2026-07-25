"""The canonical system stack, in one place.

There used to be four of these: `play.py` built 28 systems, `agent_eval.py` built 26
(no CraftSystem, no LocusSystem), `run_agents.py` built its own, and `balance_test.py`
a fourth. So the harness that produced every balance number the project quoted was
measuring a game without the craft rituals or the loci. Anything that needs the real
game builds it from here.

Order matters, and the reasons are load-bearing:
  - sigils first, so Echo can revive a just-killed player
  - reactions before the substrate writers (weather, flora, structures) so those see
    already-seeded tiles
  - salvage before forge: salvage pools the matter that forge spends
  - decay before fauna: scavengers query corpses
  - knowledge last, so its fog paints over every other overlay
"""
from __future__ import annotations


def build_systems() -> list:
    """Instantiate the full 28-system stack. Fresh objects every call: systems are stateful."""
    from .senses import SenseField
    from .memory import MemorySystem
    from .sigils import SigilSystem
    from .reactions import ReactionSystem
    from .weather import WeatherSystem
    from .flora import FloraSystem
    from .structures import StructureSystem
    from .decay import DecaySystem
    from .fauna import FaunaSystem
    from .salvage import SalvageSystem
    from .forge import ForgeSystem
    from .scent import ScentSystem
    from .quests import QuestSystem
    from .dialogue import DialogueSystem
    from .craft import CraftSystem
    from .machines import MachineSystem
    from .caches import CacheSystem
    from .terrain_mod import TerrainModSystem
    from .portals import PortalSystem
    from .sacrifice import SacrificeSystem
    from .factions import FactionSystem
    from .body_parts import BodySystem
    from .quality import QualitySystem
    from .history import HistorySystem
    from .marginalia import MarginaliaSystem
    from .loci import LocusSystem
    from .knowledge import KnowledgeSystem
    from .effects import EffectSystem
    from . import abilities  # noqa: F401  registers creature special actions

    return [
        SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
        FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
        SalvageSystem(), ForgeSystem(),
        ScentSystem(),
        QuestSystem(), DialogueSystem(), CraftSystem(), MachineSystem(),
        CacheSystem(),
        TerrainModSystem(),
        PortalSystem(),
        SacrificeSystem(),
        FactionSystem(), BodySystem(), QualitySystem(),
        HistorySystem(), MarginaliaSystem(), LocusSystem(), KnowledgeSystem(),
        EffectSystem(),
    ]


def register_brains() -> None:
    """Importing a brain module registers its tier, so this is the whole job."""
    from . import brains, tactics, creatures, planner, instincts  # noqa: F401
    from . import agent  # noqa: F401  universal brain, Berlin-compliant


def reset_run_state() -> None:
    """Clear every module-global that would otherwise leak from one run into the next.

    A harness runs hundreds of games in one process. Metrics were already reset; skills,
    proficiency and the chronicle were not, so run 300 of a batch started with tier-5
    foraging and diplomacy that run 1 had to earn. Measured on a fixed agent, world and
    seed: runs 1 and 2 reach floor 27 and win, runs 3 through 6 stall at floor 20 and die.
    Call this at the start of every run, not the end, so a crashed run cannot poison the
    next one.
    """
    try:
        from .proficiency import reset_proficiency
        reset_proficiency()
    except Exception:
        pass
    try:
        from .persistence import reset_chronicle
        reset_chronicle()
    except Exception:
        pass
    try:
        from .metrics import reset_metrics
        reset_metrics()
    except Exception:
        pass
