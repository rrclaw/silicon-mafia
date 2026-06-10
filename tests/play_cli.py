"""Terminal human-vs-NPC game. Usage:
    python3.11 tests/play_cli.py [--bot] [--lang bilingual|zh|en] [--seed N] [--cast id1,id2,...]
--bot replaces the human with scripted random play (used by smoke_ai)."""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (
    Role, Phase, new_game, submit_night_action, submit_speech, end_discussion,
    submit_nomination, submit_defense, submit_verdict_vote, visible_state,
)
from engine.transitions import night_required
from ai.personas import roster_cards, ep001_roster, load_chemistry, load_personas
from ai import orchestrator as O


def show_new_chat(state, cursor, lang):
    for c in state.chat[cursor:]:
        who = "🎙️ SOLANA" if c.seat is None else state.players[c.seat].name
        if c.kind == "ghost":
            who = f"👻 {who}"
        if lang == "zh":
            print(f"  {who}: {c.text_zh}")
        elif lang == "en":
            print(f"  {who}: {c.text_en}")
        else:
            print(f"  {who}: {c.text_en}")
            if c.text_zh and c.text_zh != c.text_en:
                print(f"      ﹂{c.text_zh}")
    return len(state.chat)


def pick_target(state, targets, prompt, bot, rng):
    names = ", ".join(f"{s}={state.players[s].name}" for s in targets)
    if bot:
        return rng.choice(targets)
    while True:
        raw = input(f"{prompt} [{names}]: ").strip()
        if raw.isdigit() and int(raw) in targets:
            return int(raw)
        print("  无效座位号")


def human_text(prompt, bot, default=""):
    if bot:
        return default
    return input(prompt).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", action="store_true")
    ap.add_argument("--lang", default="bilingual")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--cast", default="")
    ap.add_argument("--waves", type=int, default=2)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if args.cast:
        ids = args.cast.split(",")
    else:
        ids = ep001_roster()
    absent = ""
    if len(ids) > 11:
        absent_id = rng.choice(ids)
        absent = load_personas()[absent_id]["name_en"]
        ids = [i for i in ids if i != absent_id]
    ids = ids[:11]

    name = "rr" if args.bot else (input("你的名字: ").strip() or "rr")
    state = new_game(roster_cards(ids), human_name=name, lang=args.lang,
                     waves_per_day=args.waves, seed=args.seed,
                     chemistry_pairs=load_chemistry())
    O.cold_open(state, absent_name=absent)
    me = state.players[0]
    print(f"\n=== 你的身份: {me.role.value} ===\n")
    cursor = show_new_chat(state, 0, args.lang)

    while state.winner is None:
        if state.phase == Phase.NIGHT:
            print(f"\n--- 第 {state.day} 夜 ---")
            if O.human_night_action_needed(state):
                req = night_required(state)
                if me.role == Role.MAFIA and "kill" in req and me.alive:
                    targets = [s for s in state.alive_seats()
                               if state.players[s].role != Role.MAFIA]
                    submit_night_action(state, "kill", 0,
                                        pick_target(state, targets, "🔪 你是 mafia, 选击杀目标", args.bot, rng))
                if me.role == Role.SHERIFF and "check" in req and me.alive:
                    targets = [s for s in state.alive_seats() if s != 0]
                    t = pick_target(state, targets, "🔍 你是警长, 选查验目标", args.bot, rng)
                    submit_night_action(state, "check", 0, t)
                    print(f"  查验结果: {state.players[t].name} {'是 MAFIA!' if state.sheriff_private[-1][2] else '是好人'}")
                if me.role == Role.ANGEL and "save" in req and me.alive:
                    targets = [s for s in state.alive_seats() if s != state.angel_last_save]
                    submit_night_action(state, "save", 0,
                                        pick_target(state, targets, "🪽 你是天使, 选守护目标", args.bot, rng))
            print("  (大佬们在夜里行动...)")
            O.step_night(state)
            O.maybe_resolve_night(state)
            cursor = show_new_chat(state, cursor, args.lang)
            continue

        if state.phase == Phase.DAY_DISCUSSION:
            print(f"\n--- 第 {state.day} 天讨论 ---")
            while O.waves_left(state):
                print("  (大佬们在组织语言...)")
                O.step_wave(state)
                cursor = show_new_chat(state, cursor, args.lang)
                if me.alive:
                    txt = human_text("💬 你的发言(回车跳过): ", args.bot)
                    if txt:
                        submit_speech(state, 0, txt, txt)
                        cursor = len(state.chat)
            end_discussion(state)
            continue

        if state.phase == Phase.NOMINATION:
            print("\n--- 提名审判 ---")
            if me.alive and 0 not in state.current_day.nominations:
                targets = [s for s in state.alive_seats() if s != 0]
                if args.bot or input("要提名吗? (y/n): ").strip().lower() == "y":
                    submit_nomination(state, 0, pick_target(state, targets, "⚖️ 提名谁", args.bot, rng))
                else:
                    submit_nomination(state, 0, None)
            O.step_nominations(state)
            O.maybe_resolve_nominations(state)
            cursor = show_new_chat(state, cursor, args.lang)
            continue

        if state.phase == Phase.TRIAL:
            print("\n--- 审判席 ---")
            if 0 in state.current_day.defendants and 0 not in state.current_day.defenses_done and me.alive:
                txt = human_text("🎤 你的 15 秒辩护: ", args.bot, default="I am innocent.")
                submit_defense(state, 0, txt, txt)
            O.step_defenses(state)
            cursor = show_new_chat(state, cursor, args.lang)
            continue

        if state.phase == Phase.VERDICT:
            print("\n--- 公开投票 ---")
            from engine.transitions import verdict_voters
            if 0 in verdict_voters(state) and 0 not in state.current_day.votes:
                defs = state.current_day.defendants
                t = pick_target(state, defs, "🗳️ 投谁出局", args.bot, rng)
                submit_verdict_vote(state, 0, t, "", "")
            O.step_verdict(state)
            O.maybe_resolve_verdict(state)
            cursor = show_new_chat(state, cursor, args.lang)
            continue

    print(f"\n====== 游戏结束: {state.winner.upper()} WINS ======")
    for p in state.players:
        print(f"  {p.name}: {p.role.value} {'(alive)' if p.alive else '(dead)'}")


if __name__ == "__main__":
    main()
