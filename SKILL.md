---
name: silicon-mafia
description: >
  硅谷大佬狼人杀(Silicon Mafia)游戏管理 skill。当用户说"玩狼人杀 / 硅谷狼人杀 /
  和马斯克(大佬)玩狼人杀 / 开一局 mafia / 启动狼人杀 / 狼人杀演示局 / 加个新大佬 /
  狼人杀加角色 / 改人设卡 / 狼人杀跑测试 / silicon mafia"时使用。
  负责:启动/停止本地游戏服务并打开浏览器、跑一键演示局、终端版人机对局、
  配置 LLM 后端(Anthropic / DeepSeek / GLM / Kimi / 任意 OpenAI 兼容 / Claude Code 订阅)、
  新增 persona 角色卡+像素头像+宿敌彩蛋、跑引擎测试与声线保真盲测、排查对局卡死。
---

# Silicon Mafia · 硅谷大佬狼人杀

复刻 Founders Fund 真人秀《MAFIA》的单机狼人杀:玩家与 11 个 LLM 驱动的硅谷大佬 NPC
同桌(24 人池),节目规则(3 Mafia / 1 Sheriff / 1 Angel + Trial 审判制),Mike Solana 主持,
像素 UI + 浏览器 TTS。粉丝二创,开源免费,未克隆任何真人声音。

## 快速启动

```bash
pip install -r requirements.txt          # 首次
python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8301
# 打开 http://127.0.0.1:8301 → 选 11 位大佬 → 开局
```

- 用户说"开一局/启动游戏" → 起服务 + 提示打开浏览器(或代开)。
- 服务是**内存态**:重启丢对局。重启命令同上(先 `lsof -ti:8301 | xargs kill`)。
- 每次 LLM 调用日志落 `logs/<ts>_<label>.log`,排查 NPC 行为先看这里。

## LLM 后端(自带 key,五选一)

`.env`(参考 `.env.example`),选择顺序:`MAFIA_PROVIDER` 显式指定 > 按 key 自动探测 > claude CLI:

| Provider | 配置 | 说明 |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | persona 保真度最佳,默认 `claude-sonnet-4-6`,`MAFIA_MODEL` 可改 |
| DeepSeek | `DEEPSEEK_API_KEY` | 便宜 |
| 智谱 GLM | `GLM_API_KEY` | |
| 任意 OpenAI 兼容 | `OPENAI_COMPAT_BASE_URL/_API_KEY/_MODEL` + `MAFIA_PROVIDER=openai` | Kimi/本地模型等 |
| Claude Code 订阅 | 什么都不填(需本机 `claude` CLI) | 走 `claude -p`,零 API 费 |

一局 12 人桌 ≈ 20-30 次调用、40-60 分钟;赶时间组局时选"快速(每天 1 轮发言)"。

## 玩法入口与 URL 参数

- **🎬 演示局按钮**(大厅):全明星桌剧本驱动自动演完一整局,零 LLM 消耗,适合第一次感受/录屏。
- 练习参数:`/?role=mafia|sheriff|angel|town`(强制自己身份)、`&seed=N`(固定发牌)、
  `&demo=1&auto=1&seed=14`(导演模式+自动驾驶,剧本在 `data/demo/ep06_script.json`)。
- 终端版:`python3 tests/play_cli.py`(`--bot` 纯 AI 自走,`--cast id1,id2,...` 指定阵容)。

## 新增/修改角色(最常见的二次开发)

1. **角色卡**:复制 `data/personas/<某人>.yaml` 改写。关键字段:`nickname_zh` 外号、
   `voice.verbal_tics/catchphrases` 口头禅(专属,他人禁用)、`play_style.as_mafia/as_town/...`
   分身份打法、`few_shot` 真实语料 2-4 条、`bio_zh` 人物档案(大厅 ⓘ 弹窗)、
   `voice_profile.hint` 必须带 `male_`/`female_` 前缀(TTS 按此分性别选音色)。
2. **像素头像**:在 `data/sprites/build_sprites.py` 的 `CHARS` 加一行配置(肤色/发型/衣服/配件),
   跑 `python3 data/sprites/build_sprites.py` 生成 idle/talk/dead 三帧。
3. **宿敌/CP 彩蛋**(可选):`data/personas/_chemistry.yaml` 加 pair(type: blood_feud/rivalry/
   alliance/banter + bias + flavor),两人同桌自动激活;全桌共享梗在 `_table_gags.yaml`。
4. **必跑保真闸**:改完卡或 prompt,跑一局 bot 对局再 `python3 tests/eval_voice.py <对局日志>`,
   剥名盲测归属 **≥60% 才算过**(基线 97%)。

## 测试

```bash
python3 tests/smoke_engine.py     # 纯引擎 20 局自走 + 信息隔离断言(零 LLM,秒级)
python3 tests/play_cli.py --bot --seed 1   # 真 LLM 完整对局冒烟
python3 tests/eval_voice.py /tmp/game.log  # persona 声线盲测闸 ≥60%
```

## 架构速览

```
engine/      纯状态机:角色/相位(夜→讨论wave→提名→审判→亮票→翻牌)/胜负/视角脱敏,零 LLM
ai/          driver(五后端+导演模式) / personas(卡渲染) / actions(相位prompt+backfill) / orchestrator
data/personas/  角色卡+梗表+宿敌表 ← 游戏灵魂,改人设只动这里
data/demo/   导演模式剧本(label→响应 JSON)
server/      FastAPI :8301,内存对局+后台 AI worker
static/      vanilla JS 前端(无构建),sprites 由 build_sprites.py 生成
```

## 排查

- **对局卡住**:看 `logs/` 最新文件(LLM 超时/JSON 解析失败会重试一次,再失败走 backfill 默认,
  游戏不会死锁;若 UI 不动,刷新页面会静默恢复进度)。
- **NPC 串味/没人味**:跑 eval_voice;通常是 persona 卡被改稀释,或同 wave 塞了太多人。
- **TTS 声音性别不对/重复**:`voice_profile.hint` 缺 `male_/female_` 前缀;系统音色太少时
  下载更多(macOS:系统设置→辅助功能→朗读内容)。
- **弱模型(DeepSeek/GLM)JSON 不稳**:正常,backfill 全覆盖;persona 风味以 Claude 系为基准。

## 边界

- 粉丝二创、非商业;不做真人声音克隆(声音=系统 TTS/合成哔哔声)。
- 对局不落盘;公网部署需自行加持久化与鉴权,默认仅本机使用。
