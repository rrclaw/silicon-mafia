"""Phase-level AI actions: build prompt -> call_llm -> validate -> backfill.

Call topology (per game day):
  NIGHT   1 mega-call  (mafia kill consult + sheriff check + angel save
                        + Solana dawn narration + ghost one-liners)
  DAY     N wave calls (4 NPCs per wave, later waves see earlier speeches)
  NOMINATION 1 call    (each NPC nominates + one-liner)
  TRIAL   1 call       (AI defendants' 15-second defenses)
  VERDICT 1 call       (open votes with one-liner reasons + Solana execution flavor)

Every field has a deterministic backfill so the game never stalls on LLM failure.
"""
from __future__ import annotations

import json
import random

from engine.rules import Role, ROLE_LABELS
from engine.state import GameState, Phase
from . import personas as P
from .driver import call_llm

SYSTEM = """你是 Founders Fund 真人秀《MAFIA》的牌桌模拟器，地点旧金山 Tosca Café。
你同时扮演牌桌上的多位硅谷名人 NPC（以及主持人 Mike Solana）。

铁规则:
1. 只输出严格符合 schema 的 JSON。不要 markdown 围栏，不要解释。
2. 每个 NPC 只知道自己被告知的私密信息。绝不能把 A 的秘密泄漏进 B 的发言或行动。
3. 每个 NPC 必须严格用自己 persona 卡里的语气/句式/口头禅说话。口头禅和专属梗
   只属于本人(和主持人)，其他人绝不借用。
4. 发言像真人桌游: 短(1-3句)、有立场、敢指认、敢接前面人的话茬、敢怼人。
5. mafia 身份的 NPC 按其卡里 as_mafia 策略演——外在仍是这个人的真实风格。
6. 绝不替人类玩家发言或决策。
7. 中英双语字段: text_en 是该角色的英文原话(母语载体, 口头禅用英文)，text_zh 是
   同一句话的腔调化中文(参考各卡 zh_notes 的译法)，不是机翻。"""

LANG_FIELDS = {
    "bilingual": '"text_en": "...", "text_zh": "..."',
    "zh": '"text_en": "...", "text_zh": "..."',
    "en": '"text_en": "..."',
}


def _persona_of(state: GameState, seat: int) -> dict:
    return P.load_personas()[state.players[seat].persona_id]


def _present_ids(state: GameState) -> set[str]:
    return {p.persona_id for p in state.players if p.persona_id}


def _roster_line(state: GameState) -> str:
    rows = []
    for p in state.players:
        tag = "HUMAN" if p.is_human else p.persona_id
        status = "alive" if p.alive else (
            f"DEAD(身份已翻牌:{ROLE_LABELS[p.role]['zh']})" if p.revealed else "DEAD(身份未公开)")
        rows.append(f"  seat{p.id}={p.name}({tag}) {status}")
    return "\n".join(rows)


def _chat_tail(state: GameState, n: int = 80) -> str:
    rows = []
    for c in state.chat[-n:]:
        who = "SOLANA" if c.seat is None else state.players[c.seat].name
        rows.append(f"  [D{c.day}/{c.kind}] {who}: {c.text_en}")
    return "\n".join(rows) or "  (还没有发言)"


def _public_block(state: GameState) -> str:
    return (f"== 公共局面 ==\n第 {state.day} 天。阶段: {state.phase.value}。\n"
            f"座位表:\n{_roster_line(state)}\n"
            f"全桌共享梗(可玩,按 requires 在场):\n{P.gags_block(_present_ids(state))}\n"
            f"发言与事件记录(最近):\n{_chat_tail(state)}")


