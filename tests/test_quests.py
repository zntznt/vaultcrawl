"""Drive the real Game through the QuestSystem and assert the contract (DEEPEN_SPEC Agent A).

Covers: quests load from the manifest with concrete, kind-bound objectives; `offer` activates
a fresh quest; the matching bus trigger (an `enemy_killed` boss kill for slay, accrued matter
for recover) moves the quest into `completed`; and a deterministic reward is applied (faction
standing for slay, recovered matter for recover). FactionSystem / KnowledgeSystem / SalvageSystem
ride along so the rewards have real systems to write into.

Run: python3 -m tests.test_quests   (from the vaultcrawl project root)
"""
from runtime.components import inv, world_materials
from runtime.entities import make_boss
from runtime.factions import FactionSystem
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.quests import QuestSystem
from runtime.salvage import SalvageSystem


def _new_game():
    qs = QuestSystem()
    # rewards write into these; including them exercises the None-guarded cross-system calls
    g = Game(load_manifest("examples/world.json"),
             systems=[qs, FactionSystem(), KnowledgeSystem(), SalvageSystem()])
    return g, qs


def _offer_until(qs, g, kind):
    """Ensure at least one quest of `kind` is active (offering in manifest order); return it."""
    for q in qs.active:
        if q.get("kind") == kind:
            return q
    while True:
        offered = qs.offer(g)
        if offered is None:
            return None
        if offered.get("kind") == kind:
            return offered


def test_quests():
    g, qs = _new_game()

    # --- 1) quests load from the manifest, each bound to a checkable objective ----
    assert len(qs.quests) == len(g.m["quests"]), "every manifest quest is loaded"
    assert qs.quests, "the sample world defines quests"
    for q in qs.quests:
        assert q.get("objective"), "the displayed string is the transformed TODO objective"
        kind = q.get("kind")
        if kind == "slay":
            assert q.get("target_source") and q.get("target_boss_id"), \
                "slay binds to a concrete boss (id + source note)"
        elif kind == "recover":
            assert isinstance(q.get("need"), int) and q["need"] > 0, \
                "recover binds to an N-matter goal"
        elif kind in ("fetch", "escort"):
            assert q.get("band"), "fetch/escort binds to a target region depth band"
        elif kind == "cleanse":
            assert "region_id" in q, "cleanse binds to a region (for its reward)"

    # nothing active yet; the HUD reports 0 done out of the full slate
    assert qs.active == [], "quests start inactive — NPCs offer them"
    assert qs.completed == set(), "nothing completed yet"
    total = len(qs.quests)
    assert qs.status_line(g) == f"Quests: 0/{total}", qs.status_line(g)

    # --- 2) offer() activates the next fresh quest -------------------------------
    first = qs.offer(g)
    assert first is not None, "offer hands out a quest"
    assert any(a.get("id") == first["id"] for a in qs.active), "the offered quest is now active"
    assert first["id"] not in qs.completed

    # --- 3) SLAY: emit `enemy_killed` with the bound boss -> complete + reward ----
    slay = _offer_until(qs, g, "slay")
    assert slay is not None, "the world has a slay quest to drive"
    boss_spec = next(b for b in g.m["bosses"] if b["id"] == slay["target_boss_id"])
    assert boss_spec["sourceNoteId"] == slay["target_source"], "binding points at a real boss"

    factions = g.system("factions")
    fid = qs._faction_for_region(g, slay["region_id"])
    standing_before = factions.standing_of(fid)

    boss = make_boss(boss_spec, 1, 1)          # is_boss + source = the bound note
    g.emit("enemy_killed", enemy=boss, cause="melee")

    assert slay["id"] in qs.completed, "the slain boss completes the slay quest"
    assert slay not in qs.active, "a completed quest leaves the active list"
    assert slay.get("reward_applied"), "a reward was granted on completion"
    assert factions.standing_of(fid) > standing_before, \
        "slay reward raised the boss-region faction's standing"
    assert any(m == f"Quest complete: {slay['objective']}" for m in g.messages), \
        "completion is logged with the objective text"

    # --- 4) RECOVER: accrue N matter, then a tick lands it in completed + reward --
    recover = _offer_until(qs, g, "recover")
    assert recover is not None, "the world has a recover quest to drive"
    need = recover["need"]

    mat = (world_materials(g) or ["scrap"])[0]
    inv(g.player).add({mat: need})             # grow matter to the goal
    matter_at_goal = inv(g.player).total()
    g.emit("noise", pos=(g.player.x, g.player.y), volume=1)   # a tick re-checks objectives

    assert recover["id"] in qs.completed, "accrued matter completes the recover quest"
    assert recover.get("reward_applied"), "a reward was granted on completion"
    assert inv(g.player).total() > matter_at_goal, "recover reward paid out extra matter"

    # --- 5) HUD reflects the two completions; determinism on a fresh run ---------
    assert qs.status_line(g) == f"Quests: {len(qs.completed)}/{total}"
    assert len(qs.completed) >= 2

    g2, qs2 = _new_game()
    assert [q["id"] for q in qs2.quests] == [q["id"] for q in qs.quests], "load is deterministic"
    assert qs2.quests[0].get("kind") == qs.quests[0].get("kind")


def main():
    test_quests()
    print("OK")


if __name__ == "__main__":
    main()
