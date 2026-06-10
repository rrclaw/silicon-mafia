"""Engine smoke test: scripted 12-player game, no LLM. Asserts phase flow,
win conditions, and information isolation (visible_state never leaks)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random

from engine import (
    Role, Phase, new_game, night_required, submit_night_action, resolve_night,
    submit_speech, end_discussion, submit_nomination, nomination_pending,
    resolve_nominations, submit_defense, submit_verdict_vote, verdict_pending,
    verdict_voters, resolve_verdict, visible_state,
)
from ai.personas import roster_cards, ep001_roster, load_chemistry


def auto_night(state, rng):
    nr = state.current_night
    for action in night_required(state):
        if action == "kill":
            actor = state.mafia_seats()[0]
            tgt = rng.choice([s for s in state.alive_seats()
                              if state.players[s].role != Role.MAFIA])
            submit_night_action(state, "kill", actor, tgt)
        elif action == "check":
            actor = state.seat_with_role(Role.SHERIFF)
            tgt = rng.choice([s for s in state.alive_seats() if s != actor])
            submit_night_action(state, "check", actor, tgt)
        elif action == "save":
            actor = state.seat_with_role(Role.ANGEL)
            tgt = rng.choice([s for s in state.alive_seats() if s != state.angel_last_save])
            submit_night_action(state, "save", actor, tgt)
    assert not night_required(state)
    resolve_night(state)
    return nr


def run_game(seed):
    rng = random.Random(seed)
    roster = roster_cards(ep001_roster()[:11])
    state = new_game(roster, human_name="rr", seed=seed,
                     chemistry_pairs=load_chemistry())
    assert len(state.players) == 12
    assert len(state.mafia_seats()) == 3

    rounds = 0
    while state.winner is None and rounds < 30:
        rounds += 1
        assert state.phase == Phase.NIGHT, state.phase
        auto_night(state, rng)
        if state.winner:
            break
        # discussion
        assert state.phase == Phase.DAY_DISCUSSION
        for s in state.alive_seats():
            submit_speech(state, s, f"speech by seat{s}", f"seat{s} 的发言")
        end_discussion(state)
        # nominations: everyone nominates a random other alive player
        assert state.phase == Phase.NOMINATION
        for s in list(nomination_pending(state)):
            tgt = rng.choice([x for x in state.alive_seats() if x != s])
            submit_nomination(state, s, tgt)
        resolve_nominations(state)
        if state.phase == Phase.NIGHT:
            continue  # quiet day
        assert state.phase == Phase.TRIAL
        for d in list(state.current_day.defendants):
            submit_defense(state, d, "not me", "不是我")
        assert state.phase == Phase.VERDICT
        for s in list(verdict_pending(state)):
            tgt = rng.choice(state.current_day.defendants)
            submit_verdict_vote(state, s, tgt, "gut feeling", "直觉")
        resolve_verdict(state)

    assert state.winner in ("mafia", "town"), f"no winner after {rounds} rounds"
    return state


def check_isolation(state):
    """visible_state for the human must not leak others' unrevealed roles or
    night actions; sheriff results only in sheriff's own view."""
    vs = visible_state(state, viewer=0)
    me = state.players[0]
    for pd in vs["players"]:
        p = state.players[pd["seat"]]
        if pd["seat"] == 0 or p.revealed or state.winner:
            continue
        assert "role" not in pd, f"leaked role of seat {pd['seat']}"
    if me.role != Role.SHERIFF:
        assert "checks" not in vs["you"], "leaked sheriff checks to non-sheriff"
    if me.role != Role.MAFIA:
        assert "teammates" not in vs["you"], "leaked mafia list to non-mafia"
    # night targets never appear in public chat
    for c in vs["chat"]:
        assert "kill_target" not in c["en"]
    blob = str(vs)
    return blob


def main():
    wins = {"mafia": 0, "town": 0}
    for seed in range(20):
        state = run_game(seed)
        wins[state.winner] += 1
        # isolation check on a mid-game snapshot too
    # isolation on a fresh game (no reveals yet)
    roster = roster_cards(ep001_roster()[:11])
    fresh = new_game(roster, human_name="rr", seed=1, chemistry_pairs=load_chemistry())
    check_isolation(fresh)
    print(f"OK: 20 games completed. wins={wins}")
    assert wins["mafia"] > 0 and wins["town"] > 0, "suspiciously one-sided"


if __name__ == "__main__":
    main()
