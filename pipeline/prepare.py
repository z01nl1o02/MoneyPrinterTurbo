"""ffmpeg 素材预处理（Stage A）：竖屏适配、慢放、定格帧。

两条竖屏路线：
- cover:     高能镜头，中心裁剪铺满 1080x1920
- letterbox: 宏观镜头，整幅居中 + 同帧放大模糊压暗当背景
"""
import os
import subprocess
import sys
from pathlib import Path

from . import config

BASE = ["ffmpeg", "-v", "error", "-y"]


def run(cmd: list) -> None:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit(f"ffmpeg failed: {' '.join(str(c) for c in cmd[:8])} ...")


def probe_duration(path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)]).decode().strip()
    return float(out)


def _cmd_in(src, out, ss=None, t=None):
    cmd = list(BASE)
    if ss is not None:
        cmd += ["-ss", f"{ss}"]
    if t is not None:
        cmd += ["-t", f"{t}"]
    return cmd + ["-i", str(src)]


def cover(src, out, ss=None, t=None, speed=1.0) -> Path:
    """高能镜头：中心裁剪铺满竖屏。speed<1 为慢放（60fps 素材可到 0.45）。"""
    out = Path(out)
    cmd = _cmd_in(src, out, ss, t) + [
        "-filter_complex",
        f"[0:v]setpts=PTS/{speed},crop=ih*9/16:ih,fps={config.FPS},"
        f"scale={config.W}:{config.H}:flags=lanczos,setsar=1[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-crf", config.CRF_SEG,
        "-preset", config.PRESET, str(out)]
    run(cmd)
    return out


def letterbox(src, out, ss=None, t=None, speed=1.0) -> Path:
    """宏观镜头：整幅画面居中，模糊放大背景铺满，上下留白放花字信息条。"""
    out = Path(out)
    cmd = _cmd_in(src, out, ss, t) + [
        "-filter_complex",
        f"[0:v]setpts=PTS/{speed},split[a][b];"
        f"[a]scale={config.W}:{config.H}:force_original_aspect_ratio=increase,"
        f"crop={config.W}:{config.H},boxblur=22:2,eq=brightness=-0.13,"
        f"eq=saturation=1.15[bg];"
        f"[b]scale={config.W}:-2:flags=lanczos[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={config.FPS},setsar=1[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-crf", config.CRF_SEG,
        "-preset", config.PRESET, str(out)]
    run(cmd)
    return out


def frame_png(src, out, ss=None, eof=False, letterboxed=False) -> Path:
    """抽取单帧。letterboxed=True 输出宏观路线竖版静帧，否则 cover 竖版。"""
    out = Path(out)
    tmp = out.with_name(out.stem + "_raw.png")
    cmd = list(BASE)
    if eof:
        cmd += ["-sseof", "-0.15"]
    elif ss is not None:
        cmd += ["-ss", f"{ss}"]
    run(cmd + ["-i", str(src), "-update", "1", "-frames:v", "1", str(tmp)])
    if letterboxed:
        vf = (f"split[a][b];[a]scale={config.W}:{config.H}:"
              f"force_original_aspect_ratio=increase,crop={config.W}:{config.H},"
              f"boxblur=22:2,eq=brightness=-0.13[bg];"
              f"[b]scale={config.W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        vf = f"crop=ih*9/16:ih,scale={config.W}:{config.H}:flags=lanczos"
    run(list(BASE) + ["-i", str(tmp), "-vf", vf, "-update", "1",
                      "-frames:v", "1", str(out)])
    os.remove(tmp)
    return out
