"""全局配置：路径、画布、TTS、字幕样式、BGM、编码参数。

所有可调参数集中在此，改样式/语速/尺寸只需动这个文件。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SONGS_DIR = ROOT / "resource" / "songs"
FONTS_DIR = ROOT / "resource" / "fonts"

# 画布与帧率（抖音竖屏）
W, H, FPS = 1080, 1920, 30

# TTS（Edge TTS 免费，无需 Key；词级时间戳必须显式 boundary="WordBoundary"）
VOICE_NAME = "zh-CN-YunxiNeural"
VOICE_RATE = "+18%"  # 实测约 5 字/秒

# 场景垫片（秒）：head 为配音前留白，tail 为配音后画面停留
DEFAULT_TAIL = 0.18
HEADS = {1: 0.10}
TAILS = {1: 0.32, 7: 0.90}  # 未列出的场景用 DEFAULT_TAIL

# 字体（resource/fonts 随仓库携带，跨机器可用；ttc 需 index=0）
FONT_BOLD = FONTS_DIR / "MicrosoftYaHeiBold.ttc"
FONT_REG = FONTS_DIR / "MicrosoftYaHeiNormal.ttc"

# 大字幕样式
SUB_FONT = 60
SUB_STROKE = 6
SUB_LINE_HEIGHT = 86
SUB_MAXW = 920          # 超过则拆两行
SUB_BREAK_PUNCT = "。！？，、：；"
SUB_MIN_BREAK = 6       # 标点断句最小字数
SUB_MAX_CHARS = 14      # 单卡硬上限
SUB_Y = 1180            # 字幕顶部 y 坐标

# 配色（RGBA）
WHITE = (255, 255, 255, 255)
BLACK = (24, 24, 28, 255)
BLACK_STROKE = (20, 20, 24, 255)
YELLOW = (255, 214, 10, 255)
RED = (255, 62, 62, 255)
CYAN = (85, 235, 255, 255)
DARK_TEXT = (10, 30, 40, 255)
RED_WORDS = {"背刺", "惨败", "绕后", "平局", "零蛋", "学坏", "筛子", "送后背"}  # 示例默认值，批次按文案覆盖

# BGM
BGM_VOLUME = 0.10
BGM_SKIP = 6            # 跳过前奏，从第 6 秒取
BGM_FADEIN = 0.8
BGM_FADEOUT = 1.5

# 编码
CRF_SEG = 18            # Stage A 中间片段
CRF_FINAL = 20          # 成片
PRESET = "veryfast"
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"  # 抖音响度标准
