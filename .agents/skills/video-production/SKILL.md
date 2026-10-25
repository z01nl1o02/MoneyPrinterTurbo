---
name: video-production
description: 本仓库（douyin-videokit）的视频制作全流程：输入分镜脚本 + 本地素材，产出抖音竖屏/B站横屏成片与发布包。涵盖新建批次、语速校核、Edge TTS 配音、素材预处理、词级 cue 锚定分镜、合成母版、QC 与发布策略。Use when the user asks to make/produce/edit a video, create a new video batch, run or debug the video pipeline (TTS/字幕/合成/切片), or package a video for publishing.
---

# 视频制作工作流（douyin-videokit）

**工具定位**：分镜脚本（人工）+ 本地素材 clips → Edge TTS 配音 → 词级大字幕 → MoviePy 合成 → loudnorm 母版 → 引流切片 + 封面 + 发布包。零 API Key、零外部下载。

深度细节见仓库根文档：`README.md`（目录结构与快速开始）、`MoneyPrinterTurbo_视频制作实战经验.md`（全部踩坑与方法论，本文是其浓缩）。做新视频前若时间允许，通读经验文档。

## 1. 环境与架构

```bash
uv sync    # 建 .venv（Python 3.11；依赖 moviepy==2.2.1 / edge-tts>=7.3.1 / pydub / pillow）
```
FFmpeg 用系统的。三个阶段：`seg`（ffmpeg 素材预处理）→ `compose`（MoviePy 叠层合成）→ `master`（loudnorm 母版 + 切片 + 封面）。

| 模块 | 职责 |
|---|---|
| `pipeline/config.py` | 全部可调参数：语速/画布/字体/配色/垫片/BGM/编码。平台差异在批次 build.py 运行时覆盖，**不改 pipeline** |
| `pipeline/tts.py` | Edge TTS 分场景配音 + 词级 cues 缓存（`work/tts/scene{id}.mp3+json`，存在即跳过） |
| `pipeline/prepare.py` | ffmpeg 预处理：cover 裁剪 / letterbox 模糊背景 / 慢放 / 定格帧 |
| `pipeline/textfx.py` | PIL 花字：印章/信息条/计数器/对比条/词级大字幕卡 |
| `pipeline/compose.py` | MoviePy 合成：场景组装/BGM/母版 loudnorm/切片 |

## 2. 新建批次

1. 复制模板批次为新目录 `videos/<YYYYMMDD>-<平台>/`：抖音竖屏参考 `videos/20261024-douyin/`（词级 cue 锚定），B站横屏参考 `videos/20261020A-bili/`（含 make_tts.py 抗网络抖动）
2. 放入 `clips/`（本地素材）与分镜脚本 md（`脚本/`，文案的事实来源）
3. 写批次 `build.py`：`SCENES` 分镜文案 → 镜头规划 → 花字时间轴（模板已含全部结构，替换数据即可）
4. 跑 `build.py all`，产出在 `output/`

## 3. 分镜脚本规范（写文案先于写代码）

- **语速校核**（以目标平台调性反推）：抖音 `+18%~+23%` ≈ 4.3~5 字/秒；B站知识区 `-12%` ≈ 4.7 字/秒
- **估算**：60s ≈ 280-300 字；**每个数字/百分号折算 ~1.5 个汉字**（数字读得又慢又顿）；时长 = 字数 ÷ 平台词速，**必须用 `plan` 子命令实测校核，不信脚本标称**
- 时长红线超了先删文案（砍重复修饰、保数字与情绪线），再调语速；`+25%` 起吐字明显发赶
- **逐场景分段写文案**（不要整篇一段）：每场时长独立可控、cue 天然分段、失败重试只影响一场
- 敏感词/平台违禁词在文案阶段就统一替换，配音/字幕/花字同源不分裂
- 素材→分镜映射表先写清楚（哪个 clip 对应哪段文案、走什么处理路线），再动手写代码

