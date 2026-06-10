"""Game state dataclasses. Pure data, no IO, no LLM."""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .rules import Role


class Phase(str, Enum):
    NIGHT = "night"
    DAY_DISCUSSION = "day_discussion"
    NOMINATION = "nomination"
    TRIAL = "trial"
    VERDICT = "verdict"
    GAME_OVER = "game_over"


@dataclass
class Player:
    id: int
    name: str                      # display name (EN)
    name_zh: str = ""
    persona_id: Optional[str] = None   # None => human
    is_human: bool = False
    role: Role = Role.TOWN
    alive: bool = True
    revealed: bool = False         # role publicly revealed (execution flips the card)


@dataclass
class ChatLine:
    seat: Optional[int]            # None => narrator (Solana) / system
    kind: str                      # narration|speech|ghost|system|defense|vote|reveal
    text_en: str
    text_zh: str = ""
    day: int = 0
    phase: str = ""


@dataclass
class NightRecord:
    night_idx: int
    kill_target: Optional[int] = None
    angel_save: Optional[int] = None
    sheriff_check: Optional[int] = None
    sheriff_result: Optional[bool] = None     # True => target is mafia
    death: Optional[int] = None               # resolved
    done: set = field(default_factory=set)    # {"kill","save","check"} submitted


@dataclass
class DayRecord:
    day_idx: int
    nominations: dict = field(default_factory=dict)   # seat -> target (or None abstain)
    defendants: list = field(default_factory=list)    # 1-2 seats on trial
    defenses_done: set = field(default_factory=set)   # seats that gave defense
    votes: dict = field(default_factory=dict)         # seat -> defendant seat or None
    executed: Optional[int] = None


@dataclass
class GameState:
    game_id: str
    players: list                      # list[Player], seat 0 = human
    phase: Phase = Phase.NIGHT
    day: int = 1                       # round counter; night N precedes day N
    wave_idx: int = 0
    waves_per_day: int = 2
    lang: str = "bilingual"            # bilingual|zh|en
    chat: list = field(default_factory=list)       # list[ChatLine]
    nights: list = field(default_factory=list)     # list[NightRecord]
    days: list = field(default_factory=list)       # list[DayRecord]
    winner: Optional[str] = None       # "mafia" | "town"
    angel_last_save: Optional[int] = None
    sheriff_private: list = field(default_factory=list)  # [(night_idx, target, is_mafia)]
    chemistry_active: list = field(default_factory=list) # active pair dicts (both at table)
    seed: Optional[int] = None

    @property
    def current_night(self) -> Optional[NightRecord]:
        return self.nights[-1] if self.nights else None

    @property
    def current_day(self) -> Optional[DayRecord]:
        return self.days[-1] if self.days else None

    def alive_players(self) -> list:
        return [p for p in self.players if p.alive]

    def alive_seats(self) -> list[int]:
        return [p.id for p in self.players if p.alive]

    def mafia_seats(self, alive_only: bool = True) -> list[int]:
        return [p.id for p in self.players
                if p.role == Role.MAFIA and (p.alive or not alive_only)]

    def seat_with_role(self, role: Role, alive_only: bool = True) -> Optional[int]:
        for p in self.players:
            if p.role == role and (p.alive or not alive_only):
                return p.id
        return None

    def human(self):
        return self.players[0]


def new_game_id() -> str:
    return secrets.token_hex(4)