def _private_line(state: GameState, seat: int) -> str:
    p = state.players[seat]
    bits = [f"身份={ROLE_LABELS[p.role]['zh']}({p.role.value})"]
    if p.role == Role.MAFIA:
        mates = [state.players[s].name for s in state.mafia_seats(alive_only=False) if s != seat]
        bits.append(f"mafia 队友={mates}")
    if p.role == Role.SHERIFF and state.sheriff_private:
        bits.append("历史查验=" + "; ".join(
            f"N{n} {state.players[t].name}:{'MAFIA' if r else '好人'}"
            for n, t, r in state.sheriff_private))
    if p.role == Role.ANGEL and state.angel_last_save is not None:
        bits.append(f"昨晚守护了 {state.players[state.angel_last_save].name}(今晚不能再守同一人)")
    chem = P.chemistry_block(p.persona_id, state.chemistry_active)
    if chem:
        bits.append("\n" + chem)
    return f"- seat{seat} {p.name}: " + "; ".join(bits)


def _cards_block(state: GameState, seats: list[int]) -> str:
    present = _present_ids(state)
    return "\n\n".join(P.render_card(_persona_of(state, s), state.players[s].role, present)
                       for s in seats)


def _lang_note(state: GameState) -> str:
    if state.lang == "en":
        return "本局纯英文模式: 只输出 text_en 字段。"
    return "双语: text_en 英文原话 + text_zh 腔调化中文。"


def _alive_ai(state: GameState) -> list[int]:
    return [p.id for p in state.alive_players() if not p.is_human]


def _seat_names(state: GameState, seats: list[int]) -> str:
    return ", ".join(f"seat{s}={state.players[s].name}" for s in seats)


def _get_texts(item: dict) -> tuple[str, str]:
    en = str(item.get("text_en", "")).strip()
    zh = str(item.get("text_zh", "")).strip()
    return en or zh, zh or en


# ---------- night ----------

