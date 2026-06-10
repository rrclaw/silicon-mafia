"""Generate 20x20 pixel-art avatars for all personas -> static/sprites/*.png
(idle / talk / dead frames, x8 scale). 仿 build_clawd.py 的「像素数组即资产」思路，
但 19 人用过程式生成: 基础人形模板 + 每人配色/发型/配件配置。

Run: python3.11 data/sprites/build_sprites.py
"""
from pathlib import Path

from PIL import Image

S = 20          # grid size
SCALE = 8       # output 160x160
OUT = Path(__file__).resolve().parent.parent.parent / "static" / "sprites"

# palette helpers
SKIN = {"fair": (240, 200, 170), "tan": (220, 180, 140), "glow": (250, 215, 185),
        "pale": (235, 210, 190), "med": (200, 160, 125), "brown": (170, 125, 90)}
HAIR = {"brown": (90, 60, 40), "dark": (45, 35, 30), "black": (25, 22, 20),
        "blond": (215, 180, 110), "grey": (150, 150, 150), "pink": (235, 90, 180),
        "silver": (190, 190, 195)}

CHARS = {
    # id: skin, hair color, hair style, shirt rgb, extras
    "altman":   dict(skin="fair", hair="brown", style="short", shirt=(120, 125, 135)),
    "palmer":   dict(skin="tan", hair="brown", style="messy", shirt=(200, 60, 50),
                     pattern="hawaii", goatee=True),
    "bryan":    dict(skin="glow", hair="dark", style="short", shirt=(30, 30, 35)),
    "moxie":    dict(skin="fair", hair="dark", style="beanie", shirt=(50, 55, 70),
                     beard=True, beanie=(40, 45, 55)),
    "trae":     dict(skin="fair", hair="blond", style="side", shirt=(40, 60, 100)),
    "dylan":    dict(skin="fair", hair="dark", style="curly", shirt=(235, 235, 230)),
    "liv":      dict(skin="fair", hair="blond", style="long", shirt=(60, 50, 80)),
    "tim":      dict(skin="fair", hair="brown", style="short", shirt=(70, 130, 90)),
    "cyan":     dict(skin="fair", hair="dark", style="bob", shirt=(225, 220, 210),
                     streak=(80, 200, 220)),
    "ryan_petersen": dict(skin="tan", hair="brown", style="short", shirt=(40, 90, 180)),
    "josie":    dict(skin="pale", hair="pink", style="wild", shirt=(120, 40, 160)),
    "beiermeister":  dict(skin="fair", hair="brown", style="long", shirt=(180, 50, 60)),
    "musk":     dict(skin="fair", hair="dark", style="short", shirt=(20, 20, 22)),
    "jensen":   dict(skin="med", hair="silver", style="side", shirt=(35, 32, 38),
                     pattern="leather", glasses=True),
    "dario":    dict(skin="fair", hair="dark", style="curly", shirt=(70, 100, 160),
                     glasses=True),
    "ilya":     dict(skin="fair", hair="grey", style="balding", shirt=(110, 110, 115),
                     beard=True),
    "thiel":    dict(skin="fair", hair="blond", style="side", shirt=(60, 60, 70),
                     pattern="suit"),
    "zuck":     dict(skin="pale", hair="brown", style="curly", shirt=(130, 135, 140),
                     chain=True),
    "solana":   dict(skin="tan", hair="dark", style="bandana", shirt=(90, 30, 35),
                     bandana=(160, 40, 45)),
    "cook":     dict(skin="fair", hair="silver", style="short", shirt=(40, 55, 95),
                     glasses=True),
    "bezos":    dict(skin="tan", hair="dark", style="bald", shirt=(45, 45, 50)),
    "gates":    dict(skin="fair", hair="grey", style="side", shirt=(165, 60, 130),
                     glasses=True),
    "pichai":   dict(skin="brown", hair="grey", style="short", shirt=(105, 105, 115),
                     glasses=True, beard=True),
    "karpathy": dict(skin="fair", hair="dark", style="short", shirt=(45, 120, 130)),
    "son":      dict(skin="med", hair="grey", style="balding", shirt=(50, 48, 60),
                     pattern="suit", glasses=True),
}

OUTLINE = (30, 25, 28)


