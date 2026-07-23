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
    """Drive the descent through the PLAYER'S BRAIN. Supports AgentAction and legacy (dx, dy)."""
    from .agent_action import AgentAction, dispatch as _dispatch

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
            result = game.player.brain.decide(game, game.player)
            # Legacy compatibility: wrap (dx, dy) tuples
            if isinstance(result, tuple) and len(result) == 2:
                result = AgentAction("move", dx=result[0], dy=result[1])
            ok = _dispatch(game, result)
            if not ok:
                if game.on_stairs():
                    break
                step = bfs_step(game.level, ppos, game.level.stairs)   # anti-stall
                if not step or step == (0, 0):
                    break
                _dispatch(game, AgentAction("move", dx=step[0], dy=step[1]))
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


KEYS_HELP = ("move:hjkl+yubn  o:explore g:travel  >enter <climb .wait  x:examine t:speak e:effect m:log  "
              "z:toss c:cast f:forge b:breakdown  d:shield p:shove a:act  i:inspect Q:quests C:companions V:overworld  q:quit")
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
        # a place's color is its CHARACTER: vivid leans (a grove, a shrine, a forge)
        # burn bright; muted leans (ash, dust, waste) recede. This is the "colorful
        # or NOT, depending on the place" axis — brightness itself signals the mood.
        for lean, col, ex in (("verdant", G, BOLD), ("holy", M, BOLD), ("rust", R, BOLD),
                              ("harsh", Y, BOLD), ("cold", C, BOLD), ("bloom", M, BOLD),
                              ("gold", Y, BOLD),
                              ("pale", W, 0), ("dim", W, DIM), ("ash", W, DIM)):
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
        actors_at = {}
        for a in game.actors:
            actors_at[(a.x, a.y)] = a
        for y, row in enumerate(grid):
            put(y + 1, 0, "│", dim)
            put(y + 1, vw + 1, "│", dim)
            block_glyphs = getattr(game, "_block_glyphs", frozenset())
            for x, ch in enumerate(row):
                a = palette.get(ch, 0)
                wx, wy = ox + x, oy + y
                actor = actors_at.get((wx, wy))
                if actor is not None and getattr(actor, "quality", 0) > 0:
                    tier = actor.quality
                    qcol = [(G, BOLD), (B, BOLD), (M, BOLD), (Y, BOLD)][min(tier - 1, 3)]
                    a = curses.color_pair(qcol[0] + 1) | qcol[1]
                # THE PLACE HAS A COLOR: all of a region's ground — block terrain AND
                # bare floor AND grain — wears its palette-lean, so a whole place reads
                # in one hue and crossing a border visibly changes the world's color.
                # A vivid kind (grove/market) burns; a muted one (necropolis) recedes.
                if ch in block_glyphs or ch in ".,'`\"":
                    rid = game._region_of.get((wx, wy)) if hasattr(game, "_region_of") else None
                    lean = game.region_palette(rid) if hasattr(game, "region_palette") else None
                    if lean:
                        pa = palette.get("pal:" + lean)
                        if pa is not None:
                            # bare floor takes the hue but stays quieter than features
                            a = pa | (curses.A_DIM if ch == "." else 0)
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
        # waypoint beacon: a faint marker through the fog guiding toward the target
        wp = getattr(game, "_ow_waypoint", None)
        if wp is not None:
            wpx, wpy = wp
            sx_, sy_ = wpx - ox + 1, wpy - oy + 1
            if 1 <= sx_ <= vw and 1 <= sy_ <= vh and (wpx, wpy) != (px, py):
                put(sy_, sx_, "✦", palette.get("?", curses.A_BOLD))

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
        body = getattr(p, "body", None)
        if body:
            hh, th, lh = body["head"]["hp"], body["torso"]["hp"], body["legs"]["hp"]
            leg_tag = "!" if lh <= 0 else ""
            put(1, sx, f"HP H{hh} T{th} L{leg_tag}{lh} [{'=' * fill}] {max(0, p.hp)}/{p.max_hp}",
                hp_attr)
        else:
            put(1, sx, f"HP [{'=' * fill}{' ' * (barw - fill)}] {max(0, p.hp)}/{p.max_hp}",
                hp_attr)
        put(2, sx, f"ATK {p.atk}  DEF {p.defense}"
            + (f"  items {game.items_taken}" if game.items_taken else "")
            + ("" if game.sandbox else f"   floor {game.floor}/{game.max_floor}")
            + (f"  DEBUG @({p.x},{p.y}) t{game.turn}"
               if getattr(game, "debug", False) else ""), 0)
        row = 3
        # active effects — shield, enrage, bleeding, etc.
        effs = []
        sh = getattr(p, "_shield_bonus", 0)
        if sh: effs.append(("Shield +" + str(sh), palette.get("n", 0)))
        en = getattr(p, "_enrage_stacks", 0)
        if en: effs.append(("Enrage +" + str(en), palette.get("*", curses.A_BOLD)))
        if getattr(p, "speed", 1.0) > 1.0: effs.append(("Haste", palette.get("n", 0)))
        if getattr(p, "speed", 1.0) < 1.0 and getattr(p, "speed", 1.0) > 0:
            effs.append(("Slow", palette.get("^", 0)))
        for tag, tag_attr in [("Bleed " + str(getattr(p, "_bleeding", 0)),
                               palette.get("^", curses.A_BOLD)),
                              ("Staggered", palette.get("^", curses.A_BOLD)),
                              ("Winded", palette.get("^", 0)),
                              ("Slowed " + str(getattr(p, "_slowed", 0)) + "t",
                               palette.get("^", 0))]:
            if tag.split()[0] not in "".join(e[0] for e in effs):
                val = getattr(p, tag.lower().split()[0] if " " not in tag else
                             "_" + tag.lower().split()[0], 0)
                if val > 0: effs.append((tag, tag_attr))
        if effs:
            put(row, sx, "  ".join(tag for tag, _ in effs)[:cols - sx - 1], 0)
            row += 1
        if getattr(game, "_resting", False):
            put(row, sx, "RESTING", palette.get("*", curses.A_BOLD))
            row += 1
        # tension indicator
        t = getattr(game, "_tension", 0)
        if t >= 50:
            tc = palette.get(":", 0) if t < 100 else (palette.get("*", 0) if t < 200 else palette.get("^", curses.A_BOLD))
            put(row, sx, f"Tension: {t}", tc)
            row += 1
        # region aspect
        asp = getattr(game, "_aspect", "")
        if asp:
            put(row, sx, asp[:cols - sx - 1], palette.get("?", curses.A_BOLD))
            row += 1
        row = max(row, 4)
        comps = [a for a in game.actors if a.allegiance == "companion"]
        if comps and row < vh:
            put(row, sx, f"With you ({len(comps)}):", palette.get("P", curses.A_BOLD))
            row += 1
            for a in comps[:3]:
                if row < vh:
                    tags = []
                    if getattr(a, "_bleeding", 0): tags.append("B")
                    if getattr(a, "_staggered", 0): tags.append("!")
                    if getattr(a, "_slowed", 0): tags.append("~")
                    eff = " " + "".join(tags) if tags else ""
                    put(row, sx, f" {a.name[:14]}{eff} {max(0, a.hp)}/{a.max_hp}",
                        palette.get("n", 0))
                    row += 1
            if len(comps) > 3 and row < vh:
                put(row, sx, f" ...and {len(comps) - 3} more", curses.A_DIM)
                row += 1
        # decision-relevant lines first: on a short terminal the ambience is
        # what falls off the bottom, never your build, wealth, or reputation
        order = ("sigils", "salvage", "effects", "factions", "quests", "knowledge",
                 "caches", "history", "marginalia", "machines", "dialogue", "body", "terrain")
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
            elif k in (curses.KEY_HOME, ord("g")) and off > 0:
                off = 0
            elif k in (curses.KEY_END, ord("G")) and off + vh < len(body):
                off = max(0, len(body) - vh)
            else:
                return k

    def show_log(scr, tag=""):
        """Full scrollback with optional category filter."""
        msgs = list(game.messages)
        tags = getattr(game, "message_tags", [])
        if tag and tags and len(tags) == len(msgs):
            msgs = [m for m, t in zip(msgs, tags) if t == tag]
        title = f"Message Log — {tag}" if tag else "Message Log"
        k = popup(scr, title, msgs or ["(no messages in this category)"],
                  footer="m:all  c:combat  d:discovery  a:ambient  q/esc close")
        if k == ord("m"):
            show_log(scr, "")
        elif k == ord("c"):
            show_log(scr, "combat")
        elif k == ord("d"):
            show_log(scr, "discovery")
        elif k == ord("a"):
            show_log(scr, "ambient")

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

    def _capture(fn, *a, **kw):
        """Run a verb that logs its result and RETURN the lines it appended, so a
        talk window can show the response in its own transcript. Returns (ret, lines)."""
        before = len(game.messages)
        ret = fn(*a, **kw)
        return ret, list(game.messages[before:])

    def dialog_frame(scr, name, transcript, verbs, topics, face=None, stats=None,
                     face_attr=0):
        """The ONE unified conversation frame — every talk uses it, so it can be styled
        once, here, later. Two kinds of choice, deliberately in different places:

          * NAME in the TOP border, with a STATS line (stance/grade/house/links) just
            beneath it — the metrics the window used to waste its space not showing.
          * a procedural PORTRAIT of the interlocutor at the top of the body.
          * the running exchange fills the BODY (auto-scrolled to the latest line);
            the creature's words are quoted BARE (no name prefix — it's on the border).
          * the STANDARD mechanical VERBS (same for every creature) render along the
            BOTTOM BORDER — the fixed, universal frame.
          * this creature's EXCLUSIVE dialogue TOPICS list inside the BODY (they are
            not standard; they depend on the creature, so they live in the content).

        Choices are numbered continuously: verbs 1..V, then topics V+1..V+T. Returns the
        chosen 0-based index (into verbs+topics), or None to leave."""
        rows, cols = scr.getmaxyx()
        w = min(max(48, cols - 6), cols - 2, 84)
        left = max(0, (cols - w) // 2)
        acc = palette.get("@", curses.A_BOLD)
        nv = len(verbs)
        stat_line = "  ·  ".join(stats) if stats else ""
        # the verb bar can wrap across a couple of border rows if there are many
        labels = [f"{n + 1}·{v}" for n, v in enumerate(verbs)] + ["0·leave"]
        bar_rows, cur = [], ""
        for lab in labels:
            if len(cur) + len(lab) + 2 > w - 4:
                bar_rows.append(cur.rstrip())
                cur = ""
            cur += lab + "  "
        if cur.strip():
            bar_rows.append(cur.rstrip())
        # the STATS line + portrait form the fixed header (both pinned above the scroll)
        art = []
        if stat_line:
            art.append(stat_line[:w - 4])
        if face:
            fw = max((len(r) for r in face), default=0)
            pad = max((w - 4 - fw) // 2, 0)
            art += [" " * pad + r for r in face]
        if art:
            art.append("")
        # topics live in the body, appended under the exchange
        topic_lines = ([""] + [f"  {nv + n + 1}. {lbl}" for n, (lbl, _) in
                               enumerate(topics)]) if topics else []
        while True:
            # the portrait is a FIXED header (art); only the exchange+topics scroll
            scroll = _wrap(transcript, w - 4) + topic_lines
            body = art + scroll                       # art pinned at top
            vh = max(3, min(len(body), rows - 6 - len(bar_rows)))
            top = max(0, (rows - vh - 4 - len(bar_rows)) // 2)
            # scroll the CONTENT under the fixed portrait to its newest line
            scroll_vh = max(1, vh - len(art))
            view = art + scroll[max(0, len(scroll) - scroll_vh):]
            bar = "─" * (w - 2)
            try:
                for r in range(vh + 3 + len(bar_rows)):
                    scr.addstr(top + r, left, " " * w)
                scr.addstr(top, left, "┌" + bar + "┐", acc)
                nm = f" {name} "
                scr.addstr(top, left + 2, nm[:w - 4], acc)
                for i in range(vh):
                    scr.addstr(top + 1 + i, left, "│", acc)
                    if i < len(view):
                        # the portrait rows wear the creature's element colour; the
                        # first stat row and the exchange stay plain
                        ra = face_attr if (face and 1 <= i < 1 + len(face)) else 0
                        scr.addstr(top + 1 + i, left + 2, view[i][:w - 4], ra)
                    scr.addstr(top + 1 + i, left + w - 1, "│", acc)
                scr.addstr(top + 1 + vh, left, "├" + bar + "┤", acc)
                for j, brow in enumerate(bar_rows):
                    scr.addstr(top + 2 + vh + j, left,
                               "│ " + brow.ljust(w - 4) + " │", acc)
                scr.addstr(top + 2 + vh + len(bar_rows), left, "└" + bar + "┘", acc)
            except curses.error:
                pass
            scr.refresh()
            k = scr.getch()
            if k in (ord("0"), ord("q"), 27):
                return None
            i = (k - ord("1")) if ord("1") <= k <= ord("9") else -1
            if 0 <= i < nv + len(topics):
                return i

    # every interlocutor offers the SAME verbs — roguelike doctrine: all options are
    # always available. The target's NATURE decides the OUTCOME (a hostile rebuffs your
    # offering, a Keeper has no truce to strike), never which options you may attempt.
    TALK_VERBS = ("Speak with it", "Ask its history", "Offer matter",
                  "Confide a truth", "Seek a truce")

    def _talk_do(target, verb, nid):
        """Resolve one talk verb against any target; returns the response lines. Every
        verb works on everything — the effect just depends on what the target is. The
        creature's own words are quoted BARE (no name prefix — the name is on the
        border already); narration of what happens is plain prose."""
        if verb == "Speak with it":
            line = game._weave_note(nid, salt=f"speak:{game.turn}") if nid else ""
            return [f'"{line}"'] if line else ["It says nothing you can hold."]
        if verb == "Ask its history":
            h = game._note_history(nid, salt="talk") if nid else ""
            return [h] if h else ["It has no past you can read."]
        if verb == "Offer matter":
            _r, lines = _capture(game.becalm, target)  # an offering placates a hostile;
            return [_strip_name(ln, target) for ln in lines] or \
                   ["It has no need of your matter."]   # else no-op
        if verb == "Confide a truth":
            _r, lines = _capture(game.confide, target)
            return [_strip_name(ln, target) for ln in lines] or \
                   ["It has no secret to trade."]
        if verb == "Seek a truce":
            if target.allegiance == "monster" and not target.is_boss \
                    and not getattr(target, "_enraged", False):
                return None   # sentinel: hand off to the full SMT parley
            return ["It is not at war with you." if target.allegiance != "monster"
                    else "It will not hear you."]
        return [""]

    def _strip_name(line, target):
        """Verbs that log 'Name does X' get the leading name trimmed, since the window
        already shows it. 'Foo stills.' -> 'It stills.'"""
        if line.startswith(target.name + " "):
            return "It " + line[len(target.name) + 1:]
        return line

    def talk_window(scr, target):
        """The one conversation surface for EVERY interlocutor. Name at the top border,
        the exchange in the body, the choices as a numbered list with the hint in the
        bottom border — the same modal as examine, consistent across the board.

        Two layers of choices: the fixed MECHANICAL verbs (offer/confide/truce/...),
        the SAME for every creature (roguelike all-options doctrine), then this note's
        EXCLUSIVE dialogue topics (what it links to, its concerns) — those may differ
        per creature, since dialogue is born from what the note actually is."""
        nid = getattr(target, "source", "")
        topics = game.dialogue_topics(nid) if nid else []
        opening = game._weave_note(nid, salt="talk") if nid else ""
        transcript = [f'"{opening}"' if opening else "It regards you."]
        # a Spore-style procedural PORTRAIT, built from the creature's own traits
        from .portrait import portrait
        arch, dmg = game.creature_look(target)
        face = portrait(arch, nid, getattr(target, "tier", 1),
                        getattr(target, "quality", 0), dmg)
        stats = game.creature_stats(target)   # readable metrics under the name
        # the portrait wears the creature's ELEMENT colour (arc gold, flame red,
        # frost cyan, ...), so a face reads as its nature at a glance
        _DMG_GLYPH = {"flame": "^", "frost": ":", "arc": "!", "venom": ";",
                      "decay": "%", "psychic": "M", "blade": "|"}
        face_attr = palette.get(_DMG_GLYPH.get(dmg, ""), 0)
        while True:
            i = dialog_frame(scr, target.name, transcript, TALK_VERBS, topics,
                             face, stats, face_attr)
            if i is None:
                break
            if i < len(TALK_VERBS):
                label = TALK_VERBS[i]
                lines = _talk_do(target, label, nid)
                if lines is None:             # truce with a hostile -> full parley
                    negotiate_window(scr, target)
                    return True
            else:
                label, resp = topics[i - len(TALK_VERBS)]
                lines = [f'{target.name}: "{resp}"']
            transcript.append(f"> {label.lower()}")
            transcript += [ln for ln in lines if ln]
        return True

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

    def autoexplore(scr):
        """Autoexplore: BFS toward nearest fog edge. Stops on monsters, items, rooms, damage."""
        know = game.system("knowledge")
        if know is None:
            game.try_move(1, 0)
            return
        seen = know.seen.get(game.floor, set())
        px, py = game.player.x, game.player.y
        # find nearest unseen floor tile within 20 tiles
        best, bd = None, 999
        for y in range(max(0, py - 20), min(game.level.h, py + 21)):
            for x in range(max(0, px - 20), min(game.level.w, px + 21)):
                if game.level.walkable(x, y) and (x, y) not in seen:
                    d = max(abs(x - px), abs(y - py))
                    if d < bd:
                        best, bd = (x, y), d
        if best is None:
            game.log("Nothing unexplored nearby.")
            return
        step = bfs_step(game.level, (px, py), best)
        if step is None or step == (0, 0):
            return
        game.try_move(*step)
        draw(scr)
        """Glide in a chosen direction until something worth stopping for. Turns one
        intention into real traversal across the wilderness; any key aborts. Stops on:
        a wall/edge, a new place entered, a region crossed, a discovery in reach, or a
        new (non-duplicate) log line — so every glide ends in an arrival."""
        d = pick_dir(scr, "travel which way?")
        if d is None:
            return
        dx, dy = d
        scr.nodelay(True)
        steps = 0
        try:
            for _ in range(400):                      # hard cap; a glide is bounded
                steps += 1
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
            if steps > 1:
                game.log(f"Travelled {steps} paces.", ambient=True)

    def _can_overlook(game):
        idx = game.room_at(game.player.x, game.player.y)
        if idx is not None and getattr(game, "_places", None):
            for pl, c in game._places:
                if pl.contains(game.player.x, game.player.y) and c.intensity >= 0.5:
                    return True
        return (game.player.x, game.player.y) in getattr(game, "_gates", {})

    def quest_log(scr):
        qs = game.system("quests")
        if qs is None:
            game.log("No quest system active.")
            return
        lines = []
        if qs.active:
            lines.append("─ Active ─")
            for q in qs.active:
                obj = q.get("objective", q.get("id", "?"))
                prog = qs.quest_progress(game, q)
                reward = qs.quest_reward_text(q)
                lines.append(f"▸ {obj[:50]}")
                lines.append(f"  progress: {prog}  ·  reward: {reward}")
        if qs.completed:
            lines.append("─ Completed ─")
            for q in qs.quests:
                if q.get("id") in qs.completed:
                    lines.append(f"✓ {q.get('objective', q.get('id', '?'))[:50]}")
        if not lines:
            lines = ["No quests yet. Seek a Keeper in town."]
        popup(scr, "Quests", lines)

    def companion_panel(scr):
        comps = [a for a in game.actors if a.allegiance == "companion"]
        if not comps:
            game.log("No companions walk with you.")
            return
        lines = []
        for c in comps:
            body = getattr(c, "body", None)
            hp_str = f"HP {max(0, c.hp)}/{c.max_hp}"
            if body:
                parts = [f"{p[0]}{body[p]['hp']}" for p in ("head", "torso", "legs")]
                hp_str = f"HP {' '.join(parts)} [{c.hp}/{c.max_hp}]"
            effs = []
            if getattr(c, "_bleeding", 0): effs.append("bleeding")
            if getattr(c, "_staggered", 0): effs.append("staggered")
            if getattr(c, "_slowed", 0): effs.append(f"slowed {c._slowed}t")
            eff = " · " + " ".join(effs) if effs else ""
            lines.append(f"{c.name[:20]}  {hp_str}")
            lines.append(f"  tier {c.tier}  ·  {c.faction or 'no house'}{eff}")
            if len(lines) >= 30:
                break
        popup(scr, f"Companions ({len(comps)})", lines)

    def completion_plaque(scr):
        nodes = game.m.get("graph", {}).get("nodes", {})
        know = game.system("knowledge")
        lines = []
        total, seen = len(nodes), 0
        for nid, nd in sorted(nodes.items(), key=lambda kv: kv[0]):
            role = nd.get("role", "?")
            known = "◆" if (know and nid in know.learned) else ("◎" if (know and nid in know.known) else "☐")
            title = nd.get("title", nid)[:30]
            depth = nd.get("pagerank", 0)
            d_tag = f"←{max(1, int(depth * 10))}" if depth else ""
            lines.append(f"{known} {title} · {role}")
            if known != "☐":
                seen += 1
        lines.insert(0, f"Discoveries · {seen}/{total} notes ({int(100*seen/max(1,total))}%)")
        popup(scr, "Discoveries", lines)

    def overworld_loop(scr):
        scr.nodelay(False)
        curses.curs_set(0)
        dim = palette.get("#", curses.A_DIM)
        game._in_overworld = True
        cursor_x, cursor_y = game._ow_cursor
        try:
            while True:
                scr.erase()
                rows, cols = scr.getmaxyx()
                ow_w = cols - 4
                ow_h = rows - 5
                ow_w, ow_h = max(20, ow_w), max(6, ow_h)
                grid, meta = game.compose_overworld(ow_w, ow_h)
                bar = "─" * (ow_w - 2)
                acc = palette.get("@", curses.A_BOLD)

                # title bar
                txt = f"The Overworld · sprawl={game.sprawl:.1f}"
                try:
                    scr.addstr(0, 1, "┌" + bar + "┐", acc)
                    scr.addstr(0, 3, txt[:ow_w - 4], acc)
                except curses.error:
                    pass

                for y in range(min(ow_h, len(grid))):
                    try:
                        scr.addstr(y + 1, 1, "│", dim)
                        scr.addstr(y + 1, ow_w, "│", dim)
                    except curses.error:
                        pass
                    for x, ch in enumerate(row := grid[y]):
                        wx, wy = x, y
                        a = palette.get(ch, 0)
                        rid = meta.get((x, y), "")
                        if rid:
                            r = next((r for r in game.m["regions"] if r.get("name") == rid), None)
                            if r:
                                lean = game.region_palette(r.get("id", ""))
                                pa = palette.get("pal:" + lean) if lean else None
                                if pa is not None:
                                    a = pa
                                # mapped check: dim unknown regions
                                know = game.system("knowledge")
                                if know is not None and not know.region_known_for(r.get("id", "")):
                                    a = a | curses.A_DIM if a else dim
                        # cursor highlight
                        if (wx, wy) == (cursor_x, cursor_y):
                            a = a | curses.A_REVERSE
                        try:
                            scr.addstr(y + 1, 2 + x, ch, a)
                        except curses.error:
                            pass

                # landmarks at scaled positions
                for (lx, ly), kind in getattr(game, "_landmarks", {}).items():
                    bw = max(1, (game.level.w + ow_w - 1) // ow_w)
                    bh = max(1, (game.level.h + ow_h - 1) // ow_h)
                    ocx, ocy = lx // bw, ly // bh
                    if 0 <= ocx < ow_w and 0 <= ocy < ow_h:
                        gly = {"heart": "◆", "town": ">", "wild": "*"}.get(kind, "*")
                        pa = palette.get(gly, 0) | curses.A_BOLD
                        try:
                            scr.addstr(ocy + 1, 2 + ocx, gly, pa)
                        except curses.error:
                            pass

                # footer
                cur_info = meta.get((cursor_x, cursor_y), "")
                foot = f"cursor: {cur_info or 'wilds'}  ·  [arrows]move  [tab]player  [enter]inspect  [esc/v]return"
                try:
                    scr.addstr(ow_h + 2, 1, "├" + bar + "┤", acc)
                    scr.addstr(ow_h + 3, 1, "│ " + foot[:ow_w - 4].ljust(ow_w - 4) + " │", acc)
                    scr.addstr(ow_h + 4, 1, "└" + bar + "┘", acc)
                except curses.error:
                    pass
                scr.refresh()

                k = scr.getch()
                if k in (ord("v"), ord("V"), 27, ord("q")):
                    game._ow_cursor = (cursor_x, cursor_y)
                    return
                elif k == ord("\t"):
                    px, py = game.player.x, game.player.y
                    bw = max(1, (game.level.w + ow_w - 1) // ow_w)
                    bh = max(1, (game.level.h + ow_h - 1) // ow_h)
                    cursor_x, cursor_y = px // bw, py // bh
                elif k == curses.KEY_UP or k == ord("k"):
                    cursor_y = max(0, cursor_y - 1)
                elif k == curses.KEY_DOWN or k == ord("j"):
                    cursor_y = min(ow_h - 1, cursor_y + 1)
                elif k == curses.KEY_LEFT or k == ord("h"):
                    cursor_x = max(0, cursor_x - 1)
                elif k == curses.KEY_RIGHT or k == ord("l"):
                    cursor_x = min(ow_w - 1, cursor_x + 1)
                elif k in (10, 13):
                    info = meta.get((cursor_x, cursor_y), "")
                    rid = next((r["id"] for r in game.m["regions"] if r["name"] == info), "")
                    lines = [f"Region: {info}"]
                    if rid:
                        r = next((r for r in game.m["regions"] if r["id"] == rid), None)
                        if r:
                            lines.append(f"Element: {r.get('element', '?')}")
                            lines.append(f"Faction: {game._region_faction.get(rid, '?')}")
                            know = game.system("knowledge")
                            mapped = know.region_known_for(rid) if know else False
                            lines.append(f"Mapped: {'yes' if mapped else 'no'}")
                    popup(scr, "Inspect Region", lines)
                elif k == ord("w"):
                    bw = max(1, (game.level.w + ow_w - 1) // ow_w)
                    bh = max(1, (game.level.h + ow_h - 1) // ow_h)
                    game._ow_waypoint = (cursor_x * bw + bw // 2, cursor_y * bh + bh // 2)
                elif k == ord("W"):
                    game._ow_waypoint = None
        finally:
            game._in_overworld = False

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
            if k == curses.KEY_RESIZE:
                curses.update_lines_cols()
                draw(scr)
                continue
            # q only: bare ESC is dropped, because fast arrow-mashing can leak a
            # partial escape sequence that would otherwise quit the game mid-fight
            if k == ord("q"):
                return
            if k in moves:
                game.try_move(*moves[k])
            elif k == ord("g"):
                travel(scr)   # TRAVEL: pick a direction, glide until something happens
            elif k == ord("o"):
                autoexplore(scr)  # AUTOEXPLORE: one step toward nearest fog edge
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
            elif k == ord("M"):
                show_log(scr, "combat")
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
                # ONE talk verb for everything: a wild landmark, the deepest thought,
                # or any adjacent creature — all open the same windowed conversation
                # (name at top, verbs at the bottom border). The boss/landmark keep
                # their special resolution; every actor uses the unified talk window.
                if game.commune_landmark() is not None:
                    pass
                elif game.commune() is None:
                    adj = [a for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                           for a in [game.actor_at(game.player.x + dx,
                                                   game.player.y + dy)]
                           if a is not None]
                    if adj:
                        talk_window(scr, adj[0])
                        game.wait()   # the exchange costs the turn
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
                        from .proficiency import exercise
                        if kind == "sigil":
                            exercise(slots[ref]["ability"])
                        else:
                            exercise(ref)
                        game.wait()
            elif k == ord("f"):
                if forge is None:
                    continue
                names = ", ".join(f"{n + 1}:{a}" for n, a in enumerate(ABILITIES))
                i = pick(scr, f"forge which? {names}", len(ABILITIES))
                if i is not None:
                    if forge.forge(game, ABILITIES[i]):
                        from .proficiency import exercise
                        exercise(ABILITIES[i])
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
                elif k == ord("a"):
                    game.interact()
                    # sacrifice shrine popup
                    pending = getattr(game, "_pending_sacrifice", None)
                    if pending:
                        opts = [f"{o[0]}: {o[2]}" for o in pending] + ["Reject all — the shrine crumbles"]
                        i = menu(scr, "Renunciation Shrine", opts,
                                 lead=["Choose a sacrifice, or reject all."])
                        if i is not None and i < len(pending):
                            sac = game.system("sacrifice")
                            if sac:
                                sac.apply(game, pending[i][1])
                        else:
                            game._pending_sacrifice = None
                            game.log("You turn away. The shrine crumbles to dust.")
                elif k == ord("d"):
                    game.shield()
                elif k == ord("p"):
                    d = pick_dir(scr, "shove which way?")
                    if d is not None:
                        game.shove(*d)
            elif k == ord("V"):
                if not game._on_surface():
                    game.log("There is no overlooking the depths from below.")
                elif not _can_overlook(game):
                    game.log("You need a vantage — a heart of a place, or a town's gate.")
                else:
                    overworld_loop(scr)
            elif k == ord("i"):
                px, py = game.player.x, game.player.y
                adj = [a for a in game.actors
                       if max(abs(a.x - px), abs(a.y - py)) <= 1 and a.allegiance != "companion"]
                if adj:
                    target = sorted(adj, key=lambda a: abs(a.x-px) + abs(a.y-py))[0]
                    lines = game.inspect_actor(target)
                    popup(scr, target.name, lines)
                else:
                    game.log("Nothing to inspect nearby.")
            elif k == ord("Q"):
                quest_log(scr)
            elif k == ord("C"):
                companion_panel(scr)
            elif k == ord("D"):
                completion_plaque(scr)
            elif k == ord("G"):
                # gravestone lookup: if standing on a grave tile, read it
                gv = game._graves.get((game.player.x, game.player.y))
                if gv:
                    popup(scr, "Grave Marker", [gv])
                else:
                    game.log("No grave marker here.")

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
                    help="player brain: artisan, cartographer, emergent, exploiter (default), seeker, whisper, survivor, hunter")
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
        from .scent import ScentSystem
        from .body_parts import BodySystem
        from .terrain_mod import TerrainModSystem
        from .portals import PortalSystem
        from .sacrifice import SacrificeSystem
        from .quests import QuestSystem
        from .dialogue import DialogueSystem
        from .machines import MachineSystem
        from .caches import CacheSystem
        from .factions import FactionSystem
        from .loci import LocusSystem
        from .craft import CraftSystem
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
                   ScentSystem(),   # scent trails for tracking and stealth
                    QuestSystem(), DialogueSystem(), CraftSystem(), MachineSystem(),   # quests · NPCs · craft rituals · machines
                   CacheSystem(),   # each place is a distinct opportunity
                   TerrainModSystem(),   # dynamic terrain: sanctums, scars, thresholds
                   PortalSystem(),       # timed realm gates
                   SacrificeSystem(),    # renunciation shrines
                    FactionSystem(), BodySystem(), QualitySystem(),   # factions, body parts, then quality grades all spawned foes
                    HistorySystem(), MarginaliaSystem(), LocusSystem(), KnowledgeSystem(),
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
    from . import agent  # noqa: F401 — universal brain, Berlin-compliant
    # ^ registers brain tiers (hunter…tactician/exploiter, mastermind/tracker/wary) + profiles
    from .sense import make_brain
    if a.embody:
        if not embody(game, a.embody):
            print(f"error: nothing in the world matches {a.embody!r}", file=sys.stderr)
            return 2
    game.player.brain = make_brain(game, game.player,
                                   name="hunter" if a.brain == "dumb" else a.brain)
    # Wire the agent name into the brain for scoring profile lookup
    game.player.brain.name = a.brain
    # Store agent name on player for personality-gated mechanics
    # Store agent name for personality-gated mechanics (e.g. whisper always-parley)
    game.player._agent_name = a.brain
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