def ai_night(state: GameState) -> dict:
    """Returns {"kill":(actor,target)|None, "check":..., "save":...,
    "dawn":(en,zh), "ghosts":[{seat,en,zh}]} for AI-held actions only."""
    rng = random.Random((state.seed or 0) + state.day * 77)
    from engine.transitions import night_required
    req = night_required(state)
    mafia_ai = [s for s in state.mafia_seats() if not state.players[s].is_human]
    sheriff = state.seat_with_role(Role.SHERIFF)
    angel = state.seat_with_role(Role.ANGEL)
    ai_kill = "kill" in req and mafia_ai and not (
        state.players[0].alive and state.players[0].role == Role.MAFIA)
    ai_check = "check" in req and sheriff is not None and not state.players[sheriff].is_human
    ai_save = "save" in req and angel is not None and not state.players[angel].is_human

    actor_seats = []
    tasks = []
    if ai_kill:
        actor_seats += mafia_ai
        non_mafia = [s for s in state.alive_seats() if state.players[s].role != Role.MAFIA]
        tasks.append(f'1. mafia 队({_seat_names(state, mafia_ai)})合议今晚击杀目标。'
                     f'可选 seat: {non_mafia}。结合每人的私心倾向与全局战略。'
                     f'输出 "mafia_kill": {{"target": <int>, "reasoning": "私密日志"}}')
    if ai_check:
        actor_seats.append(sheriff)
        cand = [s for s in state.alive_seats() if s != sheriff]
        tasks.append(f'2. 警长 {state.players[sheriff].name} 选查验目标，可选 {cand}。'
                     f'输出 "sheriff_check": <int>')
    if ai_save:
        actor_seats.append(angel)
        cand = [s for s in state.alive_seats() if s != state.angel_last_save]
        tasks.append(f'3. 天使 {state.players[angel].name} 选守护目标(可守自己, 不能连守同一人)，'
                     f'可选 {cand}。输出 "angel_save": <int>')

    dead_npcs = [p.id for p in state.players if not p.alive and not p.is_human]
    tasks.append('4. 以 Mike Solana 的腔调写"黎明播报"占位句 narration_dead / narration_quiet 两个版本: '
                 'narration_dead 假设今晚有人死(用 {VICTIM} 占位真名, 死法必须贴合死者群体的硅谷人设风格, '
                 '参考节目定制死法传统), narration_quiet 假设没人死("quiet night"风格)。'
                 '每个版本输出 {"en": "...", "zh": "..."}')
    if dead_npcs:
        tasks.append(f'5. 已死亡 NPC({_seat_names(state, dead_npcs)})各给一句 ghost 吐槽'
                     '(看不到任何私密信息, 纯 meta 幽默, 符合各自人设)。'
                     '输出 "ghost_lines": [{"seat": <int>, "en": "...", "zh": "..."}]')

    card_seats = sorted(set(actor_seats + dead_npcs))
    solana_card = P.render_card(P.solana(), Role.TOWN, _present_ids(state))
    prompt = (f"{_public_block(state)}\n\n== 主持人卡 ==\n{solana_card}\n\n"
              f"== 涉及 NPC persona 卡 ==\n{_cards_block(state, card_seats)}\n\n"
              f"== 各自私密信息(互相隔离) ==\n"
              + "\n".join(_private_line(state, s) for s in sorted(set(actor_seats)))
              + f"\n\n== 夜晚任务 ==\n" + "\n".join(tasks)
              + f"\n\n{_lang_note(state)}\n只输出一个 JSON 对象，包含上述要求的字段。")

    try:
        data = call_llm(SYSTEM, prompt, f"night_d{state.day}")
    except Exception:
        data = {}

    out: dict = {"kill": None, "check": None, "save": None, "dawn": None, "ghosts": []}
    alive = set(state.alive_seats())
    if ai_kill:
        tgt = (data.get("mafia_kill") or {}).get("target") if isinstance(data.get("mafia_kill"), dict) \
            else data.get("mafia_kill")
        non_mafia = [s for s in alive if state.players[s].role != Role.MAFIA]
        if not (isinstance(tgt, int) and tgt in non_mafia):
            tgt = rng.choice(non_mafia)
        out["kill"] = (mafia_ai[0], tgt)
    if ai_check:
        tgt = data.get("sheriff_check")
        cand = [s for s in alive if s != sheriff]
        if not (isinstance(tgt, int) and tgt in cand):
            tgt = rng.choice(cand)
        out["check"] = (sheriff, tgt)
    if ai_save:
        tgt = data.get("angel_save")
        cand = [s for s in alive if s != state.angel_last_save]
        if not (isinstance(tgt, int) and tgt in cand):
            tgt = rng.choice(cand)
        out["save"] = (angel, tgt)
    out["dawn"] = {
        "dead": data.get("narration_dead") or {},
        "quiet": data.get("narration_quiet") or {},
    }
    for g in data.get("ghost_lines", []) or []:
        if isinstance(g, dict) and g.get("seat") in dead_npcs:
            en, zh = _get_texts({"text_en": g.get("en", ""), "text_zh": g.get("zh", "")})
            out["ghosts"].append({"seat": g["seat"], "en": en, "zh": zh})
    return out


def dawn_narration(out: dict, state: GameState, death: int | None) -> tuple[str, str]:
    d = out.get("dawn") or {}
    if death is None:
        q = d.get("quiet") or {}
        return q.get("en", ""), q.get("zh", "")
    v = d.get("dead") or {}
    name = state.players[death].name
    en = (v.get("en") or "").replace("{VICTIM}", name)
    zh = (v.get("zh") or "").replace("{VICTIM}", name)
    return en, zh


# ---------- discussion waves ----------

