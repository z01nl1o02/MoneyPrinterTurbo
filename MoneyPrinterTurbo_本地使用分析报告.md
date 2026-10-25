# MoneyPrinterTurbo 本地使用分析报告

> 基于对工程源码的纯静态分析整理（未运行任何工程代码），供后续使用该工程时参考。
> 分析对象：MoneyPrinterTurbo（一站式 AI 短视频生成工具）
> 分析环境：Windows 10 / Dell Inspiron 5680 / i7 Coffee Lake 6 核 / 32GB 内存 / GTX 1070 8GB（驱动 457.51）

---

## 目录

1. [工程架构与视频制作流水线](#一工程架构与视频制作流水线)
2. [外部 API/服务依赖总表](#二外部-apiservice-依赖汇总)
3. [本机最少云 API Key 需求（免费方案）](#三本机最少云-api-key-需求免费方案)
4. [本机硬件评估：能否部署 Qwen2.5](#四本机硬件评估能否部署-qwen25)
5. [用 GLM 作为 LLM 驱动工程的方案](#五用-glm-作为-llm-驱动工程的方案)
6. [推荐配置速查](#六推荐配置速查)

---

## 一、工程架构与视频制作流水线

### 1.1 整体架构（三个入口，共享一条流水线）

| 入口 | 文件 | 说明 |
|---|---|---|
| **REST API** | `main.py` → `app/asgi.py` → `app/controllers/v1/video.py` | FastAPI + Uvicorn，提供 `/videos`、`/audio`、`/subtitle`、`/tasks` 等端点 |
| **WebUI** | `webui/Main.py` | Streamlit 图形界面，内部调用与 API 相同的服务层 |
| **CLI** | `cli.py` | 命令行批处理 |

三条路径最终都汇聚到 `app/services/task.py` 的 `_run_pipeline()`，任务状态由
`app/services/state.py` 管理（内存或 Redis），支持按 `stop_at` 在任意阶段截断
（script / terms / audio / subtitle / materials / video）。

### 1.2 六步流水线

#### ① 生成脚本文案（`llm.py::generate_script`，进度 5→10%）
- 内置 System Prompt（要求按段落数输出纯文本口播稿）+ 主题/语言/段落数拼装 prompt，调用 LLM 生成。
- 失败自动重试最多 5 次，自动清洗 markdown、括号等噪音。
- 若任务参数中**已提供现成文案（`video_script` 非空），则完全跳过 LLM**（见 `task.py::generate_script`）。

#### ② 生成素材搜索关键词（`llm.py::generate_terms`，→20%）
- 再发一次 LLM 请求，让模型按脚本顺序提炼 N 个视频搜索词（`videoTerms`）。
- JSON 解析带代码围栏剥离（`_strip_code_fence`）和正则兜底；会剥离 `<think>` 推理块。
- 可选用 TwelveLabs API（`twelvelabs.py`）对关键词做语义 embedding 重排序（可选）。

#### ③ 语音配音 TTS（`voice.py`，→30%）
- 按声音名称前缀路由到约 **11 种 TTS 引擎**：
  - 云端：**Edge TTS（微软免费）**、Azure TTS v1/v2、SiliconFlow、Gemini、小米 MiMo、MiniMax、ElevenLabs、Fish Audio
  - 本地：**Chatterbox、Kokoro、VoxCPM**（支持上传参考音频做声音克隆）
- 支持脚本内 `[pause]` 停顿标签分段合成，FFmpeg/pydub 拼接调音量。
- 返回音频文件、时长和 `SubMaker` 时间戳对象。
- **默认声音 `zh-CN-XiaoxiaoNeural-Female` 走 Edge TTS，完全免费无需 Key。**

#### ④ 生成字幕（`subtitle.py`，→40%）
- 两种方式：
  1. TTS 时间戳直出（默认 `subtitle_provider = "edge"`，无需 Key）；
  2. **本地 faster-whisper**（默认 `large-v3`，VAD 过滤 + 词级时间戳）离线转录，并用编辑距离算法对照原脚本纠错。
- Whisper 模型文件需下载到 `models/whisper-{model_size}`。

#### ⑤ 获取视频素材（`material.py::get_video_materials`，→50%）
按 `video_source` 分流：
- **图库检索**（免费 Key）：Pexels / Pixabay / Coverr，或 `local` 本地素材
- **AI 生成全新视频**（按次付费）：WaveSpeed AI、火山引擎 Ark Seedance、OFox、Metaso MiniMax、MuAPI、LoomLoom
- **OpenAI 图片生成**：调 OpenAI 兼容 `/images/generations` 出图，渲染成 Ken Burns 缩放片段

工程要点：多 Key 轮换、线程池并发搜索下载、按宽高比过滤、检索结果缓存、按音频时长累计选取素材。

#### ⑥ 合成成片（`video.py::combine_videos` + `generate_video`，→100%）
纯本地处理，基于 **MoviePy 2.x + FFmpeg**：
- 素材按 `max_clip_duration` 切片（顺序/随机拼接），缩放变速适配 9:16 / 16:9 / 方形画布（cover 裁剪或 contain 模糊背景）
- 片段转场效果（`video_effects.py`）；FFmpeg concat 拼接（libx264/nvenc 编解码探测与降级回退）
- 字幕渲染：字体校验（防路径穿越）、描边、圆角背景、弹簧缩放动画
- 混入旁白 + BGM（内置歌曲 `resource/songs/`、用户上传，或 AI 配乐 Sonilo / ElevenLabs Music——BGM 失败自动降级为纯旁白并记录警告）

#### ⑦ 跨平台发布（可选）
通过 upload-post.com 异步发布到 TikTok / Instagram Reels / Facebook Reels / YouTube，带状态机与进程崩溃恢复。本机使用可完全忽略。

---

## 二、外部 API/Service 依赖汇总

| 类别 | 服务 | 是否免费 |
|---|---|---|
| **LLM（脚本/关键词）** | OpenAI 兼容端点、Azure OpenAI、Gemini、通义千问 DashScope、Cloudflare AI Gateway、ModelScope、LiteLLM、Claude CLI（订阅）、Kimi Code（OAuth）、LoomLoom | ModelScope/OpenRouter/Groq 有免费额度；Ollama 本地零成本 |
| **视频素材检索** | Pexels API、Pixabay API、Coverr API | ✅ Key 注册免费 |
| **AI 视频生成** | WaveSpeed AI、火山引擎 Ark（Seedance）、OFox、Metaso MiniMax、MuAPI、LoomLoom | ❌ 按次付费 |
| **AI 图片生成** | 任意 OpenAI 兼容 `/images/generations` | 视端点而定 |
| **TTS 配音** | Edge TTS、Azure、SiliconFlow、Gemini、MiMo、MiniMax、ElevenLabs、Fish Audio；本地：Chatterbox / Kokoro / VoxCPM | ✅ Edge TTS 完全免费；本地模型免费 |
| **字幕** | 本地 faster-whisper（无需 API） | ✅ 免费（需下载模型） |
| **关键词重排（可选）** | TwelveLabs | 付费 |
| **AI 配乐（可选）** | Sonilo、ElevenLabs Music | 付费 |
| **自动发布（可选）** | upload-post.com（TikTok/IG/FB/YouTube） | 付费 |
| **本地基础组件** | FFmpeg、MoviePy、pydub、Redis（可选） | ✅ 免费 |

**总结**：项目本质是「AI 编排器」——LLM 负责文字创意，第三方 API 或本地模型生产视听素材，最后本地用 FFmpeg/MoviePy 做时间线合成。

---

## 三、本机最少云 API Key 需求（免费方案）

### 结论

> **严格最少只需要 1 个 Key —— Pexels（免费注册）。**
> 甚至存在 **0 Key** 的极端用法（见下方档位表）。

### 各环节免费依据

| 环节 | 默认实现 | Key 需求 | 免费方案 |
|---|---|---|---|
| ① 脚本文案 | `llm.py` 调 LLM | 视 Provider | Ollama 本地 / 免费额度 Key / 自带文案跳过 |
| ② 搜索关键词 | 同上 | 同上 | 同上（`video_source="local"` 时可跳过） |
| ③ TTS 配音 | **Edge TTS**（默认声音） | ✅ 无需 Key | 默认即可 |
| ④ 字幕 | `subtitle_provider = "edge"` | ✅ 无需 Key | 默认即可；本地 Whisper 也免费 |
| ⑤ 视频素材 | `video_source = "pexels"` | ❗ 需 Pexels Key | Pexels/Pixabay/Coverr Key 注册免费；或 `local` 本地素材 |
| ⑥ BGM | `bgm_type = "random"`（本地歌曲） | ✅ 无需 Key | 默认即可 |
| ⑦ 合成渲染 | 本地 MoviePy + FFmpeg | ✅ 无需 Key | 仅需本机装 FFmpeg |

关键代码依据：
- `config.example.toml:480` — `subtitle_provider = "edge"`（默认，无需 Whisper）
- `app/models/schema.py:169` — `voice_name` 默认 `zh-CN-XiaoxiaoNeural-Female`（Edge 免费语音）
- `app/models/schema.py:118/172` — `video_source` 默认 `"pexels"`，`bgm_type` 默认 `"random"`
- `task.py::generate_script` — `params.video_script` 非空则跳过 LLM
- `task.py::_run_pipeline` — preflight 阶段强制检查 `utils.check_ffmpeg_ready()`，FFmpeg 不可用直接任务失败

### 三种典型档位

**🥇 极简档（1 个免费 Key）——推荐入门**

```
Pexels Key（免费注册）+ Edge TTS + edge 字幕 + 内置 BGM + 任意免费 LLM
```

**🥈 零云端档（0 个 Key）**

- `video_source = "local"` + 自备视频素材
- 自带文案（`video_script`）或本机 Ollama
- Edge TTS + edge 字幕 + 内置 BGM
- 全流程无外部 API 调用，但少了"AI 生成文案 + 自动配素材"的体验

**🥉 零 Key 全 AI 生成**

- 本机 Ollama（文案/关键词）+ Edge TTS + 本地 Whisper 字幕 + 本地素材
- 0 Key，素材需自己准备

**唯一"硬性"非 API 依赖：FFmpeg 必须本机可用**（或通过 `config.toml` 的 `app.ffmpeg_path` 指定）。

---

## 四、本机硬件评估：能否部署 Qwen2.5

### 本机实测配置

| 项目 | 配置 | 对本地推理的影响 |
|---|---|---|
| CPU | Intel Coffee Lake（6 核，~3.2GHz） | 纯 CPU 推理可用但偏慢 |
| 内存 | 32 GB | 充裕，14B 级 CPU 卸载无压力 |
| GPU | **GTX 1070 8GB**（Pascal，CUDA 算力 6.1） | 7B 量化模型可基本驻留显存 |
| 驱动 | 457.51（2020 年，CUDA 11.1） | ⚠️ 偏旧，见注意事项 |

### 模型档位评估（Ollama，Q4_K_M 量化）

| 模型 | 体积 | 可行性 | 预期体验 |
|---|---|---|---|
| qwen2.5:**7b** | ~4.7 GB | ✅ **推荐**，整体放入 8GB 显存 | 约 15–25 token/s，一份口播稿十几秒 |
| qwen2.5:**14b** | ~9 GB | ⚠️ GPU+CPU 混合卸载可行 | 约 5–10 token/s，可接受 |
| qwen2.5:32b/72b | 19 GB+ | ❌ 不实用 | 每秒个位数 token |
| 0.5b/1.5b/3b | <3 GB | ✅ 飞快 | 中文文案质量偏弱，不建议 |

**结论：可以部署。** 工程对 LLM 要求很低——每次任务只需 2 次短文本调用（几百 token 的口播稿 + 一个 JSON 关键词列表），无长上下文。**`qwen2.5:7b` 是本机甜点位。**

字幕默认走 Edge TTS 时间戳（`subtitle_provider = "edge"`），不会额外占显存跑 Whisper。

### 注意事项

1. **驱动偏旧**：Ollama 自带 CUDA v11 运行库要求驱动 ≥ 456.71，457.51 刚好达标，大概率能识别 GPU。启动后用 `ollama ps` 确认是否显示 `100% GPU`；若纯 CPU，升级 GeForce 驱动即可（GTX 1070 仍在支持列表）。
2. **当前可用内存只有约 5.5 GB**：合成视频/Whisper 阶段内存开销大，生成视频时最好关掉占内存的程序。

### 配置方法（`config.toml` → `[app]`）

```toml
llm_provider = "ollama"          # 注册表里 requires_api_key=False，无需任何 Key
ollama_model_name = "qwen2.5:7b"
```

WebUI 中直接在下拉框选 Ollama，会自动推断本机 `http://localhost:11434`。

---

## 五、用 GLM 作为 LLM 驱动工程的方案

**可以，代码已为 GLM 铺好三条路**（`app/models/llm_provider.py` 注册表 + `llm.py::_generate_response` 的 OpenAI 兼容兜底路径）。

### 路线 1：ModelScope Provider（最省事，还免费）⭐推荐

注册表里 ModelScope 的**默认模型就是 `ZhipuAI/GLM-5.2`**，端点
`https://api-inference.modelscope.cn/v1/`，标准 OpenAI 兼容流式协议。
ModelScope 注册即送每日免费推理额度。

```toml
llm_provider = "modelscope"
modelscope_api_key = "ms-xxxx"    # ModelScope 控制台申请，免费
# 默认模型即为 ZhipuAI/GLM-5.2，无需再配
```

### 路线 2：OpenRouter 免费档（零成本）

WebUI 内置提示（`webui/i18n/zh.json`）明确推荐 **`z-ai/glm-5.2:free`**：

```toml
llm_provider = "openrouter"
openrouter_api_key = "sk-or-..."
openrouter_model_name = "z-ai/glm-5.2:free"
```

### 路线 3：智谱官方 API（OpenAI 兼容端点直连）

代码无专门 "zhipu" Provider，但 `_generate_response` 对无特殊 adapter 的
Provider 一律走标准 `OpenAI(api_key, base_url).chat.completions.create`
（`llm.py` 末尾兜底分支），智谱 `https://open.bigmodel.cn/api/paas/v4`
正是 OpenAI 兼容协议。选任意 OpenAI 兼容 Provider 覆盖地址即可：

```toml
llm_provider = "openai"
openai_api_key = "智谱API Key"
openai_base_url = "https://open.bigmodel.cn/api/paas/v4"
openai_model_name = "glm-4.7"   # 或 glm-5.2 等已开通的模型
```

### 兼容性细节（已确认）

- `llm.py` 已处理 GLM 类模型的输出习惯：剥离 ```` ```json ```` 代码围栏、
  剥离 `<think>` 推理块、清洗 markdown 符号——关键词 JSON 和文案都能正常解析。
- 失败自动重试 5 次；额度耗尽等错误文本会被识别并触发重试。
- 生成脚本/关键词是短任务，GLM 全系（含免费档）均绰绰有余，一次任务只调 2 次 LLM。

---

## 六、推荐配置速查

### 方案对比

| 方案 | 成本 | 质量 | 适合 |
|---|---|---|---|
| 本机 Ollama + `qwen2.5:7b` | 0 元，纯离线 | 中文文案中等偏上 | 隐私/离线/不限量重试 |
| ModelScope + `ZhipuAI/GLM-5.2` | 免费额度 | 高 | **日常使用最佳平衡** |
| OpenRouter `z-ai/glm-5.2:free` | 0 元（限速） | 高 | 不想申请 ModelScope 时 |

### 建议的最终组合（1 个免费 Key 即可跑通全流程）

```toml
# config.toml → [app]

# ── LLM：日常用 GLM（ModelScope 免费额度），离线兜底用本地 Ollama ──
llm_provider = "modelscope"
modelscope_api_key = "ms-xxxx"
# 断网/额度耗尽时切换：
# llm_provider = "ollama"
# ollama_model_name = "qwen2.5:7b"

# ── 素材：Pexels 免费图库 ──
video_source = "pexels"
pexels_api_keys = ["免费注册获取"]

# ── 以下全部保持默认，零 Key 零成本 ──
# 配音：voice_name = "zh-CN-XiaoxiaoNeural-Female"（Edge TTS）
# 字幕：subtitle_provider = "edge"
# BGM：bgm_type = "random"（内置歌曲）

# ── 避免误触付费服务 ──
# wavespeed_api_keys / volcengine_seedance_api_key / ofox_api_key 等全部留空
```

### 使用前检查清单

- [ ] FFmpeg 已安装且在 PATH（或配置 `app.ffmpeg_path`）
- [ ] `config.example.toml` 复制为 `config.toml` 并填入 Key
- [ ] （可选）Ollama 已拉取 `qwen2.5:7b`，`ollama ps` 确认 GPU 生效
- [ ] （可选，本地 Whisper 字幕时）下载 whisper 模型到 `models/whisper-large-v3`
- [ ] 生成视频前关闭占内存程序（当前常用内存偏高）
