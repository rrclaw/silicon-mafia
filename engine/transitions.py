"""State transitions for MAFIA. Pure functions over GameState; no LLM calls.

Phase machine (节目规则):
NIGHT -> (resolve) -> DAY_DISCUSSION (waves) -> NOMINATION -> TRIAL (defenses)
-> VERDICT (open vote) -> execute + reveal -> NIGHT ... -> GAME_OVER

Narration text is passed in by the AI layer (Solana flavor); every resolve
function has a template fallback so the game never stalls on LLM failure.
"""
from __future__ import annotations

import random
from typing import Optional

from .rules import Role, build_role_deck, ROLE_LABELS
from .state import GameState, Player, Phase, ChatLine, NightRecord, DayRecord, new_game_id


# ---------- setup ----------

def new_game(roster: list[dict], human_name: str, lang: str = "bilingual",
             waves_per_day: int = 2, seed: Optional[int] = None,
             human_role: Optional[Role] = None,
             chemistry_pairs: Optional[list[dict]] = None) -> GameState:
    """roster: list of persona dicts (id/name_en/name_zh) for the 11 NPC seats."""
    n = len(roster) + 1
    rng = random.Random(seed)
    deck = build_role_deck(n)
    rng.shuffle(deck)
    if human_role is not None:
        # swap human's drawn card with a seat holding the requested role
        if deck[0] != human_role:
            j = deck.index(human_role)
            deck[0], deck[j] = deck[j], deck[0]

    players = [Player(id=0, name=human_name, name_zh=human_name, is_human=True, role=deck[0])]
    order = list(roster)
    rng.shuffle(order)
    for i, card in enumerate(order, start=1):
        players.append(Player(
            id=i, name=card["name_en"], name_zh=card.get("name_zh", card["name_en"]),
            persona_id=card["id"], role=deck[i],
        ))

    present = {p.persona_id for p in players if p.persona_id}
    active = []
    for pair in (chemistry_pairs or []):
        if set(pair["pair"]) <= present:
            active.append(pair)

    state = GameState(game_id=new_game_id(), players=players, lang=lang,
                      waves_per_day=waves_per_day, seed=seed,
                      chemistry_active=active)
    state.nights.append(NightRecord(night_idx=1))
    return state


def _say(state: GameState, seat: Optional[int], kind: str, en: str, zh: str = "") -> None:
    state.chat.append(ChatLine(seat=seat, kind=kind, text_en=en, text_zh=zh or en,
                               day=state.day, phase=state.phase.value))


# ---------- night ----------

def night_required(state: GameState) -> list[str]:
    """Actions still missing this night, as ["kill","check","save"]."""
    nr = state.current_night
    req = []
    if state.mafia_seats() and "kill" not in nr.done:
        req.append("kill")
    if state.seat_with_role(Role.SHERIFF) is not None and "check" not in nr.done:
        req.append("check")
    if state.seat_with_role(Role.ANGEL) is not None and "save" not in nr.done:
        req.append("save")
    return req


def submit_night_action(state: GameState, action: str, actor_seat: int, target: int) -> None:
    if state.phase != Phase.NIGHT:
        raise RuntimeError(f"not night: {state.phase}")
    nr = state.current_night
    actor = state.players[actor_seat]
    tgt = state.players[target]
    if not actor.alive:
        raise ValueError("actor is dead")
    if not tgt.alive:
        raise ValueError("target is dead")
    if action == "kill":
        if actor.role != Role.MAFIA:
            raise ValueError("not mafia")
        if tgt.role == Role.MAFIA:
            raise ValueError("mafia cannot kill mafia")
        nr.kill_target = target
        nr.done.add("kill")
    elif action == "check":
        if actor.role != Role.SHERIFF:
            raise ValueError("not sheriff")
        nr.sheriff_check = target
        nr.sheriff_result = (tgt.role == Role.MAFIA)
        state.sheriff_private.append((nr.night_idx, target, nr.sheriff_result))
        nr.done.add("check")
    elif action == "save":
        if actor.role != Role.ANGEL:
            raise ValueError("not angel")
        if state.angel_last_save is not None and target == state.angel_last_save:
            raise ValueError("cannot save the same person two nights in a row")
        nr.angel_save = target
        nr.done.add("save")
    else:
        raise ValueError(f"unknown action {action}")


