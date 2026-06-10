# MAFIA @ Tosca Café — 我和硅谷大佬玩狼人杀

> Play the party game *Mafia* (Werewolf) at a virtual Tosca Café table with
> LLM-driven NPC replicas of Silicon Valley figures — inspired by Founders Fund's
> reality show **MAFIA EP001** (June 2026). You sit in; Sam Altman dissects your
> speech patterns; Mike Solana invents a custom death for everyone.

![pixel style](https://img.shields.io/badge/style-pixel%20art-d87757)
![BYO key](https://img.shields.io/badge/LLM-bring%20your%20own%20key-blue)

## 是什么

- **12 人桌复刻节目规则**：3 Mafia / 1 Sheriff（查验）/ 1 Angel（守护，可自救、不能连守）
  / 7 Townspeople。白天走节目的 **Trial 审判制**：讨论 → 提名 → 上庭 15 秒辩护 → 公开亮票 → 翻牌。
- **19 个大佬 NPC**：EP001 原班 12 人（persona 取材自节目 transcript 蒸馏：Altman 的
  "definitive statements feel very mafia"、Trae 的"一百局没当过 mafia"、Bryan 的不死梗、
  Cyan 的面包房人设…）+ 扩展嘉宾 Musk / Jensen / Dario / Ilya / Thiel / Zuck。
- **宿敌化学反应**：特定大佬同桌自动激活彩蛋——Musk 夜里优先刀 Altman，Ilya 投 Altman
  时 Solana 会喊 "not again"，Jensen 和 Musk 互保（订单还没交付）。
- **Mike Solana 主持**：冷开场点名缺席者、为每个死者定制死法播报（Flexport 创始人
  会被装进五个集装箱）。
- **像素 UI**：Tosca Café 桌景、日夜转场、打字机气泡、翻牌处决动画、双语字幕
  （英文原声 + 中文）、浏览器 TTS 每人独立声线（或像素哔哔声）。

## 快速开始

需要 Python 3.11+。

```bash
git clone <this repo> mafia && cd mafia
pip install -r requirements.txt
cp .env.example .env        # 填一个你有的 key（任选其一）
python3 -m uvicorn server.main:app --port 8301
# 打开 http://127.0.0.1:8301
```

### 支持的 LLM（自带 key，任选其一）

| Provider | .env 配置 | 备注 |
|---|---|---|
| Anthropic Claude | `ANTHROPIC_API_KEY=sk-ant-...` | **persona 保真度最佳**（默认 `claude-sonnet-4-6`，可用 `MAFIA_MODEL` 改） |
| DeepSeek | `DEEPSEEK_API_KEY=sk-...` | 便宜，约 ¥1-3/局 |
| 智谱 GLM | `GLM_API_KEY=...` | |
| Kimi / 任意 OpenAI 兼容 | `OPENAI_COMPAT_BASE_URL` + `OPENAI_COMPAT_API_KEY` + `OPENAI_COMPAT_MODEL` | |
| Claude Code 订阅 | 什么都不填（需本机装 `claude` CLI） | 走 `claude -p`，零 API 费用 |

> persona 声线、双语质量以 Claude 系为基准调校；其他厂商可玩，风味会打折扣。

一局 12 人桌约 40-60 分钟、20-30 次 LLM 调用（Claude API 约 $0.5-2，DeepSeek 约 ¥1-3）。
赶时间可在组局时选「快速（每天 1 轮发言）」。

### 终端版（不开浏览器）

```bash
python3 tests/play_cli.py                 # 人机对局
python3 tests/play_cli.py --bot --seed 1  # 纯 AI 自走（冒烟测试）
```

## 测试

```bash
python3 tests/smoke_engine.py    # 纯引擎：20 局脚本自走 + 信息隔离断言（零 LLM）
python3 tests/eval_voice.py <game.log>  # persona 保真闸：剥名盲测归属 ≥60%
```

## 项目结构

```
engine/      纯状态机（角色/相位/胜负/视角脱敏），零 IO 零 LLM
ai/          driver(三后端) / personas(卡片渲染) / actions(相位 prompt) / orchestrator
data/personas/   19 张大佬 persona 卡(YAML) + 全桌梗表 + 宿敌化学表  ← 项目灵魂
data/transcript/ EP001 字幕 + 蒸馏 quote bank（build-time 素材）
server/      FastAPI + 内存对局 + 后台 AI worker
static/      像素前端（vanilla JS，无构建步骤）+ 程序化生成的 sprite
```

想加新大佬？复制一张 `data/personas/*.yaml` 改写（外号/口头禅/分身份打法/few_shot），
在 `data/sprites/build_sprites.py` 加一行配置跑一遍，就会出现在组局大厅。
宿敌彩蛋加在 `data/personas/_chemistry.yaml`。

## Disclaimer

This is a **non-commercial fan project** inspired by Founders Fund's "MAFIA" show.
All real-person characters are parody/satire portrayals for private entertainment.
Not affiliated with or endorsed by Founders Fund or any person depicted.
**No real-person voice cloning** — voices are generic browser TTS / synthesized blips.

License: MIT (code). Persona cards are parody content, same non-commercial intent.
