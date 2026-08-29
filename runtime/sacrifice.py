"""Renunciation Shrine — permanent sacrifices for lasting power.

Found in deep z-levels (rare). Interacting offers 3 choices from a pool.
Each is a permanent trade-off: lose something now for a lasting benefit.
Rejecting all 3 causes the shrine to crumble — no second chance at that shrine.

Deterministic: shrine placement and offerings are seeded.
"""
from __future__ import annotations

import os
import random

from runtime.systems import System

# The five rewards, measured on one instrument: each granted from turn 0, 24 runs paired on
# (agent, seed), against a control that won 10 of 24 at mean floor 19.4.
#
#     +8 max HP     10/24   +0   floor 19.4   identical to control on every seed
#     +0.2 speed    10/24   +0   floor 19.4   byte-identical: player speed is never read
#     +2 sight      14/24   +4   floor 21.4
#     +1 ATK        17/24   +7   floor 22.0
#     +3 DEF        19/24   +9   floor 23.8
#
# TWO OF THE FIVE REWARDS WERE WORTH NOTHING. `sigil` paid +8 max HP and `rest` paid +5 max HP
# plus +0.2 speed, and the agent sits at 83% average HP, so a slightly higher ceiling changes
# no outcome; speed is worse than weak, it is inert, because `enemies_act` spends an energy
# budget over `self.actors` and the player is not in that list. `weather.py` also resets
# `player.speed` to 1.0 outright.
#
# The gains in SHRINE_GAIN were close to inversely ordered against this: `effect` was priced
# lowest at 5 while being the third strongest, `sigil` at 8 while being worth zero.
#
# Repriced onto the three currencies that measurably work, into a +4 to +9 band. Magnitudes
# marked INTERPOLATED were not measured at that exact value; the stat was measured at a
# neighbouring magnitude and scaled linearly, which is an assumption the combined arm below
# tests but does not isolate.
_OFFERINGS = [
    ("Renounce a Sigil Slot", "sigil", "Lose 1 max sigil capacity, gain permanent +2 ATK"),
    ("Renounce a Learned Note", "note", "Unlearn a note, gain permanent +1 ATK"),
    ("Renounce Matter", "matter", "Lose all carried matter, gain a sigil slot bearing Ward"),
    ("Renounce Rest", "rest", "Can no longer camp, gain permanent +3 sight radius"),
    ("Renounce an Effect", "effect", "Lose one effect, gain permanent +4 sight radius"),
]

# DEF is gone from this table, and the reason is arithmetic rather than taste.
#
# `dmg = max(1, att.atk - dfn.defense)`. Mean foe attack is 3.08 and the player already holds
# DEF 3 by the depth shrines appear at, so **91% of incoming hits at floor 13+ are already
# pinned at the minimum of 1** and further DEF changes nothing. That is why suppressing the
# shrine reward entirely cost 1 win in 138 and quadrupling it gained 1: two of the five
# renunciations were paying into a term that had already bottomed out.
#
# The previous pass chose DEF precisely because it measured strongest FROM TURN 0, where the
# player starts near DEF 0 and the subtraction still has room. Correct on that instrument,
# wrong for the position a shrine grants in. A late reward has to be paid in a currency that
# does not saturate.
#
# ATK does not. Measured at floor 13 and below: mean foe DEF **0.09**, and **0%** of player
# hits sit at the damage floor, so every +1 ATK is a full +1 damage on every swing, against a
# mean of 4.56. Early floors are 6% floored, so ATK is if anything better late than early.
#
# SIGHT is unverified at depth and is marked so. It cannot saturate arithmetically the way a
# subtraction does, but its value plainly falls once a room is already mapped, and no
# instrument here has separated those. The 0x / 1x / 4x arms below test the repriced set as a
# whole; they do not isolate sight.
SIGIL_ATK_GAIN = 2          # ATK verified non-saturating at shrine depth
NOTE_ATK_GAIN = 1           # measured: +1 ATK at +7 from turn 0
# `matter` pays in a SIGIL SLOT rather than a number, and this is the one reward chosen on
# route variety instead of on win rate.
#
# Granted at floor 13, the depth a shrine actually fires at, over 24 runs paired on
# (agent, seed) against a control that won 11 of 24:
#
#     nothing            11/24   standing 3, boss 7, commune 1                  3 routes
#     +2 standing (all)  12/24   standing 6, boss 4, commune 2                  3 routes
#     +3 known notes      9/24   standing 2, boss 7                             2 routes
#     +1 SIGIL SLOT      12/24   standing 5, commune 2, boss 2, truths 2,
#                                diplomacy 1                                    5 ROUTES
#
# No candidate moves the win rate, which by now is the expected result for anything handed
# over once past half depth.
#
# **The route-diversity result above DID NOT REPLICATE and this comment is the correction.**
# At 24 runs the slot showed five win routes against the control's three, which looked like
# the stated criterion moving where the win column did not. At 138 runs, with 28 slots
# actually granted, the picture is flat: five routes in both arms, and the top route's share
# of wins is 43% with the slot against 38% without it, so if anything marginally LESS varied.
# The caveat attached to the original claim, that 24 runs and 12 wins across five routes is
# thin, was the correct read and the replication is what settled it.
#
# The slot is kept anyway, on design grounds rather than measured ones, and the distinction
# matters: it is not better, it is not worse (75 wins against 74 with no reward at all), and
# it is the only reward in the pool that compounds mechanically rather than numerically. A
# slot holds a sigil, and a sigil can be cast, forged, upgraded, broken down, deployed and
# recovered, so it opens a subsystem for the rest of the run where +4 sight opened nothing.
# That is a reason to prefer it between two options measured as equal. It is not evidence.
MATTER_SLOT_GAIN = 1
MATTER_SLOT_ABILITY = "Ward"
REST_SIGHT_GAIN = 3         # UNVERIFIED at depth