## 4. TTS 配音（Edge TTS，免费无 Key）

- 默认声音 `zh-CN-YunxiNeural`；词级时间戳必须显式 `boundary="WordBoundary"`（7.3.x 默认只给整句）
- **403 错误**：先查时钟偏移（比对微软域名 Date 响应头），时钟正常仍 403 → `uv pip install -U edge-tts`（旧客户端指纹被拒）
- 中文词文本一律写 UTF-8 JSON 文件，**不 print**（Windows GBK 乱码）
- 批量合成遇网络抖动/TCP 挂起：指数退避重试 + `asyncio.wait_for(collect(), 90)` 整体超时（B站批次的 `make_tts.py` 模式）；长任务一律 `python -u`
- 缓存按文件存在判断：改文案后需 `--force-tts` 才重做配音；**场景时长 = head垫 + 配音实测 + tail垫**，画面永远贴着配音走

## 5. 素材预处理（Stage A，重活全在 ffmpeg）

| 路线 | 适用 | 说明 |
|---|---|---|
| cover 裁剪 | 高能镜头（特写/碾压/计数器） | 中心裁剪铺满画布 |
| letterbox 模糊背景 | 宏观镜头（全景/图解） | 原帧缩放居中 + 同帧放大模糊压暗当背景，留白处放花字 |

- **慢放有帧率下限**：20fps 素材 ≥0.8x；60fps 可到 0.3~0.45x。**快进无下限**（短拍补时长优先快进让时长）
- 时长补齐用**定格 + Ken Burns 推近**（尾帧 freeze.png + `zoom_image`），比硬慢放自然；定格帧从已处理段里抽
- **素材时长先校验再切**：`need = ss + dur×speed + 0.15`，不够先降 speed/换素材，禁止盲切
- 素材契约建议**净底片**：无烧录字幕、HUD 全隐藏、主体居中——计数器/比分牌/梗全部后期 PIL，样式全系列统一

## 6. 词级 cue 锚点分镜（强烈推荐，改语速不需重写时间轴）

镜头/花字不手写秒数，声明 `V(src, at="锚点子串")`，`plan()` 把锚点翻译成时间轴，镜头时长 = 下一锚点 - 当前锚点。规则：

- 锚点子串**必须无标点**（cue 文本不含标点，拼接后查找）；数字/英文按原样可命中
- **场景开头第一句不能当后续镜头的锚点**（塌缩到 0 会把前面镜头挤成 0.6s）
- 单调钳制（≥前锚+0.6s）+ 上限钳制（≤dur-0.8s）；查不到回退音频等分并打 WARN
- **装饰层（梗/标签/计数器）显隐只依赖自身显示窗口，与素材段长度解耦**（素材排不满时梗会被静默跳过且不报错）
- 渲染前先跑 `build.py plan` 预览时间轴，两轮"删字→复测"不用浪费一次渲染

## 7. 合成（Stage B/C）

- 分层渲染：ffmpeg 做裁剪/变速（快 5~10 倍），MoviePy 只做叠层与时间轴；中间产物可单独检查，改样式只重跑 `compose`
- **MoviePy 2.x API**（v1 全改名）：`ImageClip()` 不收 PIL 对象 → `ImageClip(np.asarray(img))`；`resized()/with_start()/with_duration()/with_position()`；音量 `with_effects([MultiplyVolume(0.10)])`；切片 `subclipped()`；同尺寸串联 `concatenate_videoclips(scenes, method="chain")`
- 特效 lambda 收到的是**片段本地时间**（t - start）；弹入围绕中心：`resized(s)` 配 `with_position(lambda t: (x-(w0*s(t)-w0)/2, y-(h0*s(t)-h0)/2))`，w0/h0 闭包捕获原始尺寸
- BGM：曲库 RMS 择优，音量 0.10、跳前奏 6s 起、FadeIn 0.8/FadeOut 1.5；**曲库单曲仅 180s，长片用 `render(bgm=False)` + pydub 循环垫底烘成 `work/bgm_pad.mp3`，母版阶段单 pass ffmpeg amix 混入**（视频流直拷，秒级）
- 母版必须 `loudnorm=I=-14:TP=-1.5:LRA=11`（视频流直拷只重编音频）；抖音规格：1080×1920/30fps/h264+aac，crf 20

