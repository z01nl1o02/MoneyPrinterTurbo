"""MoviePy 合成层（Stage B/C）：场景组装、字幕挂载、BGM 混音、母版、切片。

用法（批次 build.py）：
    scenes = pipeline.tts.synth(batch, SCENES)
    layers = {1: [...], 2: [...]}   # 用 video()/chain()/zoom_image()/place() 构建
    raw = pipeline.compose.render(batch, scenes, layers)
    pipeline.compose.master(raw, batch/"output"/"成片.mp4")
"""
import os
from pathlib import Path

import numpy as np
from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                     ImageClip, VideoFileClip, concatenate_videoclips)
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, MultiplyVolume
from PIL import Image

from . import config, prepare, textfx


# ---------------------------------------------------------------- 片段构建
def video(path, dur=None, start=0.0):
    c = VideoFileClip(str(path))
    if dur is not None:
        c = c.with_duration(dur)
    return c.with_start(start)


def chain(paths, dur, start=0.0):
    """多个已预处理片段顺序拼接并限定总时长。"""
    c = concatenate_videoclips([VideoFileClip(str(p)) for p in paths], method="chain")
    return c.with_duration(dur).with_start(start)


def zoom_image(png, dur, k=0.07, start=0.0):
    """整幅定格图 Ken Burns 推近（图须已处理为 W×H）。"""
    ic = ImageClip(str(png)).with_duration(dur)
    w0, h0 = ic.size
    s = lambda t: 1.0 + k * (t / dur)
    return (ic.resized(s)
            .with_position(lambda t: ((config.W - w0 * s(t)) / 2,
                                      (config.H - h0 * s(t)) / 2))
            .with_start(start))


def place(clip, x, y, start, dur, popin=True):
    """PIL 图/路径 → 定位叠层；popin 弹入（围绕中心 1.32→1.0，0.22s）。"""
    if isinstance(clip, Image.Image):
        clip = np.asarray(clip)
    c = ImageClip(clip).with_duration(dur)
    w0, h0 = c.size
    cx = max(0, min(config.W - w0, x)) if w0 <= config.W else (config.W - w0) // 2
    if popin:
        s = lambda t: 1.0 + 0.32 * max(0.0, 1.0 - t / 0.22)
        return (c.resized(s)
                .with_position(lambda t: (cx - (w0 * s(t) - w0) / 2,
                                          y - (h0 * s(t) - h0) / 2))
                .with_start(start))
    return c.with_position((cx, y)).with_start(start)


# ---------------------------------------------------------------- 合成
def pick_bgm() -> Path:
    """内置曲库按 RMS 择优（取 30~38s 切片比较能量）。"""
    import pydub
    best, best_rms = None, -1
    for fn in sorted(os.listdir(config.SONGS_DIR)):
        if not fn.endswith(".mp3"):
            continue
        seg = pydub.AudioSegment.from_file(config.SONGS_DIR / fn)[30000:38000]
        if seg.rms > best_rms:
            best_rms, best = seg.rms, config.SONGS_DIR / fn
    print("BGM pick:", best.name, "rms:", best_rms)
    return best


def render(batch_dir, scenes: list, layers: dict, bgm=True, raw_name="day1_raw.mp4") -> Path:
    """逐场景组装（画面层 + 自动字幕层 + 配音）→ concat → 混 BGM → 写出。"""
    batch_dir = Path(batch_dir)
    ovl_dir = batch_dir / "work" / "overlays"
    total = sum(s["dur"] for s in scenes)
    print("scene durations:", [s["dur"] for s in scenes], "total:", round(total, 2))

    comps = []
    for sc in scenes:
        lv = list(layers[sc["id"]])
        for card in textfx.subtitle_overlays(sc, ovl_dir):
            lv.append(ImageClip(card["png"])
                      .with_start(card["start"]).with_duration(card["end"] - card["start"])
                      .with_position(((config.W - card["w"]) // 2, config.SUB_Y)))
        comp = CompositeVideoClip(lv, size=(config.W, config.H)).with_duration(sc["dur"])
        narr = AudioFileClip(sc["mp3"])
        narr = narr.with_start(sc["head"]).with_duration(
            min(narr.duration, sc["dur"] - sc["head"]))
        comps.append(comp.with_audio(narr))

    full = concatenate_videoclips(comps, method="chain")
    if bgm:
        bgm_clip = (AudioFileClip(str(pick_bgm()))
                    .subclipped(config.BGM_SKIP, config.BGM_SKIP + total + 0.5)
                    .with_effects([MultiplyVolume(config.BGM_VOLUME),
                                   AudioFadeIn(config.BGM_FADEIN),
                                   AudioFadeOut(config.BGM_FADEOUT)]))
        full = full.with_audio(CompositeAudioClip([full.audio, bgm_clip]))

    out_dir = batch_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / raw_name
    full.write_videofile(str(raw), fps=config.FPS, codec="libx264",
                         preset=config.PRESET, audio_codec="aac",
                         audio_bitrate="192k",
                         ffmpeg_params=["-crf", str(config.CRF_FINAL)], threads=4)
    for c in comps:
        c.close()
    return raw


def master(raw, out) -> Path:
    """母版：loudnorm -14LUHS（视频流直拷，仅重编音频）。"""
    prepare.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", config.LOUDNORM,
                 "-ar", "44100", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)])
    return Path(out)


def teaser(src, cuts: list, out, fade_out=0.8) -> Path:
    """从成片二次剪切引流切片：cuts=[(a,b),...] 段落 + 首尾淡入淡出 + loudnorm。"""
    src, out = str(src), str(out)
    total = sum(b - a for a, b in cuts)
    parts_v, parts_a = [], []
    for i, (a, b) in enumerate(cuts):
        parts_v.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}]")
        parts_a.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]")
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(cuts)))
    fc = (";".join(parts_v + parts_a) + ";" +
          f"{pairs}concat=n={len(cuts)}:v=1:a=1[vc][ac];"
          f"[vc]fade=t=in:d=0.3,fade=t=out:st={total - 0.6:.2f}:d=0.6[vf];"
          f"[ac]afade=t=out:st={total - fade_out:.2f}:d={fade_out},{config.LOUDNORM}[af]")
    prepare.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", fc,
                 "-map", "[vf]", "-map", "[af]", "-c:v", "libx264",
                 "-crf", config.CRF_FINAL, "-preset", config.PRESET,
                 "-c:a", "aac", "-b:a", "192k", out])
    return Path(out)
