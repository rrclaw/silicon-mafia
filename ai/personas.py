"""Persona card loading + rendering into prompt blocks."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from engine.rules import Role

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "personas"

ROLE_STYLE_KEY = {
    Role.MAFIA: "as_mafia",
    Role.SHERIFF: "as_sheriff",
    Role.ANGEL: "as_angel",
    Role.TOWN: "as_town",
}


@lru_cache(maxsize=1)
def load_personas() -> dict[str, dict]:
    out = {}
    for f in sorted(DATA_DIR.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        card = yaml.safe_load(f.read_text())
        out[card["id"]] = card
    return out


@lru_cache(maxsize=1)
def load_gags() -> list[dict]:
    f = DATA_DIR / "_table_gags.yaml"
    return yaml.safe_load(f.read_text())["gags"] if f.exists() else []


@lru_cache(maxsize=1)
def load_chemistry() -> list[dict]:
    f = DATA_DIR / "_chemistry.yaml"
    return yaml.safe_load(f.read_text())["pairs"] if f.exists() else []


def roster_cards(persona_ids: list[str]) -> list[dict]:
    personas = load_personas()
    return [personas[i] for i in persona_ids]


def playable_roster() -> list[dict]:
    """All personas except the host."""
    return [c for c in load_personas().values() if c.get("role") != "host"]


def ep001_roster() -> list[str]:
    """The 12 real EP001 players (source == ep001_transcript, non-host)."""
    return [c["id"] for c in load_personas().values()
            if c.get("source") == "ep001_transcript" and c.get("role") != "host"]


def solana() -> dict:
    return load_personas()["solana"]


def render_card(card: dict, role: Role, present_ids: set[str]) -> str:
    """Render one persona into a compact prompt block, role-conditioned."""
    v = card.get("voice", {})
    lines = [
        f"### {card['name_en']}（{card.get('nickname_zh','')} / \"{card.get('nickname_en','')}\"）",
        f"语气: {v.get('register','')}",
        f"句式: {v.get('sentence_style','')}",
    ]
    tics = v.get("verbal_tics", []) + v.get("catchphrases", [])
    if tics:
        lines.append("口头禅(专属,他人禁用): " + " | ".join(tics))
    ps = card.get("play_style", {})
    style = ps.get(ROLE_STYLE_KEY[role], "")
    if style:
        lines.append(f"本局身份打法: {style}")
    if ps.get("tells"):
        lines.append(f"特征: {ps['tells']}")
    rels = card.get("relationships", {})
    rel_lines = [f"- 对 {k}: {txt}" for k, txt in rels.items() if k in present_ids]
    if rel_lines:
        lines.append("在场关系:\n" + "\n".join(rel_lines))
    fs = card.get("few_shot", [])
    if fs:
        lines.append("真实语料(模仿腔调,不要照抄):\n" + "\n".join(f"  > {q}" for q in fs[:3]))
    banned = card.get("banned", [])
    if banned:
        lines.append("此人绝不会: " + "、".join(banned))
    return "\n".join(lines)


def chemistry_block(persona_id: str, active_pairs: list[dict]) -> str:
    """Private chemistry directives for one NPC (only pairs involving them)."""
    out = []
    for p in active_pairs:
        if persona_id in p["pair"]:
            other = [x for x in p["pair"] if x != persona_id][0]
            bias = ", ".join(f"{k}={v}" for k, v in (p.get("bias") or {}).items())
            out.append(f"[私心·对 {other}] ({p['type']}; 倾向: {bias or '无'}) {p['flavor']}"
                       " —— 这是你的私人倾向，演出来但别太明显，绝不在发言里直说。")
    return "\n".join(out)


def gags_block(present_ids: set[str]) -> str:
    lines = []
    for g in load_gags():
        req = set(g.get("requires", []))
        if req <= present_ids:
            lines.append(f"- {g['text']}")
    return "\n".join(lines)