def wave_seats(state: GameState) -> list[int]:
    """Seats speaking in the current wave (alive NPCs split across waves)."""
    seats = _alive_ai(state)
    waves = max(1, state.waves_per_day)
    per = -(-len(seats) // waves)  # ceil
    start = state.wave_idx * per
    return seats[start:start + per]


def ai_discussion_wave(state: GameState) -> list[tuple[int, str, str]]:
    seats = wave_seats(state)
    if not seats:
        return []
    prompt = (f"{_public_block(state)}\n\n"
              f"== 本 wave 发言者 persona 卡 ==\n{_cards_block(state, seats)}\n\n"
              f"== 各自私密信息(互相隔离) ==\n"
              + "\n".join(_private_line(state, s) for s in seats)
              + f"\n\n== 任务 ==\n第 {state.day} 天讨论 wave {state.wave_idx + 1}。"
              f"为 {_seat_names(state, seats)} 各生成一段桌面发言(1-3句)。"
              "要接前面发言的话茬(包括人类玩家的话)，可以指认、怼人、玩在场的梗。"
              f"\n{_lang_note(state)}\n"
              f'只输出 JSON: {{"speeches": [{{"seat": <int>, {LANG_FIELDS[state.lang]}}}]}}')
    try:
        data = call_llm(SYSTEM, prompt, f"wave_d{state.day}w{state.wave_idx}")
    except Exception:
        data = {}
    got = {}
    for s in data.get("speeches", []) or []:
        if isinstance(s, dict) and s.get("seat") in seats:
            en, zh = _get_texts(s)
            if en:
                got[s["seat"]] = (en, zh)
    out = []
    for seat in seats:
        en, zh = got.get(seat, ("(listens quietly)", "(安静观察中)"))
        out.append((seat, en, zh))
    return out


# ---------- nominations ----------

def ai_nominations(state: GameState) -> list[tuple[int, int | None, str, str]]:
    seats = [s for s in _alive_ai(state) if s not in state.current_day.nominations]
    if not seats:
        return []
    alive = state.alive_seats()
    prompt = (f"{_public_block(state)}\n\n"
              f"== 提名者 persona 卡 ==\n{_cards_block(state, seats)}\n\n"
              f"== 各自私密信息(互相隔离) ==\n"
              + "\n".join(_private_line(state, s) for s in seats)
              + f"\n\n== 任务 ==\n提名审判: {_seat_names(state, seats)} 各提名一个想送上审判席的人"
              f"(可选 seat: {alive}, 不能提名自己, target=null 表示弃权)，配一句话理由。"
              f"\n{_lang_note(state)}\n"
              f'只输出 JSON: {{"nominations": [{{"seat": <int>, "target": <int|null>, '
              f'{LANG_FIELDS[state.lang]}}}]}}')
    try:
        data = call_llm(SYSTEM, prompt, f"nom_d{state.day}")
    except Exception:
        data = {}
    got = {}
    for item in data.get("nominations", []) or []:
        if isinstance(item, dict) and item.get("seat") in seats:
            tgt = item.get("target")
            if not (isinstance(tgt, int) and tgt in alive and tgt != item["seat"]):
                tgt = None
            en, zh = _get_texts(item)
            got[item["seat"]] = (tgt, en, zh)
    return [(s, *got.get(s, (None, "", ""))) for s in seats]


# ---------- trial defenses ----------

def ai_defenses(state: GameState) -> list[tuple[int, str, str]]:
    seats = [s for s in state.current_day.defendants
             if not state.players[s].is_human and s not in state.current_day.defenses_done]
    if not seats:
        return []
    prompt = (f"{_public_block(state)}\n\n"
              f"== 被审判者 persona 卡 ==\n{_cards_block(state, seats)}\n\n"
              f"== 各自私密信息(互相隔离) ==\n"
              + "\n".join(_private_line(state, s) for s in seats)
              + "\n\n== 任务 ==\n审判席 15 秒辩护(参考节目: Moxie 亮天使+概率论证, Trae 主动上庭反杀)。"
              f"为 {_seat_names(state, seats)} 各写一段辩护(2-4句, 这是生死陈词, 必须有戏)。"
              "可以亮身份(真假皆可)、反指控、用规则话术。"
              f"\n{_lang_note(state)}\n"
              f'只输出 JSON: {{"defenses": [{{"seat": <int>, {LANG_FIELDS[state.lang]}}}]}}')
    try:
        data = call_llm(SYSTEM, prompt, f"trial_d{state.day}")
    except Exception:
        data = {}
    got = {}
    for item in data.get("defenses", []) or []:
        if isinstance(item, dict) and item.get("seat") in seats:
            en, zh = _get_texts(item)
            if en:
                got[item["seat"]] = (en, zh)
    out = []
    for s in seats:
        en, zh = got.get(s, ("I did not do it. That is all.", "不是我干的。说完了。"))
        out.append((s, en, zh))
    return out


# ---------- verdict ----------

def ai_verdict(state: GameState) -> dict:
    """Returns {"votes":[(seat,target|None,reason_en,reason_zh)], "death_flavor":{en,zh}}."""
    from engine.transitions import verdict_voters
    seats = [s for s in verdict_voters(state)
             if not state.players[s].is_human and s not in state.current_day.votes]
    defendants = state.current_day.defendants
    if not seats:
        return {"votes": [], "death_flavor": {}}
    dnames = _seat_names(state, defendants)
    prompt = (f"{_public_block(state)}\n\n"
              f"== 投票者 persona 卡 ==\n{_cards_block(state, seats)}\n\n"
              f"== 各自私密信息(互相隔离) ==\n"
              + "\n".join(_private_line(state, s) for s in seats)
              + f"\n\n== 任务 ==\n公开亮票。被审判者: {dnames}。"
              f"{_seat_names(state, seats)} 各投一票(target 必须是 {defendants} 之一, null=弃权)"
              "配一句话理由(节目精华格式, 要有人味)。mafia 投票时记得演好人。"
              "\n另外: 以 Solana 腔调为每位被审判者各写一句'若 TA 被处决'的定制死法播报"
              "(死法必须贴合该死者本人的公司/人设, 节目定制死法传统)。"
              f"\n{_lang_note(state)}\n"
              f'只输出 JSON: {{"votes": [{{"seat": <int>, "target": <int|null>, '
              f'{LANG_FIELDS[state.lang]}}}], '
              f'"execution_flavor": {{"<defendant_seat>": {{"en": "...", "zh": "..."}}, ...}}}}')
    try:
        data = call_llm(SYSTEM, prompt, f"verdict_d{state.day}")
    except Exception:
        data = {}
    # 保留 LLM/剧本给出的亮票顺序(戏剧性所在), 漏掉的座位补在最后
    rng = random.Random((state.seed or 0) + state.day * 31)
    votes, seen = [], set()
    for item in data.get("votes", []) or []:
        if isinstance(item, dict) and item.get("seat") in seats and item["seat"] not in seen:
            tgt = item.get("target")
            if not (isinstance(tgt, int) and tgt in defendants):
                tgt = None
            en, zh = _get_texts(item)
            votes.append((item["seat"], tgt, en, zh))
            seen.add(item["seat"])
    for s in seats:
        if s not in seen:
            votes.append((s, rng.choice(defendants), "", ""))
    return {"votes": votes, "death_flavor": data.get("execution_flavor") or {}}


def execution_narration(flavor: dict, state: GameState, executed: int) -> tuple[str, str]:
    p = state.players[executed]
    role_en = ROLE_LABELS[p.role]["en"]
    role_zh = ROLE_LABELS[p.role]["zh"]
    # flavor 可能是 {seat: {en,zh}}(新) 或 {en,zh}(旧/降级)
    item = flavor.get(str(executed)) or flavor.get(executed) or flavor
    if not isinstance(item, dict):
        item = {}
    en = (item.get("en") or "").replace("{VICTIM}", p.name)
    zh = (item.get("zh") or "").replace("{VICTIM}", p.name)
    if en:
        en += f" The card flips: {p.name} was {role_en.upper()}."
        zh += f" 翻牌：{p.name} 的身份是——{role_zh}。"
    return en, zh
