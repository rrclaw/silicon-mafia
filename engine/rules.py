"""Role definitions and win conditions for MAFIA (Founders Fund EP001 rules).

Show terminology: 3 jacks = Mafia, 1 king = Sheriff (查验), 1 ace = Angel (守护),
rest = Townsperson. Trial system: nominate -> top-2 on trial -> 15s defenses -> vote.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    MAFIA = "mafia"
    SHERIFF = "sheriff"
    ANGEL = "angel"
    TOWN = "town"


ROLE_LABELS = {
    Role.MAFIA: {"en": "Mafia", "zh": "黑手党"},
    Role.SHERIFF: {"en": "Sheriff", "zh": "警长"},
    Role.ANGEL: {"en": "Angel", "zh": "天使"},
    Role.TOWN: {"en": "Townsperson", "zh": "村民"},
}

ROLE_CARDS = {  # 节目里的发牌梗
    Role.MAFIA: "J",
    Role.SHERIFF: "K",
    Role.ANGEL: "A",
    Role.TOWN: "#",
}

# n_players -> (n_mafia, n_sheriff, n_angel)
ROLE_DISTRIBUTION = {
    9: (2, 1, 1),
    10: (3, 1, 1),
    11: (3, 1, 1),
    12: (3, 1, 1),
    13: (3, 1, 1),
}


def supported_player_counts() -> list[int]:
    return sorted(ROLE_DISTRIBUTION)


def build_role_deck(n_players: int) -> list[Role]:
    n_mafia, n_sheriff, n_angel = ROLE_DISTRIBUTION[n_players]
    deck = [Role.MAFIA] * n_mafia + [Role.SHERIFF] * n_sheriff + [Role.ANGEL] * n_angel
    deck += [Role.TOWN] * (n_players - len(deck))
    return deck


def role_hint(role: Role) -> str:
    return {
        Role.MAFIA: "夜里和队友合议杀一人；白天伪装好人，把怀疑引向无辜者。mafia 人数 >= 存活好人数即获胜。",
        Role.SHERIFF: "每晚查验一人是否 mafia。信息是好人最大武器，但暴露身份会被优先刀。",
        Role.ANGEL: "每晚守护一人(可守自己, 不能连续两晚守同一人)。被守护者当晚免死。",
        Role.TOWN: "没有夜间能力。靠发言、投票和推理找出 mafia。",
    }[role]
