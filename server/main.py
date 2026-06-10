"""FastAPI server for MAFIA @ Tosca Café. In-memory store + background AI worker
(forked from the avalon pattern). Run: uvicorn server.main:app --port 8301"""
from __future__ import annotations

import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (
    Role, Phase, new_game, submit_night_action, submit_speech, end_discussion,
    submit_nomination, submit_defense, submit_verdict_vote, visible_state,
)
from engine.rules import ROLE_DISTRIBUTION
from engine.transitions import night_required, verdict_voters
from ai.personas import (
    load_personas, roster_cards, ep001_roster, load_chemistry, playable_roster,
)
from ai import orchestrator as O
from ai.driver import get_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mafia.server")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="MAFIA @ Tosca Café")

AI_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai")


class Store:
    def __init__(self):
        self._games: dict[str, GameRunner] = {}
        self._lock = threading.Lock()

    def create(self, runner: "GameRunner"):
        with self._lock:
            self._games[runner.state.game_id] = runner

    def get(self, game_id: str) -> "GameRunner":
        with self._lock:
            r = self._games.get(game_id)
        if r is None:
            raise HTTPException(404, f"game {game_id} not found")
        return r

    def drop(self, game_id: str):
        with self._lock:
            self._games.pop(game_id, None)


STORE = Store()


class GameRunner:
    def __init__(self, state):
        self.state = state
        self.lock = threading.Lock()
        self.busy = False
        self._kick_pending = False
        self.last_error: Optional[str] = None
        self.current_step: Optional[str] = None
        self.step_started: float = 0.0

    # ---- what the AI still needs to do this phase ----
    def _needs_ai_locked(self) -> bool:
        s = self.state
        if s.winner is not None:
            return False
        if s.phase == Phase.NIGHT:
            req = night_required(s)
            human_holds = O.human_night_action_needed(s)
            ai_req = [a for a in req if not _human_holds_action(s, a)]
            return bool(ai_req) or (not req)
        if s.phase == Phase.DAY_DISCUSSION:
            if O.waves_left(s):
                return True
            return not s.players[0].alive  # auto-end discussion for dead human
        if s.phase == Phase.NOMINATION:
            pending = [x for x in s.alive_seats() if x not in s.current_day.nominations]
            ai_pending = [x for x in pending if not s.players[x].is_human]
            return bool(ai_pending) or not pending
        if s.phase == Phase.TRIAL:
            return any(not s.players[d].is_human and d not in s.current_day.defenses_done
                       for d in s.current_day.defendants)
        if s.phase == Phase.VERDICT:
            pending = [x for x in verdict_voters(s) if x not in s.current_day.votes]
            ai_pending = [x for x in pending if not s.players[x].is_human]
            return bool(ai_pending) or not pending
        return False

    def kick(self):
        with self.lock:
            if self.busy:
                self._kick_pending = True
                return
            if not self._needs_ai_locked():
                return
            self.busy = True
        AI_EXECUTOR.submit(self._loop)

    def _set_step(self, label: Optional[str]):
        self.current_step = label
        self.step_started = time.time() if label else 0.0

    def _loop(self):
        try:
            while True:
                with self.lock:
                    if not self._needs_ai_locked():
                        self.busy = False
                        self._set_step(None)
                        if self._kick_pending:
                            self._kick_pending = False
                            if self._needs_ai_locked():
                                self.busy = True
                                continue
                        return
                    phase = self.state.phase
                self._set_step(_step_label(self.state))
                try:
                    s = self.state
                    if phase == Phase.NIGHT:
                        if night_required(s) and any(
                                not _human_holds_action(s, a) for a in night_required(s)):
                            O.step_night(s)
                        with self.lock:
                            O.maybe_resolve_night(s)
                    elif phase == Phase.DAY_DISCUSSION:
                        if O.waves_left(s):
                            O.step_wave(s)
                        elif not s.players[0].alive:
                            with self.lock:
                                end_discussion(s)
                    elif phase == Phase.NOMINATION:
                        O.step_nominations(s)
                        with self.lock:
                            O.maybe_resolve_nominations(s)
                    elif phase == Phase.TRIAL:
                        O.step_defenses(s)
                    elif phase == Phase.VERDICT:
                        O.step_verdict(s)
                        with self.lock:
                            O.maybe_resolve_verdict(s)
                except Exception as e:  # noqa: BLE001
                    log.exception("AI step failed")
                    self.last_error = f"{type(e).__name__}: {e}"
                    with self.lock:
                        self.busy = False
                        self._set_step(None)
                    return
        finally:
            pass


def _human_holds_action(s, action: str) -> bool:
    me = s.players[0]
    if not me.alive:
        return False
    return ((action == "kill" and me.role == Role.MAFIA)
            or (action == "check" and me.role == Role.SHERIFF)
            or (action == "save" and me.role == Role.ANGEL))


def _step_label(s) -> str:
    if s.phase == Phase.NIGHT:
        return "夜晚行动中：大佬们在密谋…"
    if s.phase == Phase.DAY_DISCUSSION:
        seats = __import__("ai.actions", fromlist=["wave_seats"]).wave_seats(s)
        if seats:
            names = "、".join(s.players[x].name for x in seats[:2])
            return f"{names} 正在组织语言…"
        return "讨论收尾…"
    if s.phase == Phase.NOMINATION:
        return "大佬们在提名…"
    if s.phase == Phase.TRIAL:
        return "被审判者在辩护…"
    if s.phase == Phase.VERDICT:
        return "公开亮票中…"
    return "AI 思考中…"


# ---------- request models ----------