# Scales every reward at the moment it is granted, so an arm can ask what a shrine reward is
# worth IN SITU rather than from turn 0.
#
# The distinction is the whole reason this exists. A turn-0 grant measures a currency's
# ceiling: +3 DEF from turn 0 is +9 wins in 24. A shrine fires about once per run and only
# past half depth, so the same currency handed over once, late, has a fraction of that to
# work with, and the first 138-run arm that changed two rewards from worthless to working
# moved the outcome by exactly zero. Suppressing and amplifying the reward around the
# shipped value bounds what one late grant is actually worth.
REWARD_PCT = int(os.environ.get("VC_SHRINE_REWARD_MULT", "100"))


def _reward(n: int) -> int:
    """Scale a reward, never rounding a live reward down to nothing by accident."""
    if REWARD_PCT <= 0:
        return 0
    return max(1, n * REWARD_PCT // 100)

# Named, because the offering text quotes it and the two drifted apart once already.
SIGHT_PER_RENUNCIATION = 4  # UNVERIFIED at depth

# What each renunciation is WORTH, before the cost of what it takes from you. These were five
# literals inside `_worth` chosen to be state-driven rather than measured, which was said
# plainly at the time and is now swept.
#
# `GAIN_PCT` scales all five together. That is deliberate: five gains swept independently is a
# five-dimensional space and roughly 1 shrine fires per run, so the arms would be
# indistinguishable long before the space was covered. One scalar asks the question the design
# actually has, which is whether the shrine is too eager or too reluctant, and the per-kind
# uptake table below says which individual gain to move next if any.
SHRINE_GAIN = {"sigil": 8, "note": 6, "matter": 9, "rest": 7, "effect": 5}
GAIN_PCT = int(os.environ.get("VC_SHRINE_GAIN_PCT", "100"))

# What each renunciation COSTS, as a function of how many you hold. These are the numbers the
# gain sweep pointed at: it came back flat across a 2.7x range of gains precisely because two
# offerings were priced against holdings the agent never reaches, and scaling a gain cannot
# rescue a cost written to the wrong scale.
#
# Measured over 4,710 sampled shrine states, the agent holds:
#
#     sigil slots   0 in 88% of states, then 1, 2, 3, 4. Never more than 4.
#     effects       0 in 68%, 1 in 32%. NEVER two.
#
# The old formulas reached zero cost at 6 slots and at 3 effects. Neither is attainable: the
# first is beyond anything observed, and the second never happens at all. So `sigil` was worth
# -2 at the only holding it commonly saw, `effect` was worth exactly 0 at the ONLY holding it
# ever sees, and zero is refused. Both were dead by arithmetic rather than by preference,
# chosen 0 times out of 25 and 60 dealings after the pool was filtered.
#
# Repriced against the distribution that exists. The shape is unchanged and it is the right
# shape: giving up your last one is dear, giving up a spare is cheap. Only the scale moves,
# from "zero at six" to "zero at four", which is the top of the observed range.
#
#     sigil    1 slot -> +2   2 -> +4   3 -> +6   4 -> +8
#     effect   1 -> +3
#
# For reference, what those compete against at a typical shrine: `rest` +7 while healthy,
# `note` +6 at the 12 to 13 notes agents carry, `matter` +7 to +9 when any is carried. So a
# last sigil slot at +2 is a marginal call that usually loses, and a spare fourth at +8 beats
# everything, which is what the fiction says it should do.
#
# EFFECT_STEP is a ramp the game currently never climbs: the agent is never observed holding
# two effects, so `effect` is in practice a flat cost of 2. The ramp stays so the formula
# remains sensible if the economy ever changes, and it is called out rather than pretended to
# be a curve.
SIGIL_COST_BASE, SIGIL_COST_STEP = 8, 2
EFFECT_COST_BASE, EFFECT_COST_STEP = 4, 2

# `rest` had no holdings axis at all: its cost was `0 if hp_pct >= 70 else 10`, and the agent
# is above 70% HP in 99% of sampled shrine states, so the cost was a constant zero and the
# offering a constant +7. It won 81% of the times it was dealt and was dealt more than
# anything else, which read as an imbalance to tune.
#
# It was not a tuning problem. `_cant_camp` gates the `on_town` branch of `Game.rest` and
# nothing else, `on_town` requires `_on_surface()`, and `_on_surface()` is
# `self.sandbox and self._dungeon is None`. **Classic descent is never on the surface**, so in
# the mode every measurement here runs in, renouncing rest takes away exactly nothing and
# grants +5 max HP, +5 HP and +0.2 speed permanently. A free buff, correctly identified as the
# best trade on the table by a `_worth` that was reporting the truth.
#
# Measured over 4,710 sampled shrine states: town rest healing is **0 in 100% of them**, while
# ordinary out-of-town resting has healed a median of 485 HP by the time a shrine is reached.
# The renunciation protects none of that.
#
# So `rest` is priced the same way as the other four: you can only renounce camping if camping
# has actually been doing something for you. In classic that is never, and the offering
# correctly leaves the pool. Where it does occur, the cost rises with how much the run has
# leaned on it.
#
# REST_COST_PER is UNMEASURED and deliberately flagged as such. Its SHAPE is evidenced, being
# the same "more reliance costs more" principle as the other four, but its scale cannot be
# calibrated from classic runs because the quantity is identically zero there. Sandbox has
# never been instrumented for this. Do not quote a balance claim from it until it has been.
REST_COST_PER = 25          # one point of cost per this much town-rest HP
REST_COST_CAP = 14          # never worse than twice the gain

# `note` cost `max(0, 10 - known)` and agents carry 11 to 15 notes, so the cost was zero
# across the ENTIRE observed range and the offering a constant +6. That is the same shape as
# `rest`'s HP term, and it made `note` take 57% of all choices and win 87% of its dealings
# once `rest` left the pool: the third constant cost curve found in this one function.
#
# It is the third and it is not the same fix, because `known` barely varies. Measured over
# 4,807 sampled shrine states the span is 11 to 15, median 13, so ANY curve over it is nearly
# flat and repricing cannot manufacture discrimination the input does not have. The base is
# instead placed INSIDE that span, which turns the five observed values into five different
# answers, +5 down to +1, where before they were one answer.
#
#     known    11   12   13   14   15
#     worth    +1   +2   +3   +4   +5
#
# The underlying asymmetry, stated because the number is compensating for it rather than
# fixing it: the player's base attack is 4, so `note`'s +1 ATK is a permanent +25% damage, and
# its cost is one of thirteen interchangeable notes. That is by some distance the strongest
# reward for the cheapest price in the pool, against +8 max HP on a base of 100 or +2 sight.
# Raising the cost brings the trade into line with the others; it does not make the five
# rewards comparable, and doing that is a design pass this is not.
NOTE_COST_BASE = 16


def _gain(kind: str) -> int:
    return SHRINE_GAIN.get(kind, 0) * GAIN_PCT // 100


class SacrificeSystem(System):
    name = "sacrifice"

    def __init__(self):
        self.shrines: dict[tuple, list] = {}  # (x,y) -> list of offering texts
        self._done: set = set()               # positions already used
        # "Renounce an Effect" promises "+2 sight radius" in its own offering text and
        # granted nothing: `apply` left a comment saying the bonus was "handled in
        # knowledge.py via _sight()", and `_sight()` had no such term. The offering was pure
        # loss. `knowledge._sight()` now reads this.
        self.sight_bonus: int = 0

    def on_world_start(self, game):
        self.shrines = {}
        self._done = set()
        self.sight_bonus = 0

    # Fraction of the descent below which no shrine appears. "Deep levels (rare)" needs a
    # depth axis, and the two modes do not share one.
    # How deep before shrines appear, as a fraction of the descent, and how likely one is on
    # a qualifying floor. Both are env-overridable because they are the two things the reward
    # sequence proved actually matter, and neither had ever been varied.
    #
    # Every reward experiment came back flat: magnitude 0x / 1x / 4x gave 76 / 77 / 78 wins,
    # a saturating currency against a non-saturating one gave 76-78 against 74-78, and a flat
    # stat against a compounding sigil slot gave 78 against 75. The same currencies measured
    # from turn 0 are worth a great deal, +1 ATK being +7 wins in 24. The difference is
    # entirely POSITION and FREQUENCY: at 0.5 and 0.30 a shrine fires about 0.84 times per
    # run and never before half depth, into a run whose trajectory is already set.
    # 0.0, so shrines appear from floor 1. Measured, 138 runs paired on (agent, seed):
    #
    #     depth  chance   taken/run   wins   deaths   floor   sd    vs shipped
    #     0.5    0.30       0.79       75      57      20.0   8.7   (shipped)
    #     0.0    0.30       2.38       88      46      21.7   7.8   p = 0.0725 MOVED
    #     0.0    0.60       4.45       92      42      21.7   8.1   p = 0.0300 MOVED
    #
    # This is the FIRST change in the whole shrine sequence to move the win column, after
    # magnitude, currency and kind all came back flat. It confirms what those null results
    # implied: the reward was never the problem, its position was.
    #
    # The rate stays at 0.30. Doubling it on top of the depth change is not distinguishable,
    # 88 to 92 at p = 0.6835, so it buys nothing measurable and would turn a rare event into
    # a commonplace one. Position is the lever; frequency, on this evidence, is not.
    DEPTH_FRACTION = float(os.environ.get("VC_SHRINE_DEPTH_FRACTION", "0.0"))
    PLACE_CHANCE = float(os.environ.get("VC_SHRINE_PLACE_CHANCE", "0.30"))
    MIN_FLOOR = int(os.environ.get("VC_SHRINE_MIN_FLOOR", "1"))
    SANDBOX_MIN_DEPTH = 2

    def _is_deep(self, game) -> bool:
        """Deep enough for a shrine, in whichever axis this mode actually moves.

        This used to be `if getattr(game, "current_z", 0) > -2: return`. `current_z` comes
        from `level.z` and is only ever non-zero in sandbox, so in CLASSIC DESCENT it is 0 on
        every floor and the guard rejected every one. The whole system was unreachable in the
        mode every measurement this project has ever taken was run in: 288-run baselines,
        three ablation sweeps, both quality sweeps. `ablate.py` reported dropping `sacrifice`
        as inert, which was true and told us nothing, because it was already inert.
        """
        z = getattr(game, "current_z", 0)
        if z < 0:                                    # sandbox: depth is the z axis
            return z <= -self.SANDBOX_MIN_DEPTH
        floor = getattr(game, "floor", 0)            # classic: depth is the floor number
        bottom = getattr(game, "max_floor", 0) or 0
        if bottom <= 0:
            return False
        # MIN_FLOOR was a bare `max(2, ...)`, which meant a depth fraction of 0 still could
        # not put a shrine on floor 1: the knob could be turned all the way down and the
        # thing it controls would not follow. Named, so "from floor 1" is expressible.
        return floor >= max(self.MIN_FLOOR, int(bottom * self.DEPTH_FRACTION))

    def on_floor_enter(self, game):
        self.shrines = {}
        if not self._is_deep(game):
            return
        rng = random.Random(f"{game.seed}:{game.floor}:sacrifice")
        if rng.random() > self.PLACE_CHANCE:
            return
        from runtime.dungeon import free_floor_tiles
        free = free_floor_tiles(game.level, {(game.player.x, game.player.y)})
        if not free:
            return
        pos = rng.choice(free)
        # Keyed on the FLOOR as well as the position. `_done` held bare (x, y), so a shrine
        # spent at (10, 10) on floor 3 silently blocked one at (10, 10) on floor 7. That was
        # nearly harmless while shrines only appeared past half depth on 30% of floors; with
        # them placeable from floor 1 it would suppress a real share of them, and the loss
        # would look like bad luck rather than a bug.
        if (game.floor, pos) in self._done:
            return
        # pick 3 distinct offerings
        picks = rng.sample(_OFFERINGS, min(3, len(_OFFERINGS)))
        self.shrines[pos] = picks
        game._overlay[pos] = "◊"

    def points_of_interest(self, game):
        """Tiles an autonomous agent may want to visit.

        The shrine had none, so once the depth gate was fixed it was placed on the map and
        still never reached: an agent has no reason to walk to a tile nothing advertises, and
        `interact` only fires on the tile you are standing on. Placement is not reachability,
        and a system can be revived into being just as dead as before.
        """
        return list(self.shrines)

    def render_overlay(self, game, grid):
        for (x, y) in self.shrines:
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
                grid[y][x] = "◊"

    def on_interact(self, game) -> bool:
        pos = (game.player.x, game.player.y)
        offers = self.shrines.pop(pos, None)
        if offers is None:
            return False
        self._done.add((game.floor, pos))
        game._overlay.pop(pos, None)
        # Filtered HERE rather than at placement, because placement happens on floor entry
        # and the agent reaches the shrine hundreds of turns later carrying something else
        # entirely. The state that matters is the state at the moment of the choice.
        offers = self.offers_for(game, offers)
        if not offers:
            game._pending_sacrifice = None
            game.log("The shrine offers nothing you have left to give. It crumbles.")
            self._record("shrine_offered")
            self._record("shrine_empty")
            return True
        game._pending_sacrifice = offers
        game.log("A shrine of renunciation hums before you. Choose, or reject.")
        # A curses front end answers this popup synchronously (runtime/play.py, key "a").
        # Nothing else does. An agent reaching the shrine therefore had it consumed, popped
        # from `self.shrines` and added to `_done` above, and received nothing at all: the
        # verb was strictly worse than not pressing it, and no agent could take a choice a
        # human walks through. That is a Berlin violation, and it is the second one found in
        # this codebase of the same shape.
        if not getattr(game, "has_ui", False):
            self.resolve(game, offers)
        return True  # consumed the interact

    @staticmethod
    def can_renounce(game, kind: str) -> bool:
        """Does the agent actually HOLD the thing this offering takes away?

        `_OFFERINGS` was sampled with no reference to the agent, so a shrine would offer to
        take a sigil slot from an agent with no sigil slots. `apply` then guarded that with
        `if sigs and sigs.slots` and silently performed the nothing half of the trade: the
        cost was skipped, the reward was granted, and a permanent buff came free.

        The sweep found it from the other end. Over 432 runs at three gain levels, `sigil`
        was dealt 252 times and chosen 0, `effect` dealt 233 and chosen 0, because their cost
        terms are calibrated for an agent holding several of each and the agent arrives at
        shrines with a median of 0 slots and 1 effect. Two of five offerings were dead and
        the choice was `matter` against `rest`.

        `rest` is the odd one: it takes away camping, which is a capability rather than an
        object, so what it needs is that the capability is still there to lose.
        """
        if kind == "sigil":
            sigs = game.system("sigils")
            return len(getattr(sigs, "slots", []) or []) >= 1
        if kind == "note":
            know = game.system("knowledge")
            return len(getattr(know, "known", ()) or ()) >= 1
        if kind == "matter":
            salv = game.system("salvage")
            return bool(salv) and salv.inventory(game).total() >= 1
        if kind == "rest":
            # Camping must have been worth something before it can be given up. In classic
            # descent `on_town` is unreachable, so this is False on every floor and `rest`
            # leaves the pool rather than acting as a free permanent buff.
            return (not getattr(game, "_cant_camp", False)
                    and getattr(game, "_town_rest_hp", 0) > 0)
        if kind == "effect":
            eff = game.system("effects")
            return len(getattr(eff, "collected", ()) or ()) >= 1
        return False

    def offers_for(self, game, picks):
        """The offers this shrine can actually make, given what the agent is carrying.

        The shrine's character is its placement draw and that is kept where possible: the
        three kinds it rolled, filtered to the ones the agent can pay. When an unlucky draw
        leaves nothing payable, it falls back to whatever the agent CAN renounce rather than
        crumbling, because a rare permanent opportunity lost to a draw is worse than one that
        offers a different trade. The fallback is sorted, so it is the same on any machine.
        """
        live = [o for o in picks if self.can_renounce(game, o[1])]
        if live:
            return live
        pool = [o for o in _OFFERINGS if self.can_renounce(game, o[1])]
        return sorted(pool, key=lambda o: o[1])[:3]

    def _worth(self, game, kind: str) -> int:
        """Score one offering from GAME STATE, never from the agent's identity.

        Every profile runs this identical function. What differs is what each arrives
        holding, which is exactly where this project's differentiation is allowed to come
        from: starting state and what the run has done since, never a class. An agent
        carrying nothing finds `matter` nearly free; one with five sigils finds `sigil`
        cheap; one that never camps loses nothing to `rest`.

        Returns gain minus cost. Non-positive means walk away, and walking away stays
        reachable: a shrine offering nothing this agent wants crumbles unspent.

        A thing you do not hold is worth nothing to renounce, and that check lives HERE
        rather than only in `offers_for`. Keeping them apart was a split brain: `resolve`
        scores whatever list it is handed, so an offering that slipped past the presentation
        filter was still priced as if the agent owned it, and `apply` grants its reward
        whether or not the cost landed. One source of truth closes that for every caller.
        """
        if not self.can_renounce(game, kind):
            return 0
        if kind == "sigil":
            sigs = game.system("sigils")
            slots = len(getattr(sigs, "slots", []) or [])
            # A spare slot is cheap, the last is not. Zero at 4 held, the top of the
            # observed range; it used to be zero at 6, which nothing ever reached.
            return _gain("sigil") - max(0, SIGIL_COST_BASE - SIGIL_COST_STEP * slots)
        if kind == "note":
            know = game.system("knowledge")
            known = len(getattr(know, "known", ()) or ())
            # Base sits inside the observed 11-to-15 span, so the five values the game
            # actually produces give five different answers instead of one.
            return _gain("note") - max(0, NOTE_COST_BASE - known)
        if kind == "matter":
            salv = game.system("salvage")
            held = salv.inventory(game).total() if salv else 0
            return _gain("matter") - min(9, held)               # free when broke, dear when rich
        if kind == "rest":
            # Priced on what the run has actually recovered by camping, not on current HP.
            # The HP form was inert: 99% of sampled shrine states are above 70%, so it was a
            # constant zero cost and `rest` a constant +7.
            used = getattr(game, "_town_rest_hp", 0)
            return _gain("rest") - min(REST_COST_CAP, used // REST_COST_PER)
        if kind == "effect":
            eff = game.system("effects")
            held = len(getattr(eff, "collected", ()) or ())
            # The agent is never observed holding two, so this is a flat cost of 2 in
            # practice. It used to be a cost of 5 against a gain of 5, worth exactly zero at
            # the only holding that occurs, and zero is refused.
            return _gain("effect") - max(0, EFFECT_COST_BASE - EFFECT_COST_STEP * held)
        return 0

    def resolve(self, game, offers) -> str:
        """Take the best offering on state, or reject all. Returns what was chosen ("" if
        rejected). Deterministic: ties break on the offering's own key, not on iteration
        order, so the same run makes the same choice on any machine."""
        scored = sorted(((self._worth(game, kind), kind) for _, kind, _ in offers),
                        key=lambda sk: (-sk[0], sk[1]))
        best, kind = scored[0] if scored else (0, "")
        # Every resolution is recorded, taken or not. `shrine_used` alone counts only the
        # takes, so a build where the agent refuses every shrine and one where it never
        # reaches a shrine report the same number, and those are opposite problems. Uptake is
        # a rate and a rate needs its denominator.
        self._record("shrine_offered")
        # Which kinds were on the table, not only which won. Without this, an offering that
        # never wins is indistinguishable from one the pool rarely deals, and the fix for
        # each is the opposite: raise its gain, or change what `_OFFERINGS` samples.
        for _n, k, _t in offers:
            self._record("", k, table="shrine_pool")
        if best <= 0 or not kind:
            self._record("shrine_rejected")
            game._pending_sacrifice = None
            game.log("You weigh the shrine's offer and turn away. It crumbles to dust.")
            return ""
        self.apply(game, kind)
        return kind

    @staticmethod
    def _record(key: str, kind: str = "", table: str = "shrine_choice"):
        try:
            from runtime.metrics import metrics
            m = metrics()
            if kind:
                d = m.systems.setdefault(table, {})
                d[kind] = d.get(kind, 0) + 1
            else:
                m.systems[key] = m.systems.get(key, 0) + 1
        except Exception:
            pass

    def apply(self, game, choice: str):
        """Apply the chosen sacrifice permanently."""
        if choice == "sigil":
            sigs = game.system("sigils")
            if sigs and sigs.slots:
                sigs.slots.pop()
            # Was +8 max HP (zero effect), then +2 DEF (also zero, the damage floor).
            game.player.atk += _reward(SIGIL_ATK_GAIN)
        elif choice == "note":
            know = game.system("knowledge")
            if know and know.known:
                # sorted: `known` is a set, so next(iter(...)) picked a different note
                # per process rather than per game seed.
                nid = next(iter(sorted(know.known)), None)
                if nid:
                    know.known.discard(nid)
            game.player.atk += _reward(NOTE_ATK_GAIN)
        elif choice == "matter":
            salv = game.system("salvage")
            if salv:
                bag = salv.inventory(game)
                if bag:
                    bag.comp = {}
            # Was +3 DEF, then +4 sight, both measured at nothing. A slot is the only
            # grant that moved route composition at this depth.
            sigs = game.system("sigils")
            if sigs is not None:
                for _ in range(_reward(MATTER_SLOT_GAIN)):
                    sigs.slots.append({"ability": MATTER_SLOT_ABILITY,
                                       "base": MATTER_SLOT_ABILITY, "durability": 3,
                                       "note": "shrine-forged", "role": "hub"})
        elif choice == "rest":
            game._resting = False
            game._consecutive_rest = 0
            game._cant_camp = True
            # Was +5 max HP and +0.2 speed. Max HP measured at zero effect; player speed is
            # never read at all, and `weather.py` resets it to 1.0 regardless.
            self.sight_bonus += _reward(REST_SIGHT_GAIN)
        elif choice == "effect":
            eff = game.system("effects")
            if eff and eff.collected:
                nid = next(iter(sorted(eff.collected)), None)
                if nid:
                    # `EffectSystem.collected` is a dict of archetype -> note id, and this
                    # said `.discard(nid)`, a set method. AttributeError on every call, the
                    # same shape as `structures.crystals.discard` in `clear_weather`. It
                    # never fired because `effect` was never once chosen, 0 of 233 dealings
                    # across a 432-run sweep, and `dispatch`'s `except Exception` would have
                    # swallowed it into a refused verb if it had. Filtering the offer pool to
                    # what the agent holds is what would have made it reachable.
                    eff.collected.pop(nid, None)
                    if eff.worn == nid:
                        eff.worn = None
            self.sight_bonus += _reward(SIGHT_PER_RENUNCIATION)
        # `shrine_used` existed in MetricsTracker from the start and nothing ever
        # incremented it, so "did a shrine fire" was unanswerable from any run's output.
        self._record("shrine_used")
        self._record("", choice)
        game._pending_sacrifice = None
        game.log(f"You accept the {choice} renunciation — the shrine crumbles, and you are changed.")
