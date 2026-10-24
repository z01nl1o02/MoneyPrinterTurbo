"""轻量竖屏成片流水线（源自 MoneyPrinterTurbo 实战精简）。

Edge TTS 免费配音 + 词级时间戳字幕 + 本地素材 ffmpeg 预处理 + MoviePy 合成。
模块：config（参数）/ tts（配音）/ prepare（素材）/ textfx（花字字幕）/ compose（合成）。
"""
from . import config, prepare, textfx, tts, compose  # noqa: F401