class NewGameReq(BaseModel):
    cast: Optional[list[str]] = None      # 11 persona ids; None => EP001 default
    human_name: str = "Player"
    lang: str = "bilingual"
    waves: int = 2
    seed: Optional[int] = None
    role: Optional[str] = None            # force human role (debug/practice)


class TextReq(BaseModel):
    text: str


class TargetReq(BaseModel):
    target: Optional[int] = None


class NightReq(BaseModel):
    action: str
    target: int


# ---------- endpoints ----------

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
async def meta():
    cards = []
    for c in playable_roster():
        cards.append({
            "id": c["id"], "name_en": c["name_en"], "name_zh": c.get("name_zh", ""),
            "nickname_zh": c.get("nickname_zh", ""), "nickname_en": c.get("nickname_en", ""),
            "tagline_zh": c.get("tagline_zh", ""), "source": c.get("source", ""),
            "voice_profile": c.get("voice_profile", {}),
        })
    return {
        "roster": cards,
        "ep001": ep001_roster(),
        "backend": get_backend().name,
        "player_counts": sorted(ROLE_DISTRIBUTION),
    }


@app.post("/api/game/new")
async def api_new_game(req: NewGameReq):
    all_ids = set(load_personas())
    ids = req.cast or ep001_roster()
    ids = [i for i in ids if i in all_ids and i != "solana"]
    absent = ""
    if len(ids) > 11:
        import random as _r
        rng = _r.Random(req.seed)
        absent_id = rng.choice(ids)
        absent = load_personas()[absent_id]["name_en"]
        ids = [i for i in ids if i != absent_id]
    if len(ids) + 1 not in ROLE_DISTRIBUTION:
        raise HTTPException(400, f"need 8-12 NPCs, got {len(ids)}")
    human_role = Role(req.role) if req.role else None
    state = new_game(roster_cards(ids), human_name=req.human_name.strip() or "Player",
                     lang=req.lang, waves_per_day=max(1, min(3, req.waves)),
                     seed=req.seed, human_role=human_role,
                     chemistry_pairs=load_chemistry())
    O.cold_open(state, absent_name=absent)
    runner = GameRunner(state)
    STORE.create(runner)
    runner.kick()
    return {"game_id": state.game_id}


@app.get("/api/game/{game_id}")
async def api_state(game_id: str):
    runner = STORE.get(game_id)
    runner.kick()  # self-heal
    with runner.lock:
        vs = visible_state(runner.state, viewer=0)
    vs["server"] = {
        "ai_busy": runner.busy,
        "step": runner.current_step,
        "step_elapsed": round(time.time() - runner.step_started, 1) if runner.busy and runner.step_started else 0,
        "last_error": runner.last_error,
        "backend": get_backend().name,
    }
    return JSONResponse(vs)


@app.post("/api/game/{game_id}/speak")
async def api_speak(game_id: str, req: TextReq):
    runner = STORE.get(game_id)
    with runner.lock:
        if runner.state.phase not in (Phase.DAY_DISCUSSION, Phase.NOMINATION):
            raise HTTPException(409, f"phase is {runner.state.phase.value}")
        submit_speech(runner.state, 0, req.text, req.text)
    runner.kick()
    return {"ok": True}


@app.post("/api/game/{game_id}/end_discussion")
async def api_end_discussion(game_id: str):
    runner = STORE.get(game_id)
    with runner.lock:
        if runner.state.phase != Phase.DAY_DISCUSSION:
            raise HTTPException(409, f"phase is {runner.state.phase.value}")
        end_discussion(runner.state)
    runner.kick()
    return {"ok": True}


@app.post("/api/game/{game_id}/night")
async def api_night(game_id: str, req: NightReq):
    runner = STORE.get(game_id)
    with runner.lock:
        s = runner.state
        if s.phase != Phase.NIGHT:
            raise HTTPException(409, f"phase is {s.phase.value}")
        try:
            submit_night_action(s, req.action, 0, req.target)
        except ValueError as e:
            raise HTTPException(400, str(e))
        result = None
        if req.action == "check":
            result = s.sheriff_private[-1][2]
        O.maybe_resolve_night(s)
    runner.kick()
    return {"ok": True, "check_result": result}


@app.post("/api/game/{game_id}/nominate")
async def api_nominate(game_id: str, req: TargetReq):
    runner = STORE.get(game_id)
    with runner.lock:
        s = runner.state
        if s.phase != Phase.NOMINATION:
            raise HTTPException(409, f"phase is {s.phase.value}")
        try:
            submit_nomination(s, 0, req.target)
        except ValueError as e:
            raise HTTPException(400, str(e))
        O.maybe_resolve_nominations(s)
    runner.kick()
    return {"ok": True}


@app.post("/api/game/{game_id}/defense")
async def api_defense(game_id: str, req: TextReq):
    runner = STORE.get(game_id)
    with runner.lock:
        s = runner.state
        if s.phase != Phase.TRIAL:
            raise HTTPException(409, f"phase is {s.phase.value}")
        try:
            submit_defense(s, 0, req.text, req.text)
        except ValueError as e:
            raise HTTPException(400, str(e))
    runner.kick()
    return {"ok": True}


@app.post("/api/game/{game_id}/vote")
async def api_vote(game_id: str, req: TargetReq):
    runner = STORE.get(game_id)
    with runner.lock:
        s = runner.state
        if s.phase != Phase.VERDICT:
            raise HTTPException(409, f"phase is {s.phase.value}")
        try:
            submit_verdict_vote(s, 0, req.target)
        except ValueError as e:
            raise HTTPException(400, str(e))
        O.maybe_resolve_verdict(s)
    runner.kick()
    return {"ok": True}


@app.post("/api/game/{game_id}/abandon")
async def api_abandon(game_id: str):
    STORE.drop(game_id)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
