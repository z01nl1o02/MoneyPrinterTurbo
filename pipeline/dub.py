"""补配音（dub）：已有视频 + SRT 字幕 → Edge TTS 配音成片。

独立于分镜流水线，不依赖批次 build.py，仅复用 config/prepare 的公共工具。

用法：
    .venv/Scripts/python.exe -m pipeline.dub <video> <srt> [options]

流程：
    1. 解析 SRT → 逐条文案
    2. 每条 Edge TTS 合成（按 文本hash 缓存，重跑不耗网络）
    3. 对齐字幕时窗：自然时长放得下就原速；放不下先溢入条间空隙，
       再不行提语速重合成（上限 --max-rate），仍不行 atempo 精确压入
    4. pydub 把各条语音铺到全片时长的静音轨上 → work/dub.wav
    5. ffmpeg 混音（原声降权/闪避/静音三选一）+ loudnorm → 视频流直拷

示例：
    .venv/Scripts/python.exe -m pipeline.dub videos/leap_second/闰秒科普动画.mp4 \
        videos/leap_second/闰秒科普动画.srt --bg-volume 0.2
"""
import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Windows 控制台安全打印（仍尽量只 print ASCII，文案一律进 UTF-8 文件）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from . import config  # noqa: E402
from .prepare import probe_duration, run  # noqa: E402

TS_RE = __import__("re").compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


# ---------------------------------------------------------------- SRT 解析
def parse_srt(path: Path) -> list:
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        sys.exit("cannot decode srt file (tried utf-8 / gb18030)")

    cues, lines, i = [], text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 0
    while i < len(lines):
        m = TS_RE.search(lines[i])
        if m:
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            body = []
            i += 1
            while i < len(lines) and lines[i].strip():
                body.append(lines[i].strip())
                i += 1
            t = " ".join(body)
            if t and end > start:
                cues.append({"id": len(cues) + 1, "start": start, "end": end, "text": t})
        i += 1
    if not cues:
        sys.exit("no cues found in srt")
    return cues


# ---------------------------------------------------------------- TTS 合成
async def _tts(text: str, out: Path, voice: str, rate: int, timeout: int = 90) -> None:
    """单条合成，带重试 + 整体超时（抗网络抖动，B 站批次 make_tts.py 模式）。"""
    rate_str = f"{rate:+d}%"
    for attempt in range(4):
        try:
            comm = __import__("edge_tts").Communicate(text, voice, rate=rate_str)
            audio = bytearray()

            async def collect():
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio.extend(chunk["data"])
            await asyncio.wait_for(collect(), timeout)
            if audio:
                out.write_bytes(bytes(audio))
                return
        except Exception as e:  # noqa: BLE001
            print(f"  tts attempt{attempt} failed: {type(e).__name__}: {e}")
            await asyncio.sleep(1.5 * (attempt + 1))
    sys.exit(f"tts failed after retries (voice={voice} rate={rate_str}); "
             f"rerun to reuse cached files")


def _cache_path(work: Path, cue: dict, rate: int, atempo: float | None = None) -> Path:
    h = hashlib.md5(cue["text"].encode("utf-8")).hexdigest()[:8]
    stem = f"c{cue['id']:03d}_{h}_r{rate}"
    return work / (f"{stem}_t{atempo:.3f}.wav" if atempo else f"{stem}.mp3")


def _synth_cached(work: Path, cue: dict, rate: int, voice: str, force: bool) -> Path:
    """按 (文本hash, rate) 缓存合成，存在即跳过。"""
    mp3 = _cache_path(work, cue, rate)
    if force or not mp3.exists():
        print(f"  tts cue{cue['id']:03d} rate={rate:+d}% ...")
        asyncio.run(_tts(cue["text"], mp3, voice, rate))
    return mp3


def _apply_atempo(src: Path, factor: float, work: Path, cue: dict, rate: int) -> Path:
    out = _cache_path(work, cue, rate, factor)
    if not out.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter:a",
             f"atempo={factor:.4f}", "-ar", "44100", str(out)])
    return out


