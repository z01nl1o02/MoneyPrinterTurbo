# 本地成片流水线（douyin-videokit）

由 [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) 实战精简而来：
2026-10-18 首次实战成片后，删除了未用到的 WebUI/API/LLM/图库/Whisper 等模块，
只保留实战验证过的最小闭环（原工程代码在本仓库 git 历史中，`git log` 可回溯）。
2026-10-20 新增B站横屏长片路线（`videos/20261020A-bili/`：词级锚点分镜 + 术语卡，
见实战经验文档第十一节）。


## 能做什么

**本地素材 + 人工脚本 → 竖屏/横屏成片**（抖音 / B站）：

```
分镜脚本(人工) ──► Edge TTS 分场景配音(免费) ──► 词级时间戳大字幕
clips 素材    ──► ffmpeg 竖屏预处理(裁剪/模糊背景/慢放/定格)
                  ──► MoviePy 花字/印章/计数器叠层 ──► BGM 混音 ──► loudnorm 母版
                  ──► 引流切片 + 封面 + 发布包
```

零 API Key、零本地模型、不下载外部视频。

## 目录结构

```
pipeline/            工具包（新视频批次只写分镜数据，不改动这里）
├── config.py        # 全部可调参数：语速/画布/字体/配色/垫片/BGM/编码
│                    #   （B站横屏等差异在批次 build.py 运行时覆盖，不改动这里）
├── tts.py           # Edge TTS 分场景配音 + 词级 cues 缓存
├── prepare.py       # ffmpeg 素材预处理（cover 裁剪 / letterbox 模糊背景 / 慢放 / 定格帧）
├── textfx.py        # PIL 花字：印章/信息条/计数器/对比条/词级大字幕
└── compose.py       # MoviePy 合成：场景组装/BGM/母版 loudnorm/切片
resource/
├── fonts/           # 随仓库字体（雅黑 ttc，跨机器可用）
└── songs/           # 内置 BGM 曲库（RMS 自动择优；单曲180s，长片需循环垫底）
videos/<批次>/       # 一次成片 = 一个批次
├── 脚本/            #   分镜脚本 md（文案的事实来源）
├── clips/           #   本地视频素材
├── build.py         #   批次构建脚本：SCENES 分镜数据 + 素材映射 + 花字时间轴
│                    #   （B站批次另有 make_tts.py：抗网络抖动的 TTS 预生成）
├── work/tts/        #   配音缓存（可再生，勿删可省 TTS 重做）
└── output/          #   成片/切片/封面/发布说明
```

## 快速开始

```bash
uv sync                                   # 建 .venv（Python 3.11）
.venv/Scripts/python.exe videos/20261018A/build.py all          # 抖音竖屏全流程
.venv/Scripts/python.exe videos/20261024-douyin/build.py all    # 抖音竖屏（词级 cue 锚定分镜）
.venv/Scripts/python.exe videos/20261018A/build.py compose      # 只重合成（改样式后）
.venv/Scripts/python.exe videos/20261018A/build.py --force-tts all  # 重做配音

# B站横屏长片（先预生成配音抗网络抖动，再全流程；plan 子命令可预览分镜时间轴）
.venv/Scripts/python.exe -u videos/20261020A-bili/make_tts.py
.venv/Scripts/python.exe videos/20261020A-bili/build.py all
```

分阶段：`seg`（素材预处理）→ `compose`（合成）→ `master`（母版+切片+封面）。

## 新做一条视频

> 在 pi coding agent 中可用 `/skill:video-production` 直接加载完整制作工作流
>（本仓库 `.agents/skills/video-production/`）。

1. 复制 `videos/20261018A/`（抖音竖屏）或 `videos/20261020A-bili/`（B站横屏）为新批次，放入 `clips/` 与 `脚本/`
2. 改 `build.py`：`SCENES` 分镜文案 → 镜头规划（竖屏版改 `build_segments()`/`build_layers()`；
   B站版改 `SHOTS` 词级锚点表，镜头/花字全部锚定配音 cue，改语速不需重写时间轴）
3. 场景时长 = `head + 配音实测 + tail` 自动计算；画面按配音长度自适应取材
4. 跑 `build.py all`，产出在 `output/`

## 必读经验

- **踩坑与参数**：[MoneyPrinterTurbo_视频制作实战经验.md](MoneyPrinterTurbo_视频制作实战经验.md)
  （edge-tts 403/词级时间戳、竖屏两条路线、MoviePy 2.x API、QC 手段、发布策略、
  B站横屏长片/词级锚点分镜/长片 BGM 循环）
- **原工程分析**：[MoneyPrinterTurbo_本地使用分析报告.md](MoneyPrinterTurbo_本地使用分析报告.md)
- 配音语速：抖音 `+18%` ≈ 5 字/秒；B站知识区 `-12%` ≈ 4.7 字/秒。先按目标平台语速校核脚本字数（60s ≈ 280-300 字）