def resolve_night(state: GameState, dawn_en: str = "", dawn_zh: str = "",
                  ghost_lines: Optional[list[dict]] = None) -> None:
    """Call when night_required() is empty. Computes death, narrates, advances."""
    if state.phase != Phase.NIGHT or night_required(state):
        raise RuntimeError("night not complete")
    nr = state.current_night
    if nr.angel_save is not None:
        state.angel_last_save = nr.angel_save
    death = nr.kill_target
    if death is not None and death == nr.angel_save:
        death = None
    nr.death = death
    if death is not None:
        state.players[death].alive = False

    if not dawn_en:
        if death is None:
            dawn_en, dawn_zh = "It was a quiet night. Nobody died.", "昨晚很安静，没有人死。"
        else:
            nm = state.players[death].name
            dawn_en = f"{nm} was found dead this morning. Who did it?"
            dawn_zh = f"今早发现 {nm} 死了。是谁干的？"
    _say(state, None, "narration", dawn_en, dawn_zh)
    for g in (ghost_lines or []):
        seat = g.get("seat")
        if seat is not None and not state.players[seat].alive:
            _say(state, seat, "ghost", g.get("en", ""), g.get("zh", ""))

    if _check_win(state):
        return
    state.phase = Phase.DAY_DISCUSSION
    state.wave_idx = 0
    state.days.append(DayRecord(day_idx=state.day))


# ---------- day discussion ----------

def submit_speech(state: GameState, seat: int, en: str, zh: str = "") -> None:
    if state.phase not in (Phase.DAY_DISCUSSION, Phase.NOMINATION):
        raise RuntimeError(f"not discussion: {state.phase}")
    if not state.players[seat].alive:
        raise ValueError("dead players don't speak")
    _say(state, seat, "speech", en, zh)


def advance_wave(state: GameState) -> None:
    state.wave_idx += 1


def end_discussion(state: GameState) -> None:
    if state.phase != Phase.DAY_DISCUSSION:
        raise RuntimeError(f"not discussion: {state.phase}")
    state.phase = Phase.NOMINATION


# ---------- nomination ----------

def submit_nomination(state: GameState, seat: int, target: Optional[int]) -> None:
    if state.phase != Phase.NOMINATION:
        raise RuntimeError(f"not nomination: {state.phase}")
    if not state.players[seat].alive:
        raise ValueError("dead")
    if target is not None and not state.players[target].alive:
        raise ValueError("target dead")
    if target == seat:
        target = None
    state.current_day.nominations[seat] = target


def nomination_pending(state: GameState) -> list[int]:
    return [s for s in state.alive_seats() if s not in state.current_day.nominations]


def resolve_nominations(state: GameState) -> None:
    """Top-2 nominated go on trial. Zero nominations => quiet day, straight to night."""
    if nomination_pending(state):
        raise RuntimeError("nominations incomplete")
    day = state.current_day
    counts: dict[int, int] = {}
    for tgt in day.nominations.values():
        if tgt is not None:
            counts[tgt] = counts.get(tgt, 0) + 1
    if not counts:
        _say(state, None, "narration",
             "Nobody was put on trial today. The town hesitates.",
             "今天没有人被送上审判席。全镇都在犹豫。")
        start_night(state)
        return
    rng = random.Random((state.seed or 0) + state.day * 1000)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], rng.random()))
    day.defendants = [s for s, _ in ranked[:2]]
    names = " and ".join(state.players[s].name for s in day.defendants)
    _say(state, None, "narration",
         f"On trial: {names}. 15 seconds each. This is not deliberation. Did you do it or not?",
         f"上庭：{names}。每人 15 秒，不许打断。Did you do it or not?")
    state.phase = Phase.TRIAL


# ---------- trial ----------

def submit_defense(state: GameState, seat: int, en: str, zh: str = "") -> None:
    if state.phase != Phase.TRIAL:
        raise RuntimeError(f"not trial: {state.phase}")
    if seat not in state.current_day.defendants:
        raise ValueError("not on trial")
    _say(state, seat, "defense", en, zh)
    state.current_day.defenses_done.add(seat)
    if set(state.current_day.defendants) <= state.current_day.defenses_done:
        state.phase = Phase.VERDICT


# ---------- verdict ----------

def verdict_voters(state: GameState) -> list[int]:
    return [s for s in state.alive_seats() if s not in state.current_day.defendants]


def submit_verdict_vote(state: GameState, seat: int, target: Optional[int],
                        reason_en: str = "", reason_zh: str = "") -> None:
    if state.phase != Phase.VERDICT:
        raise RuntimeError(f"not verdict: {state.phase}")
    if seat not in verdict_voters(state):
        raise ValueError("not a voter")
    if target is not None and target not in state.current_day.defendants:
        raise ValueError("must vote a defendant or abstain")
    state.current_day.votes[seat] = target
    if reason_en or target is not None:
        who = state.players[target].name if target is not None else "abstain"
        en = f"votes {who}" + (f" — {reason_en}" if reason_en else "")
        zh = f"投 {who}" + (f"：{reason_zh}" if reason_zh else "")
        _say(state, seat, "vote", en, zh)


def verdict_pending(state: GameState) -> list[int]:
    return [s for s in verdict_voters(state) if s not in state.current_day.votes]