# ---------------------------------------------------------------- 对齐时窗
def plan_cues(cues: list, video_dur: float, work: Path, voice: str,
              max_rate: int, force: bool) -> list:
    """逐条规划语音素材：返回 {file, start, rate, atempo, ...}，附报告。"""
    planned = []
    for idx, cue in enumerate(cues):
        slot = cue["end"] - cue["start"]
        nxt = cues[idx + 1]["start"] if idx + 1 < len(cues) else None
        # 允许的语音窗口：≥ 字幕时窗，可溢入条间空隙（留 0.08s 呼吸）；
        # 最后一条最多拖到片尾
        if nxt is not None:
            allowed = max(slot, nxt - cue["start"] - 0.08)
        else:
            allowed = max(slot, min(cue["end"] + 0.6, video_dur) - cue["start"])
        allowed = min(allowed, video_dur - cue["start"] - 0.05)
        allowed = max(allowed, 0.5)

        mp3 = _synth_cached(work, cue, 0, voice, force)
        dur = probe_duration(mp3)
        rate, atempo, note = 0, None, "natural"

        if dur > allowed + 0.02:  # 需要提速
            ratio = dur / allowed
            rate = min(max_rate, int((ratio - 1) * 100) + 6)
            if rate > 0:
                mp3 = _synth_cached(work, cue, rate, voice, force)
                dur = probe_duration(mp3)
                note = f"respeed {rate:+d}%"
            if dur > allowed + 0.02:  # 二次提档或 atempo 兜底
                rate2 = min(max_rate, int((dur / allowed - 1) * 100) + 6)
                if rate2 > rate:
                    rate = rate2
                    mp3 = _synth_cached(work, cue, rate, voice, force)
                    dur = probe_duration(mp3)
                    note = f"respeed {rate:+d}%"
                if dur > allowed + 0.02:
                    atempo = round(min(dur / allowed, 2.0), 4)
                    note += f" +atempo {atempo}"

        src = _apply_atempo(mp3, atempo, work, cue, rate) if atempo else mp3
        final_dur = probe_duration(src)
        if final_dur > allowed + 0.05:
            print(f"  WARN cue{cue['id']:03d}: voice {final_dur:.2f}s still over "
                  f"window {allowed:.2f}s (max_rate cap?)")
        planned.append({"id": cue["id"], "start": cue["start"], "slot": slot,
                        "allowed": round(allowed, 3), "voice_dur": round(final_dur, 3),
                        "rate": rate, "atempo": atempo, "file": str(src), "note": note,
                        "text": cue["text"]})
        print(f"  cue{cue['id']:03d} slot={slot:5.2f} voice={final_dur:5.2f} "
              f"({note})")
    return planned


# ---------------------------------------------------------------- 铺轨与混音
def build_track(planned: list, video_dur: float, out_wav: Path) -> None:
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence
    track = AudioSegment.silent(duration=int((video_dur + 0.2) * 1000), frame_rate=44100)
    for p in planned:
        seg = AudioSegment.from_file(p["file"])
        # Edge TTS 片段自带前导静音，裁掉让人声贴着字幕起点（最多前移 0.25s）
        lead_ms = detect_leading_silence(seg, silence_threshold=-42, chunk_size=10)
        shift = min(max(lead_ms - 20, 0), 250)
        p["lead_trim"] = round(shift / 1000, 3)
        track = track.overlay(seg, position=max(0, int(p["start"] * 1000) - shift))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    track.set_frame_rate(44100).export(out_wav, format="wav")
    print(f"track: {len(planned)} cues -> {out_wav.name} ({video_dur:.2f}s)")