def base_grid(cfg) -> list[list]:
    g = [[None] * S for _ in range(S)]
    skin = SKIN[cfg["skin"]]
    hair = HAIR[cfg["hair"]]
    shirt = cfg["shirt"]

    def rect(x0, y0, x1, y1, c):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                g[y][x] = c

    # head
    rect(6, 4, 13, 12, skin)
    # ears
    g[8][5] = skin; g[9][5] = skin; g[8][14] = skin; g[9][14] = skin
    # hair styles
    st = cfg["style"]
    if st in ("short", "messy", "side"):
        rect(6, 3, 13, 5, hair)
        if st == "messy":
            g[5][2] = hair; g[14][2] = hair; g[7][1] = hair
        if st == "side":
            rect(6, 5, 8, 6, hair)
    elif st == "curly":
        rect(5, 3, 14, 6, hair)
        g[5][2] = hair; g[14][2] = hair
    elif st == "wild":
        rect(5, 2, 14, 6, hair)
        g[4][3] = hair; g[15][3] = hair; g[4][1] = hair; g[15][1] = hair; g[9][1] = hair
    elif st == "long":
        rect(5, 3, 14, 6, hair)
        rect(4, 6, 5, 13, hair); rect(14, 6, 15, 13, hair)
    elif st == "bob":
        rect(5, 3, 14, 5, hair)
        rect(5, 5, 6, 11, hair); rect(13, 5, 14, 11, hair)
        if cfg.get("streak"):
            for y in range(5, 11):
                g[y][13] = cfg["streak"]
    elif st == "balding":
        rect(6, 3, 7, 4, hair); rect(12, 3, 13, 4, hair)
    elif st == "bald":
        pass
    elif st == "beanie":
        rect(5, 2, 14, 6, cfg.get("beanie", hair))
    elif st == "bandana":
        rect(5, 3, 14, 6, cfg.get("bandana", hair))
        g[15][6] = cfg.get("bandana", hair); g[16][7] = cfg.get("bandana", hair)
    # eyes (row 8) — pupils dark
    g[8][8] = (35, 30, 30); g[8][11] = (35, 30, 30)
    if cfg.get("glasses"):
        gl = (20, 20, 20)
        for x in (7, 8, 9, 10, 11, 12):
            g[7][x] = gl
        g[8][7] = gl; g[8][9] = gl; g[8][10] = gl; g[8][12] = gl
    # facial hair
    if cfg.get("beard"):
        rect(7, 11, 12, 12, HAIR[cfg["hair"]])
    if cfg.get("goatee"):
        g[11][9] = HAIR[cfg["hair"]]; g[11][10] = HAIR[cfg["hair"]]
        g[12][9] = HAIR[cfg["hair"]]; g[12][10] = HAIR[cfg["hair"]]
    # mouth (row 11) — overwritten by frames
    # body
    rect(5, 13, 14, 19, shirt)
    rect(3, 14, 4, 17, shirt)   # arms
    rect(15, 14, 16, 17, shirt)
    pat = cfg.get("pattern")
    if pat == "hawaii":
        for (x, y) in [(7, 15), (10, 14), (12, 16), (8, 18), (13, 18), (6, 17)]:
            g[y][x] = (250, 220, 120)
    elif pat == "leather":
        for y in range(13, 20):
            g[y][9] = (15, 14, 16); g[y][10] = (60, 56, 62)
    elif pat == "suit":
        rect(8, 13, 11, 19, (235, 235, 235))
        for y in range(13, 19):
            g[y][9] = (140, 40, 50) if y < 17 else (235, 235, 235)
    if cfg.get("chain"):
        for x in range(7, 13):
            g[13][x] = (230, 190, 80)
    return g


def render(g, mouth: str, dead: bool) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    px = img.load()
    for y in range(S):
        for x in range(S):
            c = g[y][x]
            if c is None:
                continue
            if dead:
                avg = int(sum(c) / 3)
                c = (avg, avg, avg)
            px[x, y] = (*c, 255)
    # mouth
    if dead:
        # X eyes
        for (ex) in (8, 11):
            px[ex - 1, 7] = (*OUTLINE, 255); px[ex + 1, 7] = (*OUTLINE, 255)
            px[ex, 8] = (*OUTLINE, 255)
            px[ex - 1, 9] = (*OUTLINE, 255); px[ex + 1, 9] = (*OUTLINE, 255)
        px[9, 11] = (*OUTLINE, 255); px[10, 11] = (*OUTLINE, 255)
    elif mouth == "open":
        px[9, 11] = (120, 50, 50, 255); px[10, 11] = (120, 50, 50, 255)
        px[9, 12] = (80, 30, 30, 255); px[10, 12] = (80, 30, 30, 255)
    else:
        px[9, 11] = (150, 90, 80, 255); px[10, 11] = (150, 90, 80, 255)
    return img.resize((S * SCALE, S * SCALE), Image.NEAREST)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for cid, cfg in CHARS.items():
        g = base_grid(cfg)
        render(g, "closed", False).save(OUT / f"{cid}_idle.png")
        render(g, "open", False).save(OUT / f"{cid}_talk.png")
        render(g, "closed", True).save(OUT / f"{cid}_dead.png")
    # generic human player avatar (hoodie, coral — Clawd 色)
    cfg = dict(skin="fair", hair="dark", style="short", shirt=(216, 119, 87))
    g = base_grid(cfg)
    render(g, "closed", False).save(OUT / "human_idle.png")
    render(g, "open", False).save(OUT / "human_talk.png")
    render(g, "closed", True).save(OUT / "human_dead.png")
    print(f"wrote {len(CHARS) * 3 + 3} sprites -> {OUT}")


if __name__ == "__main__":
    main()