def resolve_verdict(state: GameState, death_en: str = "", death_zh: str = "") -> None:
    if verdict_pending(state):
        raise RuntimeError("votes incomplete")
    day = state.current_day
    counts: dict[int, int] = {}
    for tgt in day.votes.values():
        if tgt is not None:
            counts[tgt] = counts.get(tgt, 0) + 1
    if not counts or (len(counts) == 2 and len(set(counts.values())) == 1):
        _say(state, None, "narration",
             "The vote is split. Nobody dies today. The town remains paranoid.",
             "票数持平，今天没人被处决。全镇继续疑神疑鬼。")
        start_night(state)
        return
    executed = max(counts.items(), key=lambda kv: kv[1])[0]
    day.executed = executed
    p = state.players[executed]
    p.alive = False
    p.revealed = True
    role_en = ROLE_LABELS[p.role]["en"]
    role_zh = ROLE_LABELS[p.role]["zh"]
    if not death_en:
        death_en = f"{p.name} is dead. The card flips: {p.name} was... {role_en.upper()}."
        death_zh = f"{p.name} 死了。翻牌：{p.name} 的身份是——{role_zh}。"
    _say(state, None, "narration", death_en, death_zh)
    _say(state, None, "reveal",
         f"{p.name} was {role_en}.", f"{p.name} 是{role_zh}。")
    if _check_win(state):
        return
    start_night(state)


# ---------- night start / win ----------

def start_night(state: GameState) -> None:
    state.day += 1
    state.phase = Phase.NIGHT
    state.nights.append(NightRecord(night_idx=state.day))
    _say(state, None, "narration", "Everybody go to sleep.", "全体睡觉。入夜。")


def _check_win(state: GameState) -> bool:
    mafia = len(state.mafia_seats())
    town = len(state.alive_seats()) - mafia
    if mafia == 0:
        state.winner = "town"
    elif mafia >= town:
        state.winner = "mafia"
    else:
        return False
    state.phase = Phase.GAME_OVER
    for p in state.players:
        p.revealed = True
    if state.winner == "mafia":
        _say(state, None, "narration", "AND THE MAFIA WINS.", "黑手党获胜。")
    else:
        _say(state, None, "narration", "The town finally got them all. TOWN WINS.",
             "全镇终于抓光了黑手党。好人获胜。")
    return True


# ---------- visibility ----------

def visible_state(state: GameState, viewer: int = 0) -> dict:
    me = state.players[viewer]
    players = []
    for p in state.players:
        d = {
            "seat": p.id, "name": p.name, "name_zh": p.name_zh,
            "persona_id": p.persona_id, "is_human": p.is_human, "alive": p.alive,
        }
        if p.revealed or state.phase == Phase.GAME_OVER or p.id == viewer:
            d["role"] = p.role.value
        players.append(d)

    private: dict = {"role": me.role.value}
    if me.role == Role.MAFIA:
        private["teammates"] = [s for s in state.mafia_seats(alive_only=False) if s != viewer]
    if me.role == Role.SHERIFF:
        private["checks"] = [
            {"night": n, "seat": t, "is_mafia": r} for n, t, r in state.sheriff_private
        ]
    if me.role == Role.ANGEL:
        private["last_save"] = state.angel_last_save

    pending = None  # what the human must do right now
    if state.winner is None and me.alive:
        if state.phase == Phase.NIGHT:
            req = night_required(state)
            if me.role == Role.MAFIA and "kill" in req:
                pending = {"type": "kill", "targets": [s for s in state.alive_seats()
                                                       if state.players[s].role != Role.MAFIA]}
            elif me.role == Role.SHERIFF and "check" in req:
                pending = {"type": "check", "targets": [s for s in state.alive_seats() if s != viewer]}
            elif me.role == Role.ANGEL and "save" in req:
                pending = {"type": "save",
                           "targets": [s for s in state.alive_seats() if s != state.angel_last_save]}
        elif state.phase == Phase.DAY_DISCUSSION:
            pending = {"type": "speak_or_end"}
        elif state.phase == Phase.NOMINATION:
            if viewer not in state.current_day.nominations:
                pending = {"type": "nominate", "targets": [s for s in state.alive_seats() if s != viewer]}
        elif state.phase == Phase.TRIAL:
            if viewer in state.current_day.defendants and viewer not in state.current_day.defenses_done:
                pending = {"type": "defense"}
        elif state.phase == Phase.VERDICT:
            if viewer in verdict_voters(state) and viewer not in state.current_day.votes:
                pending = {"type": "verdict", "targets": list(state.current_day.defendants)}

    day = state.current_day
    return {
        "game_id": state.game_id,
        "phase": state.phase.value,
        "day": state.day,
        "wave": state.wave_idx,
        "waves_per_day": state.waves_per_day,
        "lang": state.lang,
        "winner": state.winner,
        "players": players,
        "you": {"seat": viewer, "alive": me.alive, **private},
        "pending": pending,
        "defendants": list(day.defendants) if day else [],
        "chat": [
            {"seat": c.seat, "kind": c.kind, "en": c.text_en, "zh": c.text_zh,
             "day": c.day, "phase": c.phase}
            for c in state.chat
        ],
    }