## 8. 字幕与花字（PIL 预烘焙 PNG）

- 断句：词 cue 累积，**遇标点且 ≥6 字断句，或硬上限 14 字**；单元宽 ≤920px（横屏 1400/20字）一行，否则按词边界均衡拆两行；"数字+单位"防拆两卡
- 配色：白字黑边（stroke 6px）；**含数字的词 → 黄色 #FFD60A**；关键词（RED_WORDS，批次覆盖）→ 红色；卡片时间 = 首词起点 ~ 末词终点+0.06s，与下一卡去重叠
- 花字（印章/信息条/计数器/对比条/比分牌）全部 PIL 画好存盘，**倾斜直接烘进 PNG**，MoviePy 端只做位置 + 弹入缩放
- 字体：用 `resource/fonts/` 随仓库字体（ttc 记得 `index=0`）；中文字体必须显式指定

## 9. QC（用代码算时间轴，禁止手抄秒数）

- QC 脚本 `import` 批次 build.py 复用同一份 `scenes`/锚点函数；采样点 = `Σ 前序 dur + cue`
- **像素统计验证叠层存在**：成片抽帧统计字幕带白像素数/高亮色数/特定色块数（正常字幕卡 1.5~2.3 万白像素，0 即缺失）；注意场景边界帧本就无字幕、画面红色元素会干扰红色判定
- 判定"没渲染"前，先核实采样时间戳确实落在该元素显示窗口内；可对单场景 `CompositeVideoClip(...).get_frame(t)` 帧级验证，不必重渲整片
- 音频：`silencedetect=noise=-33dB:d=1.2` 无 >1.2s 断档；响度用 `volumedetect`（注意 `-v error` 会吞统计输出）；规格 ffprobe 核对

## 10. 发布包（交付四件套）

正片 + 引流切片 + 封面 + 发布说明（标题/置顶评论/标签/发布时段）。策略：

- 切片 = 正片高能浓缩（钩子→最炸名场面→悬念提问），**要流量；正片要关注**；切片发同一账号、隔自然日、换标题封面、**换开场**（防判重）；切片 cuts 由「场景累计起点 + cue 锚点表达式」生成
- 切片完成导流使命（3~7 天）后隐藏/删除；正片数据差（完播 <15%）按切片思路重剪（改动 ≥30%）重发

## 11. 工程纪律

- **大脚本编辑后先 `ast.parse` 冒烟再跑**（防编辑工具误删/误插行）
- Windows 下 ffmpeg 子进程用 **list 参数 + capture_output**，不拼 shell；中文只出现在 UTF-8 文件里
- `S = {key: scene}` 字典与 `scenes` 列表命名一眼可分，防 `TypeError: string indices`
- 调参集中在批次 build.py 顶部；`plan`（预览）→ `seg` → `compose`（改样式只重跑）→ `master` 分阶段执行

## 12. 命令速查

```bash
uv sync                                                      # 首次建环境
.venv/Scripts/python.exe videos/<批次>/build.py plan         # 预览分镜时间轴（先跑这个）
.venv/Scripts/python.exe videos/<批次>/build.py all          # 全流程
.venv/Scripts/python.exe videos/<批次>/build.py compose      # 只重合成（改样式后）
.venv/Scripts/python.exe videos/<批次>/build.py --force-tts all  # 重做配音
.venv/Scripts/python.exe -u videos/20261020A-bili/make_tts.py   # B站长片：先预生成配音
```
