"""Apply AI action results to the engine. Shared by play_cli and the server.

Each step_* function performs the AI calls *for the current phase* and mutates
state, stopping wherever human input is required (the caller checks
visible_state()["pending"]).
"""
from __future__ import annotations

from engine.rules import Role
from engine.state import GameState, Phase, ChatLine
from engine.transitions import (
    night_required, submit_night_action, resolve_night,
    submit_speech, advance_wave, end_discussion,
    submit_nomination, nomination_pending, resolve_nominations,
    submit_defense, submit_verdict_vote, verdict_pending, resolve_verdict,
)
from . import actions as A


def cold_open(state: GameState, absent_name: str = "") -> None:
    human = state.players[0].name
    en = ("Welcome to Tosca Café. I'm now in charge. I'm the narrator. "
          f"Tonight at the table: {', '.join(p.name for p in state.players)}. ")
    zh = f"欢迎来到 Tosca Café。我是主持人，现在我说了算。今晚牌桌上：{', '.join(p.name for p in state.players)}。"
    if absent_name:
        en += f"{absent_name} couldn't make it tonight — {human} is sitting in. "
        zh += f"{absent_name} 今晚来不了，{human} 顶替入座。"
    en += "Three jacks are the mafia. One king is the sheriff. One ace is the angel. Leave the friendship at the bar. Let's go kill some people."
    zh += "三张 J 是黑手党，一张 K 是警长，一张 A 是天使。把友情留在吧台。开杀吧。"
    state.chat.append(ChatLine(seat=None, kind="narration", text_en=en, text_zh=zh,
                               day=0, phase="setup"))
    state.chat.append(ChatLine(seat=None, kind="narration",
                               text_en="Everybody go to sleep.", text_zh="全体睡觉。入夜。",
                               day=1, phase="night"))


def human_night_action_needed(state: GameState) -> bool:
    me = state.players[0]
    if not me.alive:
        return False
    req = night_required(state)
    return ((me.role == Role.MAFIA and "kill" in req)
            or (me.role == Role.SHERIFF and "check" in req)
            or (me.role == Role.ANGEL and "save" in req))


def step_night(state: GameState) -> None:
    """Run AI night actions; resolve if nothing is left waiting on the human."""
    if state.phase != Phase.NIGHT:
        return
    out = A.ai_night(state)
    for key in ("kill", "check", "save"):
        pair = out.get(key)
        if pair:
            actor, target = pair
            if key not in state.current_night.done:
                submit_night_action(state, key, actor, target)
    state.current_night.ai_meta = out  # stash narration for resolve
    maybe_resolve_night(state)


def maybe_resolve_night(state: GameState) -> None:
    if state.phase != Phase.NIGHT or night_required(state):
        return
    out = getattr(state.current_night, "ai_meta", None) or {}
    nr = state.current_night
    death = nr.kill_target
    if death is not None and death == nr.angel_save:
        death = None
    en, zh = A.dawn_narration(out, state, death) if out else ("", "")
    resolve_night(state, dawn_en=en, dawn_zh=zh, ghost_lines=out.get("ghosts"))


def step_wave(state: GameState) -> list[tuple[int, str, str]]:
    """Generate one discussion wave; returns speeches for progressive display."""
    if state.phase != Phase.DAY_DISCUSSION:
        return []
    speeches = A.ai_discussion_wave(state)
    for seat, en, zh in speeches:
        submit_speech(state, seat, en, zh)
    advance_wave(state)
    return speeches


def waves_left(state: GameState) -> bool:
    return state.phase == Phase.DAY_DISCUSSION and state.wave_idx < state.waves_per_day


def step_nominations(state: GameState) -> None:
    if state.phase != Phase.NOMINATION:
        return
    for seat, target, en, zh in A.ai_nominations(state):
        if en:
            submit_speech(state, seat, en, zh)
        submit_nomination(state, seat, target)
    if not nomination_pending(state):
        resolve_nominations(state)


def maybe_resolve_nominations(state: GameState) -> None:
    if state.phase == Phase.NOMINATION and not nomination_pending(state):
        resolve_nominations(state)


def step_defenses(state: GameState) -> None:
    if state.phase != Phase.TRIAL:
        return
    for seat, en, zh in A.ai_defenses(state):
        submit_defense(state, seat, en, zh)


def step_verdict(state: GameState) -> None:
    if state.phase != Phase.VERDICT:
        return
    out = A.ai_verdict(state)
    for seat, target, en, zh in out["votes"]:
        submit_verdict_vote(state, seat, target, en, zh)
    state.current_day.ai_flavor = out.get("death_flavor") or {}
    maybe_resolve_verdict(state)


def maybe_resolve_verdict(state: GameState) -> None:
    if state.phase != Phase.VERDICT or verdict_pending(state):
        return
    day = state.current_day
    flavor = getattr(day, "ai_flavor", {}) or {}
    counts: dict[int, int] = {}
    for tgt in day.votes.values():
        if tgt is not None:
            counts[tgt] = counts.get(tgt, 0) + 1
    en = zh = ""
    if counts and not (len(counts) == 2 and len(set(counts.values())) == 1):
        executed = max(counts.items(), key=lambda kv: kv[1])[0]
        en, zh = A.execution_narration(flavor, state, executed)
    resolve_verdict(state, death_en=en, death_zh=zh)
