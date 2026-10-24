"""分场景 TTS 配音（Edge TTS 免费路径）+ 词级时间戳缓存。

用法：
    scenes = pipeline.tts.synth(batch_dir, SCENES)
返回场景字典列表：{id, key, text, words:[(start,end,text)...], audio_dur, head, dur}
音频与词级 cues 缓存在 <batch>/work/tts/，已存在则跳过（force=True 重做）。
"""
import asyncio
import json

import edge_tts

from . import config, prepare


async def _synth_one(tts_dir, sc: dict, attempt: int = 3) -> None:
    import sys
    mp3 = tts_dir / f"scene{sc['id']}.mp3"
    js = tts_dir / f"scene{sc['id']}.json"
    for i in range(attempt):
        try:
            comm = edge_tts.Communicate(sc["text"], config.VOICE_NAME,
                                        rate=config.VOICE_RATE,
                                        boundary="WordBoundary")
            audio, words = b"", []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
                elif chunk["type"] == "WordBoundary":
                    words.append([round(chunk["offset"] / 1e7, 3),
                                  round((chunk["offset"] + chunk["duration"]) / 1e7, 3),
                                  chunk["text"]])
            if not audio:
                raise RuntimeError("empty audio")
            mp3.write_bytes(audio)
            js.write_text(json.dumps({"id": sc["id"], "key": sc["key"],
                                      "text": sc["text"], "words": words},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
            return
        except Exception as e:  # noqa: BLE001
            print(f"scene{sc['id']} attempt{i} failed: {e}")
            await asyncio.sleep(2)
    sys.exit(f"TTS failed for scene {sc['id']}")


def synth(batch_dir, scenes: list, force: bool = False) -> list:
    """合成/加载全部场景配音，并计算时间轴（dur = head + audio + tail）。"""
    from pathlib import Path
    tts_dir = Path(batch_dir) / "work" / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    need = [sc for sc in scenes
            if force or not (tts_dir / f"scene{sc['id']}.mp3").exists()
            or not (tts_dir / f"scene{sc['id']}.json").exists()]
    if need:
        for sc in need:
            asyncio.run(_synth_one(tts_dir, sc))

    result = []
    for sc in scenes:
        data = json.loads((tts_dir / f"scene{sc['id']}.json").read_text(encoding="utf-8"))
        mp3 = tts_dir / f"scene{sc['id']}.mp3"
        head = config.HEADS.get(sc["id"], 0.0)
        tail = config.TAILS.get(sc["id"], config.DEFAULT_TAIL)
        audio_dur = prepare.probe_duration(mp3)
        result.append({**data, "mp3": str(mp3), "audio_dur": audio_dur,
                       "head": head, "tail": tail,
                       "dur": round(head + audio_dur + tail, 3)})
    return result
