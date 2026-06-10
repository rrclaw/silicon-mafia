"""Persona fidelity gate: strip speaker names from a played game's NPC speeches,
shuffle, and ask the LLM to re-attribute each line (blind, names only — no
persona cards). Target: >=60% accuracy (random baseline ~9% at 11 speakers).

Usage:
    python3.11 tests/eval_voice.py /tmp/mafia_smoke.log
    python3.11 tests/eval_voice.py --game <game_id>   # from running server
"""
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.driver import call_llm

SPEAKER_RE = re.compile(r"^  ([A-Z][A-Za-z .]+): (.+)$")
SKIP = {"SOLANA", "rr"}

# 专属 tic 泄漏检查（保守集合，引用他人原话的场景不算泄漏故只查开头段）
EXCLUSIVE_TICS = {
    "Ryan Petersen": ["bill of lading"],
    "Liv Boeree": ["EV perspective"],
    "Trae Stephens": ["never been mafia"],
    "Ryan Beiermeister": ["100% town", "100% a town"],
}


def collect_from_log(path: str) -> list[tuple[str, str]]:
    out = []
    for line in Path(path).read_text().splitlines():
        m = SPEAKER_RE.match(line)
        if not m:
            continue
        who, text = m.group(1).strip(), m.group(2).strip()
        if who in SKIP or len(text) < 40 or text.startswith("("):
            continue
        out.append((who, text))
    return out


def collect_from_game(game_id: str) -> list[tuple[str, str]]:
    import urllib.request
    d = json.load(urllib.request.urlopen(f"http://127.0.0.1:8301/api/game/{game_id}"))
    names = {p["seat"]: p["name"] for p in d["players"]}
    out = []
    for c in d["chat"]:
        if c["kind"] in ("speech", "defense") and c["seat"] not in (None, 0) and len(c["en"]) >= 40:
            out.append((names[c["seat"]], c["en"]))
    return out


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--game":
        samples = collect_from_game(sys.argv[2])
    else:
        samples = collect_from_log(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mafia_smoke.log")
    if len(samples) < 10:
        print(f"not enough samples ({len(samples)})"); sys.exit(1)

    rng = random.Random(7)
    rng.shuffle(samples)
    samples = samples[:30]
    speakers = sorted({w for w, _ in samples})
    lines = [t for _, t in samples]

    # tic leakage (hard-ish check)
    leaks = []
    for owner, tics in EXCLUSIVE_TICS.items():
        for who, text in samples:
            if who != owner and any(t.lower() in text.lower() for t in tics):
                leaks.append((owner, who, text[:60]))

    prompt = ("以下是一局《硅谷大佬狼人杀》中 NPC 的发言（已打乱、匿名）。"
              f"可能的发言人(每行恰好一人): {speakers}\n"
              "根据语言风格、口头禅、思维方式判断每行是谁说的。\n\n"
              + "\n".join(f"{i}. {t}" for i, t in enumerate(lines))
              + '\n\n只输出 JSON: {"answers": ["<name>", ...]}  (按行号顺序, 名字必须来自候选列表)')
    data = call_llm("你是文风鉴定专家。只输出 JSON。", prompt, "eval_voice")
    answers = data.get("answers", [])
    correct = sum(1 for (who, _), a in zip(samples, answers) if str(a).strip() == who)
    acc = correct / len(samples)

    print(f"samples={len(samples)} speakers={len(speakers)} accuracy={acc:.0%} "
          f"(random baseline ~{1/len(speakers):.0%})")
    for (who, text), a in zip(samples, answers):
        mark = "✓" if str(a).strip() == who else "✗"
        print(f"  {mark} 真:{who:<18} 猜:{str(a):<18} {text[:60]}")
    if leaks:
        print("\n⚠ 专属 tic 泄漏:")
        for owner, who, text in leaks:
            print(f"  {owner} 的 tic 出现在 {who}: {text}")
    assert acc >= 0.6, f"voice fidelity {acc:.0%} < 60% gate"
    print("\nPASS: persona 声线保真 ≥60%")


if __name__ == "__main__":
    main()
