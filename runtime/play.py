"""Entry point.

    python -m runtime.play world.json --auto --floors 3   # headless, deterministic demo
    python -m runtime.play world.json                      # interactive curses (needs a TTY)

The auto-demo drives a BFS agent that descends toward the stairs and fights what blocks
it -- enough to show layout, depth-banded spawns, combat, and loot without a keyboard.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque

from .game import Game, load_manifest


def bfs_step(level, start, goal, avoid=None):
    """First (dx, dy) along the shortest floor path from start to goal, or None.
    Tiles in `avoid` are treated as blocked (except the goal itself)."""
    avoid = avoid or set()
    if start == goal:
        return (0, 0)
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        x, y = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in prev and level.walkable(*nxt) and (nxt not in avoid or nxt == goal):
                prev[nxt] = cur
                q.append(nxt)
    if goal not in prev:
        return None
    cur = goal
    while prev[cur] != start:
        cur = prev[cur]
    return (cur[0] - start[0], cur[1] - start[1])


def auto_play(game: Game, floors: int, max_turns: int = 500):
    """Drive the descent through the PLAYER'S BRAIN. The brain handles fight/flee/lure/loot;
    this loop only descends when the brain has nothing left to do on the floor, and nudges
    toward the stairs to avoid a stall."""
    transcript = [game.render()]
    cleared = 0
    while game.alive and not game.won and cleared < floors:
        turns = 0
        while game.alive and not game.won:
            ppos = (game.player.x, game.player.y)
            adj_threat = any(max(abs(a.x - ppos[0]), abs(a.y - ppos[1])) == 1
                             and game.hostile(game.player, a) for a in game.actors)
            has_poi = bool(game.items) or any(s.points_of_interest(game) for s in game.systems)
            if game.on_stairs() and not adj_threat and not has_poi:
                break
            dx, dy = game.player.brain.decide(game, game.player)
            if dx == 0 and dy == 0:
                if game.on_stairs():
                    break
                step = bfs_step(game.level, ppos, game.level.stairs)   # anti-stall
                if not step or step == (0, 0):
                    break
                dx, dy = step
            game.try_move(dx, dy)
            turns += 1
            if turns > max_turns:
                game.log("(no progress — abandoning floor)")
                break
        if not game.alive or game.won:
            break
        cleared += 1
        if cleared < floors:
            game.descend()
            transcript.append(game.render())
    return transcript, cleared


KEYS_HELP = ("move:hjkl+yubn  g:travel  >enter <climb .wait  x:examine t:speak e:effect m:log  "
             "z:toss c:cast f:forge b:breakdown  q:quit")
ABILITIES = ["Recall", "Phase", "Rally", "Ward", "Echo"]


def embody(game: Game, query: str) -> bool:
    """Take control of any entity in the world: the controlled actor is not a
    special kind of thing, so its stats, brainless keyboard turns, faction, and
    relations all just apply. Your old shell steps aside; the world's rules
    (kin, rivals, wildlife, territory) now read from your new body."""
    q = query.lower()
    for act in game.actors:
        if q in act.name.lower() or q in getattr(act, "source", "").lower():
            game.actors.remove(act)
            act.is_player = True
            act.brain = None      # the keyboard is the brain now
            game.player = act
            house = f", of {act.faction}" if act.faction else ""
            game.log(f"You wake behind other eyes: you are {act.name}{house}.")
            return True
    return False


SIDEBAR = 28   # column width reserved for the status panel
MSG_LINES = 5


def interactive(game: Game) -> int:
    import curses

    forge = game.system("forge")
    if forge is not None:
        forge.auto = False   # a human chooses when and what to craft

    palette: dict = {}   # glyph -> curses attr; filled once colors are up
    msg_rules: list = []  # (predicate, attr) for the message log

    def _init_palette():
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        for c in range(8):
            curses.init_pair(c + 1, c, -1)

        def P(c, extra=0):
            return curses.color_pair(c + 1) | extra

        R, G, Y, B = (curses.COLOR_RED, curses.COLOR_GREEN,
                      curses.COLOR_YELLOW, curses.COLOR_BLUE)
        M, C, W = curses.COLOR_MAGENTA, curses.COLOR_CYAN, curses.COLOR_WHITE
        BOLD, DIM = curses.A_BOLD, curses.A_DIM
        palette.update({
            "@": P(W, BOLD),
            # figure-ground: WALLS are the figure (solid white), floor recedes (dim),
            # roads are a quiet unified low value — not the brightest thing on screen
            "#": P(W), ".": P(W, DIM), "░": P(B, DIM), "·": P(W, DIM),
            # biome/block terrain in the wild — textured ground, tinted by region below
            '"': P(G, DIM), "`": P(Y, DIM),                       # scrub/reed · debris/slag
            "-": P(B, DIM), "|": P(W), "[": P(Y, DIM), "(": P(W, DIM),  # shallows·pipe·machine·tome
            "]": P(W, DIM), "!": P(Y, BOLD),                      # niche/alcove · spark-node
            ">": P(Y, BOLD), "<": P(Y, BOLD),                      # gates between realms
            ",": P(G), ";": P(G), "'": P(Y, DIM),                  # growth · dust
            "^": P(R, BOLD), "~": P(B), "/": P(Y, BOLD),           # fire · wet · charge
            # interior FIXTURES — made things, each its own color (design-panel step 1)
            "I": P(W, BOLD), "+": P(Y, BOLD), ":": P(C, BOLD),     # pillar · altar · stone
            "=": P(Y), "o": P(B, BOLD),                            # shelf · well
            "&": P(M), "_": P(R, DIM), "%": P(M, DIM),             # crystal · trap · corpse
            "*": P(Y, BOLD), "$": P(C, BOLD), "?": P(Y, BOLD),     # salvage · sigil · lore
            "F": P(B, BOLD), "T": P(B, BOLD),                      # machines
            "□": P(Y, BOLD),                                       # cache: an opportunity
            "P": P(C, BOLD), "M": P(M, BOLD),                      # keeper · boss
            "n": P(C, DIM), "z": P(C, DIM), "Y": P(C, DIM),        # wildlife
            # wild structures — landmarks strewn across the between (orphan notes)
            "A": P(W), "X": P(R, DIM), "H": P(M), "V": P(W, BOLD),  # cairn·wreck·shrine·monolith
        })
        for ch in "sgwrebch" + "qucmjkydfv":                        # the hostile bestiary
            palette[ch] = P(R)
        # spectral kinds (shades, echoes, revenants, wisps, gloom) read magenta
        for ch in "hejuk":
            palette[ch] = P(M)
        # a region's element paints its own places (never the whole app)
        for element, col in (("charged", Y), ("wet", B), ("flammable", R),
                             ("frozen", C), ("sacred", M), ("corrosive", G)):
            palette["el:" + element] = P(col)
        # an ENVIRONMENT's palette-lean: the whole vibe's color signature (blocks.py).
        # A place's wild terrain wears this, so crossing into a different vibe shifts hue.
        for lean, col, ex in (("cold", C, DIM), ("holy", M, 0), ("rust", Y, DIM),
                              ("verdant", G, 0), ("pale", W, DIM), ("harsh", Y, BOLD),
                              ("dim", W, DIM)):
            palette["pal:" + lean] = P(col, ex)
        msg_rules.extend([
            (lambda m: "hits you" in m or "strikes you down" in m or "You die" in m,
             P(R, BOLD)),
            (lambda m: "You destroy" in m or "You win" in m or "stands down" in m
             or "You integrate" in m, P(G, BOLD)),
            (lambda m: m.startswith(("You enter", "You stand", "You cross", "--")),
             P(W, BOLD)),
            (lambda m: m.startswith(("Marginalia", "You read")), P(Y)),
            (lambda m: m.startswith("Here,"), P(C)),
            (lambda m: m.startswith(("!!", "♛", "⚔", "✦", "†", "~ ")), P(M, BOLD)),
        ])

    def msg_attr(m):
        for pred, attr in msg_rules:
            if pred(m):
                return attr
        return 0

    def draw(scr, prompt=None):
        scr.erase()
        rows, cols = scr.getmaxyx()
        # size the viewport to the terminal: map box + sidebar + log must fit
        game.width = max(30, min(70, cols - SIDEBAR - 3))
        game.height = max(10, min(40, rows - MSG_LINES - 4))
        grid, (ox, oy) = game.compose_frame()
        vh, vw = len(grid), len(grid[0]) if grid else 0
        dim = palette.get("#", curses.A_DIM)

        def put(y, x, s, a=0):
            try:
                scr.addstr(y, x, s, a)
            except curses.error:
                pass

        # the map, boxed; the frame names the exact place you stand in, colored
        # by its region's element
        region = game.region_for(game.floor)
        idx0 = game.room_at(game.player.x, game.player.y)
        label = game.room_label(idx0) if idx0 is not None else None
        if label:
            title = f"┤ {label[0].upper() + label[1:]} · {game.region_name} ├"
        else:
            title = f"┤ {game.region_name} ├"
        t_attr = palette.get("el:" + region.get("element", ""),
                             palette.get("@", curses.A_BOLD)) | curses.A_BOLD
        put(0, 0, "┌" + "─" * vw + "┐", dim)
        put(0, 2, title[:vw - 2], t_attr)
        know = game.system("knowledge")
        try:
            from .knowledge import RADIUS
        except ImportError:
            RADIUS = 4
        px, py = game.player.x, game.player.y
        for y, row in enumerate(grid):
            put(y + 1, 0, "│", dim)
            put(y + 1, vw + 1, "│", dim)
            block_glyphs = getattr(game, "_block_glyphs", frozenset())
            for x, ch in enumerate(row):
                a = palette.get(ch, 0)
                wx, wy = ox + x, oy + y
                # ground + block terrain wears its ENVIRONMENT's palette-lean (the vibe
                # color), so crossing into a different atmosphere shifts the whole hue;
                # bare floor keeps the plain element tint, receding and dim.
                if ch in block_glyphs:
                    rid = game._region_of.get((wx, wy)) if hasattr(game, "_region_of") else None
                    env = getattr(game, "_region_env", {}).get(rid)
                    if env is not None:
                        a = palette.get("pal:" + env.palette(), a)
                elif ch in ".,'":
                    el = game._tint.get((wx, wy))
                    if el is not None:
                        a = palette.get("el:" + el, a) | curses.A_DIM
                elif ch == "#":
                    stance = game._frictions.get((wx, wy))
                    if stance == "war":
                        a = palette.get("^", a)                # a war-border burns
                    elif stance == "ally":
                        a = palette.get(":", a)                # accord, cyan
                if know is not None and max(abs(wx - px), abs(wy - py)) > RADIUS:
                    a |= curses.A_DIM   # remembered, not seen: the light model
                put(y + 1, 1 + x, ch, a)
        # Strong Centers: hearts and settlements are LANDMARKS, seen through fog
        for (lx, ly), kind in getattr(game, "_landmarks", {}).items():
            sx_, sy_ = lx - ox + 1, ly - oy + 1
            if 1 <= sx_ <= vw and 1 <= sy_ <= vh and (lx, ly) != (px, py):
                if kind == "heart":
                    put(sy_, sx_, "◆", palette.get("M", curses.A_BOLD))
                elif kind == "wild":
                    # a wild landmark: its glyph glows faintly through the fog, a target
                    gl = game._overlay.get((lx, ly), "*")
                    put(sy_, sx_, gl, palette.get(gl, 0) | curses.A_DIM)
                else:
                    put(sy_, sx_, ">", palette.get(">", curses.A_BOLD))
        put(vh + 1, 0, "└" + "─" * vw + "┘", dim)

        # sidebar: identity, vitals, then one line per live system
        sx = vw + 3
        p = game.player
        world = game.m.get("bible", {}).get("worldName", "vaultcrawl")
        put(0, sx, world[:cols - sx - 1], palette.get("@", curses.A_BOLD))
        tone = game.m.get("bible", {}).get("tone", "")
        if tone:
            put(3, sx, tone[:cols - sx - 1], curses.A_DIM)
        barw = 14
        fill = max(0, round(barw * max(0, p.hp) / p.max_hp))
        ratio = p.hp / p.max_hp
        hp_attr = (palette.get(":", 0) if ratio > 0.5
                   else palette.get("*", 0) if ratio > 0.25
                   else palette.get("^", curses.A_BOLD))
        put(1, sx, f"HP [{'=' * fill}{' ' * (barw - fill)}] {max(0, p.hp)}/{p.max_hp}",
            hp_attr)
        put(2, sx, f"ATK {p.atk}  DEF {p.defense}"
            + ("" if game.sandbox else f"   floor {game.floor}/{game.max_floor}")
            + (f"  DEBUG @({p.x},{p.y}) t{game.turn}"
               if getattr(game, "debug", False) else ""), 0)
        row = 4
        comps = [a for a in game.actors if a.allegiance == "companion"]
        if comps and row < vh:
            put(row, sx, f"With you ({len(comps)}):", palette.get("P", curses.A_BOLD))
            row += 1
            for a in comps[:3]:
                if row < vh:
                    put(row, sx, f" {a.name[:16]} {max(0, a.hp)}/{a.max_hp}",
                        palette.get("n", 0))
                    row += 1
            if len(comps) > 3 and row < vh:
                put(row, sx, f" ...and {len(comps) - 3} more", curses.A_DIM)
                row += 1
        # decision-relevant lines first: on a short terminal the ambience is
        # what falls off the bottom, never your build, wealth, or reputation
        order = ("sigils", "salvage", "factions", "quests", "knowledge",
                 "caches", "history", "marginalia", "machines", "dialogue")
        ranked = sorted(game.systems,
                        key=lambda s: (order.index(s.name)
                                       if getattr(s, "name", "") in order else 99))
        for s in ranked:
            line = s.status_line(game)
            if line and row < vh:
                put(row, sx, line[:cols - sx - 1], 0)
                row += 1

        # the log, colored by what happened, then the help / prompt line
        my = vh + 2
        for i, m in enumerate(game.messages[-MSG_LINES:]):
            put(my + i, 0, m[:cols - 1], msg_attr(m))
        if prompt:
            put(my + MSG_LINES, 0, prompt[:cols - 1], palette.get("*", curses.A_BOLD))
        else:
            keys = (("`:debug  " if getattr(game, "debug", False) else "") + KEYS_HELP)
            put(my + MSG_LINES, 0, keys[:cols - 1], curses.A_DIM)
        scr.refresh()

    def _wrap(lines, width):
        """Word-wrap a list of log lines to `width`, preserving blank separators."""
        import textwrap
        out = []
        for ln in lines:
            if not ln:
                out.append("")
            else:
                out.extend(textwrap.wrap(ln, width) or [""])
        return out

    def popup(scr, title, lines, footer="[any key]"):
        """A centered bordered window with word-wrapped, scrollable text — Qud's
        interaction modal. Nothing is lost: it holds every line, scrolls if tall."""
        rows, cols = scr.getmaxyx()
        w = min(max(40, cols - 8), cols - 2, 76)
        body = _wrap(lines, w - 4)
        vh = min(len(body), rows - 6)
        top = max(0, (rows - vh - 4) // 2)
        left = max(0, (cols - w) // 2)
        acc = palette.get("@", curses.A_BOLD)
        off = 0
        while True:
            for r in range(vh + 4):
                try:
                    scr.addstr(top + r, left, " " * w)
                except curses.error:
                    pass
            bar = "─" * (w - 2)
            try:
                scr.addstr(top, left, "┌" + bar + "┐", acc)
                t = f" {title} "
                scr.addstr(top, left + 2, t[:w - 4], acc)
                for i in range(vh):
                    scr.addstr(top + 1 + i, left, "│", acc)
                    scr.addstr(top + 1 + i, left + 2, body[off + i][:w - 4])
                    scr.addstr(top + 1 + i, left + w - 1, "│", acc)
                more = f"  ▼ {off + vh}/{len(body)}  ↑↓ scroll" if len(body) > vh else ""
                scr.addstr(top + 1 + vh, left, "├" + bar + "┤", acc)
                foot = (footer + more)[:w - 2]
                scr.addstr(top + 2 + vh, left, "│" + foot.ljust(w - 2) + "│", acc)
                scr.addstr(top + 3 + vh, left, "└" + bar + "┘", acc)
            except curses.error:
                pass
            scr.refresh()
            k = scr.getch()
            if k in (curses.KEY_DOWN, ord("j")) and off + vh < len(body):
                off += 1
            elif k in (curses.KEY_UP, ord("k")) and off > 0:
                off -= 1
            elif k in (curses.KEY_NPAGE, ord(" ")) and off + vh < len(body):
                off = min(off + vh, len(body) - vh)
            elif k in (curses.KEY_PPAGE,):
                off = max(0, off - vh)
            else:
                return k

    def show_log(scr):
        """Full scrollback of every message this run — Qud's message history."""
        popup(scr, "Message Log", list(game.messages), footer="[q/Esc close]")

    def menu(scr, title, options, lead=None):
        """A bordered choice window: options as a numbered list, returns index or None."""
        lines = list(lead or [])
        if lines:
            lines.append("")
        lines += [f"  {n + 1}. {o}" for n, o in enumerate(options)]
        k = popup(scr, title, lines, footer="[1-%d, other cancels]" % len(options))
        i = (k - ord("1")) if ord("1") <= k <= ord("9") else -1
        return i if 0 <= i < len(options) else None

    def negotiate_window(scr, foe):
        """A running conversation modal — the creature's lines and your moves
        accumulate in one scrollable transcript, moves chosen inside the window.
        This is where the note SPEAKS, so it must never scroll off a narrow line."""
        from .negotiate import MOVES, Parley
        p = Parley(game, foe)
        transcript = [f"You approach {foe.name}.",
                      f"({p.temperament}; mood {p.disposition:+d}/{p.goal})", "",
                      f'{foe.name}: "{p.speak(game, foe)}"']
        while p.outcome is None:
            body = list(transcript) + ["", "Your move:"] + \
                   [f"  {n + 1}. {mv}" for n, mv in enumerate(MOVES)] + \
                   ["  0. withdraw"]
            k = popup(scr, f"Parley — {foe.name}", body,
                      footer=f"mood {p.disposition:+d}/{p.goal}  [1-{len(MOVES)}, 0 leave]")
            if k in (ord("0"), ord("q"), 27):
                transcript.append("You withdraw.")
                break
            i = (k - ord("1")) if ord("1") <= k <= ord("9") else -1
            if not (0 <= i < len(MOVES)):
                continue
            transcript.append(f"> you {MOVES[i]}")
            transcript.append(p.hear(game, foe, MOVES[i]))
            if p.outcome is None:
                transcript.append(f'{foe.name}: "{p.speak(game, foe)}"')
        if p.outcome == "swayed":
            j = menu(scr, f"{foe.name} is won over",
                     ["part ways (it goes free)", "walk with me (recruit)"],
                     lead=transcript[-3:])
            line = p.resolve(game, foe, recruit=(j == 1))
            transcript.append(line)
        elif p.outcome is not None:
            transcript.append(p.resolve(game, foe))
        # a short closing card, and everything also lands in the log for scrollback
        popup(scr, f"Parley — {foe.name}", transcript[-8:], footer="[any key]")
        for ln in transcript:
            if ln and not ln.startswith(("(", "Your move", "  ")):
                game.log(ln)

    def pick(scr, prompt, count):
        """Prompt for a 1-based choice; returns a 0-based index or None."""
        draw(scr, f"{prompt} [1-{count}, other key cancels]")
        i = scr.getch() - ord("1")
        return i if 0 <= i < count else None

    _DIRKEYS = {curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
                curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
                ord("k"): (0, -1), ord("j"): (0, 1),
                ord("h"): (-1, 0), ord("l"): (1, 0),
                ord("y"): (-1, -1), ord("u"): (1, -1),
                ord("b"): (-1, 1), ord("n"): (1, 1)}

    def pick_dir(scr, prompt="toss which way?"):
        """Prompt for a direction (arrows/hjkl + diagonals yubn); (dx, dy) or None."""
        draw(scr, f"{prompt} [arrows/hjkl/yubn, other cancels]")
        return _DIRKEYS.get(scr.getch())

    def travel(scr):
        """Glide in a chosen direction until something worth stopping for. Turns one
        intention into real traversal across the wilderness; any key aborts. Stops on:
        a wall/edge, a new place entered, a region crossed, a discovery in reach, or a
        new (non-duplicate) log line — so every glide ends in an arrival."""
        d = pick_dir(scr, "travel which way?")
        if d is None:
            return
        dx, dy = d
        scr.nodelay(True)
        try:
            for _ in range(400):                      # hard cap; a glide is bounded
                px, py, msgs = game.player.x, game.player.y, len(game.messages)
                seen_before = set(game._rooms_seen)
                nx, ny = px + dx, py + dy
                if not game.level.walkable(nx, ny) or game.actor_at(nx, ny) is not None:
                    break                             # wall / edge / someone ahead
                # a discovery within one step -> stop and let the player choose
                if game._interest_near(nx, ny):
                    game.try_move(dx, dy)
                    break
                game.try_move(dx, dy)
                draw(scr)
                curses.napms(28)                      # a visible glide
                if not game.alive or game.won:
                    break
                if (game.player.x, game.player.y) == (px, py):
                    break                             # didn't move (blocked)
                if game._rooms_seen != seen_before:
                    break                             # entered a new place
                # a NEW, non-duplicate, NON-AMBIENT log line means something happened;
                # ambient mood lines (weather, a place's murmur) don't halt a glide
                if (len(game.messages) > msgs and not game.messages[-1].endswith(")")
                        and not getattr(game, "_last_was_ambient", False)):
                    break
                if scr.getch() != -1:
                    break                             # any key aborts
        finally:
            scr.nodelay(False)

    def run(scr):
        curses.curs_set(0)
        _init_palette()
        god = [False]     # debug: restored to full each action while on
        warp_at = [0]     # debug: warp-next cursor over the rooms
        moves = dict(_DIRKEYS)   # arrows + hjkl + diagonals (yubn) — follow any road
        while True:
            if god[0]:
                game.player.hp = game.player.max_hp
                game.alive = True
            draw(scr)
            if game.won or not game.alive:
                # a buffered keypress must not skip the final screen mid-mash
                curses.flushinp()
                end = "You win." if game.won else "You die."
                draw(scr, f"{end} Press q to leave.")
                while scr.getch() != ord("q"):
                    pass
                return
            k = scr.getch()
            # q only: bare ESC is dropped, because fast arrow-mashing can leak a
            # partial escape sequence that would otherwise quit the game mid-fight
            if k == ord("q"):
                return
            if k in moves:
                game.try_move(*moves[k])
            elif k == ord("g"):
                travel(scr)   # TRAVEL: pick a direction, glide until something happens
            elif k == ord(">") and game.on_stairs():
                game.descend()
            elif k == ord("<"):
                game.ascend()
            elif k in (ord("."), ord("5")):
                if game.on_stairs():
                    game.descend()   # legacy: `.` on the stairs still descends
                else:
                    game.wait()
            elif k == ord("x"):
                n = len(game.messages)
                game.examine()
                new = game.messages[n:]
                if new:
                    popup(scr, "You look around", new)
            elif k in (ord("m"), ord("P")):
                show_log(scr)   # full scrollable message history (nothing is lost)
            elif k == ord("e"):
                # wear an effect (Yume Nikki menu): switch your way of being
                eff = game.system("effects")
                if eff is None or not eff.collected:
                    game.log("You carry no effects yet. Commune with the lonely "
                             "things you find in the wild.")
                else:
                    from .effects import FEEL
                    got = sorted(eff.collected)
                    opts = [f"{e}  — {FEEL[e]}" for e in got] + ["wear nothing"]
                    i = menu(scr, "Effects", opts,
                             lead=[f"worn: {eff.worn or 'none'}"])
                    if i is not None:
                        eff.wear(got[i] if i < len(got) else None)
                        game.log(f"You wear the {eff.worn or 'nothing'}.")
            elif k == ord("t"):
                # speak: take an effect from a wild landmark, commune with the
                # deepest thought, parley with a Keeper, or becalm a hostile
                if game.commune_landmark() is not None:
                    pass
                elif game.commune() is None:
                    adj = [a for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                           for a in [game.actor_at(game.player.x + dx,
                                                   game.player.y + dy)]
                           if a is not None]
                    npc = next((a for a in adj if a.allegiance == "npc"), None)
                    foe = next((a for a in adj if a.allegiance == "monster"
                                and not a.is_boss), None)
                    friend = next((a for a in adj
                                   if a.allegiance in ("wild", "companion")
                                   and getattr(a, "source", "")), None)
                    if npc is not None:
                        game.emit("interact", target=npc, pos=(npc.x, npc.y))
                    elif foe is not None:
                        if getattr(foe, "_enraged", False):
                            game.log(f"{foe.name} will not hear you.")
                        else:
                            negotiate_window(scr, foe)
                            game.wait()   # the exchange costs the turn
                    elif friend is not None:
                        if game.confide(friend):
                            game.wait()   # secrets take a moment to trade
            elif k == ord("z"):
                d = pick_dir(scr)
                if d is not None and game.toss(*d):
                    game.wait()
            elif k == ord("`") and getattr(game, "debug", False):
                from . import debug as dbg
                tools = ["reveal all", "warp: heart", "warp: next place",
                         f"god mode {'OFF' if god[0] else 'ON'}", "warp: next gate",
                         "grant matter", "grant sigils", "smite (r8)", "inspect"]
                menu = " ".join(f"{n + 1}:{t}" for n, t in enumerate(tools))
                i = pick(scr, f"DEBUG {menu}", len(tools))
                if i == 0:
                    game.log(dbg.reveal_all(game))
                elif i == 1:
                    game.log(dbg.warp_heart(game))
                elif i == 2:
                    idxs = sorted(game.room_notes)
                    warp_at[0] = (warp_at[0] + 1) % len(idxs)
                    game.log(dbg.warp(game, idxs[warp_at[0]]))
                elif i == 3:
                    god[0] = not god[0]
                    game.log(f"god mode {'on' if god[0] else 'off'}")
                elif i == 4:
                    gates = sorted(game._gates)
                    if gates:
                        warp_at[0] = (warp_at[0] + 1) % len(gates)
                        game.player.x, game.player.y = gates[warp_at[0]]
                        game.log(f"warped to the gate toward "
                                 f"{game._gates[gates[warp_at[0]]]}")
                    else:
                        game.log("no gates on this map")
                elif i == 5:
                    game.log(dbg.grant_matter(game))
                elif i == 6:
                    game.log(dbg.grant_sigils(game))
                elif i == 7:
                    game.log(dbg.smite(game))
                elif i == 8:
                    for line in dbg.inspect(game):
                        game.log(line)
            elif k == ord("c"):
                # your verbs: slotted sigils AND your body's own actions (Qud
                # mutations: whatever you control, its capabilities are yours)
                sigs = game.system("sigils")
                slots = sigs.slots if sigs is not None else []
                body = list(getattr(game.player, "_special_actions", []) or [])
                opts = ([("sigil", n, s["ability"]) for n, s in enumerate(slots)]
                        + [("body", nm, nm) for nm in body])
                if not opts:
                    game.log("You have no verbs to cast: no sigils, no body actions.")
                    continue
                names = ", ".join(f"{n + 1}:{lbl}" for n, (_k, _r, lbl) in enumerate(opts))
                i = pick(scr, f"cast which? {names}", len(opts))
                if i is not None:
                    kind, ref, lbl = opts[i]
                    if kind == "sigil":
                        ok = sigs.cast(game, ref)
                    else:
                        from .abilities import player_cast
                        ok = player_cast(game, ref)
                        if not ok:
                            game.log(f"Your {lbl} finds no purchase here.")
                    if ok:
                        game.wait()   # a cast spends the turn; the world answers
            elif k == ord("f"):
                if forge is None:
                    continue
                names = ", ".join(f"{n + 1}:{a}" for n, a in enumerate(ABILITIES))
                i = pick(scr, f"forge which? {names}", len(ABILITIES))
                if i is not None:
                    if forge.forge(game, ABILITIES[i]):
                        game.wait()
                    else:
                        game.log("The forge does not answer (need a free slot and matter).")
            elif k == ord("b"):
                sigs, salv = game.system("sigils"), game.system("salvage")
                if not (sigs and salv and sigs.slots):
                    game.log("Nothing slotted to break down.")
                    continue
                names = ", ".join(f"{n + 1}:{s['ability']}" for n, s in enumerate(sigs.slots))
                i = pick(scr, f"break down which? {names}", len(sigs.slots))
                if i is not None:
                    salv.breakdown_sigil(game, sigs.slots[i]["ability"])
                    game.wait()

    curses.wrapper(run)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Play a baked vaultcrawl world.")
    ap.add_argument("world", help="path to world.json")
    ap.add_argument("--auto", action="store_true", help="run the headless auto-demo")
    ap.add_argument("--floors", type=int, default=3, help="auto-demo: floors to descend")
    ap.add_argument("--evolve-from", metavar="OLD",
                    help="play `world` with the chronicle from OLD->world overlaid as live upheaval")
    ap.add_argument("--width", type=int, default=56)
    ap.add_argument("--height", type=int, default=20)
    ap.add_argument("--no-systems", action="store_true",
                    help="disable the Qud/Cogmind-inspired systems layer (sigils, reactions, ...)")
    ap.add_argument("--descent", action="store_true",
                    help="play the classic floor-descent instead of the grown sandbox world")
    ap.add_argument("--embody", metavar="WHO",
                    help="play AS any entity: a name or note-id substring "
                         "(its stats, faction, and relations become yours)")
    ap.add_argument("--debug", action="store_true",
                    help="enable the in-game debug menu (backtick) and readout")
    ap.add_argument("--sprawl", type=float, default=2.0,
                    help="world-scale factor for the sandbox: bigger places, longer "
                         "ways between them (default 2.0; 1.0 = the old compact world)")
    ap.add_argument("--brain", default="exploiter",
                    help="player brain: exploiter (default), survivor, hunter/dumb")
    a = ap.parse_args(argv)

    manifest = load_manifest(a.world)
    upheaval = None
    if a.evolve_from:
        try:
            from vaultcrawl.evolve import evolve
        except ImportError:
            print("error: run from the project root so the `vaultcrawl` package is importable.",
                  file=sys.stderr)
            return 2
        from .upheaval import Upheaval
        events = evolve(load_manifest(a.evolve_from), manifest)
        upheaval = Upheaval.from_events(events)

    systems = []
    if not a.no_systems:
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
        from .quests import QuestSystem
        from .dialogue import DialogueSystem
        from .machines import MachineSystem
        from .caches import CacheSystem
        from .factions import FactionSystem
        from .history import HistorySystem
        from .marginalia import MarginaliaSystem
        from .knowledge import KnowledgeSystem
        from .effects import EffectSystem
        from .quality import QualitySystem
        from . import abilities  # noqa: F401  (registers creature special actions)
        # Order matters: sigils first (Echo can revive a just-killed player); reactions
        # before the substrate-writers (weather/flora/structures) so they see seeded
        # tiles; decay before fauna (scavengers query corpses); knowledge LAST so its fog
        # paints over every other overlay.
        systems = [SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
                   FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
                   SalvageSystem(), ForgeSystem(),   # salvage pools matter, then forge spends it
                   QuestSystem(), DialogueSystem(), MachineSystem(),   # objectives · NPCs · machines
                   CacheSystem(),   # each place is a distinct opportunity (CDDA)
                   FactionSystem(), QualitySystem(),   # quality grades all spawned foes (incl. hunters)
                   HistorySystem(), MarginaliaSystem(), KnowledgeSystem(),
                   EffectSystem()]   # Yume-Nikki ways-of-being (exploration, not power)

    headless = a.auto or not sys.stdin.isatty() or not sys.stdout.isatty()
    # The grown sandbox (ARCHITECTURE_SPEC) is the interactive game; the auto demo
    # and its brains still ride the classic descent (they steer by stairs).
    sandbox = not headless and not a.descent
    game = Game(manifest, a.width, a.height, upheaval=upheaval, systems=systems,
                sandbox=sandbox, sprawl=a.sprawl,
                site_cache=(a.world + ".site.json") if sandbox else None)
    game.debug = a.debug

    # Register the brain tiers (import = registration), then give the player its chosen
    # brain. Monsters get theirs lazily by tier via brain_for: tier-1 grunts charge (hunter),
    # tough foes/hunters/bosses scheme (tactician), wildlife forages.
    from . import (brains, tactics, creatures, planner, instincts)  # noqa: F401
    # ^ registers brain tiers (hunter…tactician/exploiter, mastermind/tracker/wary) + profiles
    from .sense import make_brain
    if a.embody:
        if not embody(game, a.embody):
            print(f"error: nothing in the world matches {a.embody!r}", file=sys.stderr)
            return 2
    game.player.brain = make_brain(game, game.player,
                                   name="hunter" if a.brain == "dumb" else a.brain)
    if headless:
        transcript, cleared = auto_play(game, a.floors)
        print("\n\n".join(transcript))
        outcome = "WON" if game.won else ("DIED" if not game.alive else f"descended {cleared} floor(s)")
        print(f"\n=== {outcome} | reached floor {game.floor} | "
              f"{game.kills} kills | {game.items_taken} items ===")
        return 0
    return interactive(game)


if __name__ == "__main__":
    raise SystemExit(main())