def mux(video: Path, dub_wav: Path, out: Path, bg_volume: float,
        mute: bool, duck: bool, loudnorm: bool) -> None:
    """视频流直拷，只重编音频（秒级）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    if mute:
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-i", dub_wav]
        if loudnorm:
            cmd += ["-filter_complex", f"[1:a]{config.LOUDNORM}[aout]",
                    "-map", "0:v", "-map", "[aout]"]
        else:
            cmd += ["-map", "0:v", "-map", "1:a"]
    else:
        if duck:  # 原声按语音侧链闪避，语音出现时自动压低
            bg = (f"[1:a]asplit=2[sc][voice];[0:a][sc]"
                  f"sidechaincompress=threshold=0.03:ratio=6:attack=80:release=450[bg];"
                  f"[bg][voice]amix=inputs=2:duration=first:normalize=0")
        else:
            bg = (f"[0:a]volume={bg_volume}[bg];"
                  f"[bg][1:a]amix=inputs=2:duration=first:normalize=0")
        fc = bg + (f",{config.LOUDNORM}[aout]" if loudnorm else "[aout]")
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-i", dub_wav,
               "-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart", str(out)]
    run(cmd)
    print(f"muxed: {out.name}")


# ---------------------------------------------------------------- 入口
def main() -> None:
    ap = argparse.ArgumentParser(description="dub a video with TTS from its srt")
    ap.add_argument("video")
    ap.add_argument("srt")
    ap.add_argument("--out", help="输出成片（默认 <video>_dub.mp4）")
    ap.add_argument("--voice", default=config.VOICE_NAME)
    ap.add_argument("--rate", type=int, default=0,
                    help="整体基础语速 %%（如 10 表示 +10%%，默认 0 自然语速）")
    ap.add_argument("--max-rate", type=int, default=60,
                    help="自动提速上限 %%（默认 60）")
    ap.add_argument("--bg-volume", type=float, default=0.25,
                    help="原声音量（默认 0.25，配音当主体）")
    ap.add_argument("--mute", action="store_true", help="丢弃原声，只留配音")
    ap.add_argument("--duck", action="store_true", help="原声侧链闪避（代替固定音量）")
    ap.add_argument("--no-loudnorm", action="store_true", help="关闭 loudnorm")
    ap.add_argument("--force", action="store_true", help="无视缓存重做全部 TTS")
    ap.add_argument("--work", help="缓存目录（默认 <video目录>/work/dub/）")
    args = ap.parse_args()

    video = Path(args.video)
    srt = Path(args.srt)
    work = Path(args.work) if args.work else video.parent / "work" / "dub"
    work.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else video.with_stem(video.stem + "_dub").with_suffix(".mp4")

    video_dur = probe_duration(video)
    cues = parse_srt(srt)
    print(f"video {video_dur:.2f}s, {len(cues)} cues, work={work}")
    if cues[-1]["end"] > video_dur + 0.2:
        print(f"WARN last cue ends {cues[-1]['end']:.2f}s > video {video_dur:.2f}s")

    # 基础语速：把 0 视作 args.rate（缓存 key 含 rate，自动区分）
    base = args.rate
    planned = plan_cues(cues, video_dur, work, args.voice, args.max_rate, args.force)
    # 基础语速非 0 时整体再加一档：直接改用 rate=base 重新合成一遍不划算，
    # 简化处理：base>0 时按 base 合成初版，超窗再自动提档
    if base != 0:
        for p, cue in zip(planned, cues):
            if p["rate"] == 0:  # 自然语速放得下的条目改用基础语速
                mp3 = _synth_cached(work, cue, base, args.voice, args.force)
                dur = probe_duration(mp3)
                if dur <= p["allowed"] + 0.02:
                    p.update(file=str(mp3), voice_dur=round(dur, 3),
                             rate=base, note=f"base {base:+d}%")
                else:  # 放不下退回自然语速
                    p["file"] = str(_cache_path(work, cue, 0))
                    p["voice_dur"] = round(probe_duration(p["file"]), 3)

    dub_wav = work / "dub.wav"
    build_track(planned, video_dur, dub_wav)
    mux(video, dub_wav, out, args.bg_volume, args.mute, args.duck,
        not args.no_loudnorm)

    report = {"video": str(video), "srt": str(srt), "out": str(out),
              "video_dur": video_dur, "voice": args.voice,
              "bg": "mute" if args.mute else
                    ("duck" if args.duck else f"volume {args.bg_volume}"),
              "cues": planned}
    (work / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    n_respeed = sum(1 for p in planned if p["rate"] or p["atempo"])
    print(f"done -> {out.name}  (respeed/atempo cues: {n_respeed}/{len(planned)}); "
          f"report: {work / 'report.json'}")


if __name__ == "__main__":
    main()
