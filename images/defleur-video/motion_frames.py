#!/usr/bin/env python3
"""App-original helper (not part of James DeFleur's plugin).

base   - write James' capture input base_frames/<id>.jpg for a list of output frames:
         live ids are source frames cut to their setup's fixed crop (crop-ledger.json)
         and scaled to the canvas; ids >= 10,000,000 are fullscreen insert media
         (image or MP4 clip, fit cover/contain) declared in the visual plan.
sheet  - contact sheet of captured frames (JPEG) with frame/time/mode labels.
check  - motion-mode picture checks: capture vs plain base frame (motion only inside
         planned beat/insert windows), exact final.mp4 vs capture (burned captions
         exactly where James' caption_layer.py draws a cue; clean where suppressed).
Evidence for review; not a perceptual judgement.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path

INSERT_BASE = 10_000_000
INSERT_STRIDE = 1_000_000


def src_input(path: Path) -> list[str]:
    return ["-protocol_whitelist", "file", "-format_whitelist", "mov", "-f", "mov", "-enable_drefs", "0",
            "-use_absolute_path", "0", "-threads", "2", "-i", str(path)]


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-f", "mov", "-enable_drefs", "0",
                                   "-use_absolute_path", "0", "-select_streams", "v:0",
                                   "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)], text=True)
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def crop_at(ledger: dict, t: float) -> list[int]:
    ranges = ledger["ranges"]
    for row in ranges:
        if row["start"] <= t < row["end"]:
            return row["crop"]
    return ranges[-1]["crop"] if t >= ranges[-1]["end"] else ranges[0]["crop"]


def fit(img, cw, ch, mode):
    from PIL import Image
    w, h = img.size
    if mode == "contain":
        f = min(cw / w, ch / h)
        out = Image.new("RGB", (cw, ch), (0, 0, 0))
        r = img.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
        out.paste(r, ((cw - r.size[0]) // 2, (ch - r.size[1]) // 2))
        return out
    f = max(cw / w, ch / h)
    r = img.resize((max(cw, round(w * f)), max(ch, round(h * f))), Image.LANCZOS)
    x, y = (r.size[0] - cw) // 2, (r.size[1] - ch) // 2
    return r.crop((x, y, x + cw, y + ch))


def base(a) -> None:
    import cv2
    import numpy as np
    from PIL import Image
    edit = json.loads(a.edit_map.read_text())
    ledger = json.loads(a.crop_ledger.read_text())
    ids = json.loads(a.base_map.read_text())
    cw, ch = ledger["canvas"]
    fps = Fraction(str(edit["fps"]))
    frames = json.loads(a.frames.read_text())
    out = a.project / "base_frames"
    out.mkdir(exist_ok=True)
    live, inserts = {}, {}
    for f in frames:
        b = ids["base_frames"][f]
        if b >= INSERT_BASE:
            inserts.setdefault((b - INSERT_BASE) // INSERT_STRIDE, set()).add(b)
            live.setdefault(ids["source_frames"][f], f)  # the live frame an insert replaces: reference for the pixel check
        else:
            live.setdefault(b, f)
    W, H = probe_size(a.source)
    size = W * H * 3
    written = 0
    if live:
        want = sorted(live)
        cmd = ["ffmpeg", "-v", "error", "-nostdin", *src_input(a.source), "-map", "0:v:0", "-fps_mode", "passthrough",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
        cur, current = -1, None
        with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
            assert p.stdout is not None
            for sf in want:
                while cur < sf:
                    data = p.stdout.read(size)
                    if len(data) != size:
                        break
                    current, cur = data, cur + 1
                if current is None:
                    raise SystemExit("source produced no frames")
                x, y, w, h = crop_at(ledger, live[sf] / float(fps))
                img = np.frombuffer(current, np.uint8).reshape(H, W, 3)[y:y + h, x:x + w]
                img = cv2.resize(img, (cw, ch), interpolation=cv2.INTER_LANCZOS4)
                ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not ok:
                    raise SystemExit("jpeg encode failed")
                (out / f"{sf:06d}.jpg").write_bytes(jpg.tobytes())
                written += 1
            p.stdout.close()
            p.kill()
    for k, wanted in inserts.items():
        win = ids["inserts"][k]
        asset = a.motion_src / win["asset"]
        if win["still"]:
            with Image.open(asset) as im:
                fit(im.convert("RGB"), cw, ch, win["fit"]).save(out / f"{INSERT_BASE + k * INSERT_STRIDE:06d}.jpg", quality=95)
            written += 1
            continue
        need = max(b - INSERT_BASE - k * INSERT_STRIDE for b in wanted) + 1
        aw, ah = probe_size(asset)
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{win['clip_start_s']:.3f}", *src_input(asset), "-map", "0:v:0",
               "-vf", f"fps={edit['fps']}", "-frames:v", str(need), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        raw = subprocess.run(cmd, check=True, capture_output=True).stdout
        n = len(raw) // (aw * ah * 3)
        if n == 0:
            raise SystemExit(f"insert {win['asset']} decoded no frames")
        for b in sorted(wanted):
            i = min(b - INSERT_BASE - k * INSERT_STRIDE, n - 1)   # hold the last frame if the clip is shorter
            im = Image.frombytes("RGB", (aw, ah), raw[i * aw * ah * 3:(i + 1) * aw * ah * 3])
            fit(im, cw, ch, win["fit"]).save(out / f"{b:06d}.jpg", quality=95)
            written += 1
    print(json.dumps({"base_frames": written, "live": len(live), "insert_windows": len(inserts)}))


def sheet(a) -> None:
    from PIL import Image, ImageDraw, ImageFont
    cap = json.loads(a.capture.read_text())
    geo = {g["frame"]: g for g in cap.get("geometry", [])}
    fps = Fraction(str(cap["fps"]))
    picks = cap["indices"]
    if len(picks) > a.max:
        picks = [picks[round(i * (len(picks) - 1) / (a.max - 1))] for i in range(a.max)]
    cols = 4
    tw, th = 270, 480
    rows = (len(picks) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tw, rows * (th + 28)), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(a.font, 16)
    for i, f in enumerate(picks):
        with Image.open(a.frames_dir / f"{f:06d}.jpg") as im:
            canvas.paste(im.convert("RGB").resize((tw, th)), ((i % cols) * tw, (i // cols) * (th + 28)))
        g = geo.get(f, {})
        label = f"#{f} {float(f / fps):.2f}s {g.get('mode') or ''}{' nocap' if g.get('captionSuppressed') else ''}"
        draw.text(((i % cols) * tw + 4, (i // cols) * (th + 28) + th + 4), label, fill=(240, 240, 240), font=font)
    canvas.save(a.out, quality=88)
    print(json.dumps({"sheet_frames": len(picks)}))


def check(a) -> None:
    """Motion-mode picture checks on the exact final.mp4 (live-only renders use final_render.py check)."""
    import sys
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(a.caption_dir))
    from caption_layer import _chunks, caption_engine  # James' adapter decides when a cue is drawn (honours suppression)
    root = a.project
    ids = json.loads(a.base_map.read_text())
    plan = json.loads((root / "visual-plan.json").read_text())
    style = json.loads((root / "caption-style.json").read_text())
    timeline = json.loads((root / "locked-timeline.json").read_text())
    fps = Fraction(str(timeline["fps"]))
    frames, (W, H) = timeline["frames"], timeline["canvas"]
    left, top, right, bottom = style["safe_rect"]
    btop, bbot = max(0, top - 24), min(H, bottom + 24)
    beats, inserts, sup = plan["beats"], plan.get("inserts", []), plan.get("caption_suppress", [])
    tf = lambda f: f / float(fps)
    inside = lambda t, rows: any(r["start"] <= t < r["end"] for r in rows)
    draw = caption_engine(root)
    blank = Image.new("RGB", (W, H))
    cue = lambda f: draw(blank, tf(f)).getbbox() is not None
    spoken = lambda f: any(w["start"] <= tf(f) < w["end"] + 0.25 for w in timeline["words"])
    pick = lambda xs, n: [xs[round(i * (len(xs) - 1) / max(1, n - 1))] for i in range(min(n, len(xs)))] if xs else []
    live = [f for f in range(frames) if not inside(tf(f), beats) and not inside(tf(f), inserts)]
    sample = {}
    for f in pick(live, 12):
        sample[f] = "live"
    def window(rows, label, n):
        for k, r in enumerate(rows):
            a0, a1 = int(r["start"] * float(fps)) + 1, min(frames - 1, int(r["end"] * float(fps)) - 1)
            for f in pick(list(range(a0, a1 + 1)), n):
                sample.setdefault(f, f"{label}-{k}")
    window(beats, "beat", 8)
    window(inserts, "insert", 4)
    window(sup, "suppress", 4)
    order = sorted(sample)
    expr = "+".join(f"eq(n\\,{i})" for i in order)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "2", "-i", str(a.final), "-map", "0:v:0",
                          "-vf", f"select='{expr}'", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                         check=True, capture_output=True).stdout
    if len(raw) != W * H * 3 * len(order):
        raise SystemExit("could not decode the sampled final frames")
    def load(path):
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB")).astype(np.int16)
    out_band = lambda img: np.concatenate([img[:btop].reshape(-1, 3), img[bbot:].reshape(-1, 3)])
    band = lambda img: img[top:bottom, left:right]
    mad = lambda x, y: round(float(np.mean(np.abs(x - y))), 2)
    chg = lambda x, y: round(float(np.mean(np.abs(x - y).max(axis=-1) > 40)), 5)  # fraction of clearly changed pixels
    rows = []
    for i, f in enumerate(order):
        fin = np.frombuffer(raw[i * W * H * 3:(i + 1) * W * H * 3], np.uint8).reshape(H, W, 3).astype(np.int16)
        cap = load(a.picture_dir / f"{f:06d}.jpg")
        b = ids["base_frames"][f]
        base = load(a.base_dir / f"{b:06d}.jpg")
        t = tf(f)
        row = {"frame": f, "t": round(t, 3), "window": sample[f], "base_frame": b, "cue_on": cue(f),
               "in_beat": inside(t, beats), "in_insert": inside(t, inserts), "suppressed": inside(t, sup), "words_spoken": spoken(f),
               "capture_vs_base_outside_band": mad(out_band(cap), out_band(base)),
               "changed_fraction_vs_base": chg(out_band(cap), out_band(base)),
               "final_vs_capture_outside_band": mad(out_band(fin), out_band(cap)),
               "caption_band_final_vs_capture": mad(band(fin), band(cap))}
        if row["in_insert"]:
            lp = a.base_dir / f"{timeline_source(ids, f):06d}.jpg"
            if lp.is_file():
                row["changed_fraction_vs_live_source"] = chg(out_band(cap), out_band(load(lp)))
        rows.append(row)
    live_rows = [r for r in rows if not r["in_beat"] and not r["in_insert"]]
    live_max = max([r["changed_fraction_vs_base"] for r in live_rows], default=0.0)
    beats_ok = {f"beat-{k}": max([r["changed_fraction_vs_base"] for r in rows if r["window"] == f"beat-{k}"], default=0.0) >= a.motion_threshold
                for k in range(len(beats))}
    ins_ok = {}
    for k in range(len(inserts)):
        rr = [r for r in rows if r["window"] == f"insert-{k}"]
        ins_ok[f"insert-{k}"] = bool(rr) and all(r.get("changed_fraction_vs_live_source", 0) >= 0.05 and r["changed_fraction_vs_base"] < a.live_threshold for r in rr)
    on = [r["caption_band_final_vs_capture"] for r in rows if r["cue_on"]]
    off = [r["caption_band_final_vs_capture"] for r in rows if not r["cue_on"]]
    sup_rows = [r for r in rows if r["suppressed"]]
    captions_ok = bool(on) and min(on) >= 4.0 and (not off or max(off) < min(on) / 2)
    suppressed_ok = all(not r["cue_on"] and r["caption_band_final_vs_capture"] < 2.0 for r in sup_rows)
    encode_ok = max(r["final_vs_capture_outside_band"] for r in rows) < 6.0
    cues = len(_chunks(timeline["words"], int(style["max_words"]), int(style["max_chars"])))
    result = {"frames": frames, "samples": rows, "caption_cues": cues, "cue_on_frames": sum(1 for f in range(frames) if cue(f)),
              "live_max_capture_vs_base": live_max, "live_threshold": a.live_threshold, "motion_threshold": a.motion_threshold,
              "no_motion_outside_planned_windows": live_max < a.live_threshold, "crop_matches_ledger": live_max < a.live_threshold,
              "beats_show_motion": beats_ok, "inserts_show_media": ins_ok,
              "caption_band_changes_with_cues": captions_ok, "captions_suppressed_where_declared": suppressed_ok,
              "suppressed_samples_with_speech": sum(1 for r in sup_rows if r["words_spoken"]),
              "encode_matches_capture": encode_ok,
              "pass": live_max < a.live_threshold and all(beats_ok.values()) and all(ins_ok.values()) and captions_ok and suppressed_ok and encode_ok,
              "method": ("Sampled frames: capture.cjs output vs the plain live base frame it fed to #live (outside the caption band, "
                         "mean absolute RGB difference): live windows must match, each beat must change pixels, each insert must differ "
                         "from the live frame it replaced. Exact final.mp4 decoded by FFmpeg vs the capture: caption band changes exactly "
                         "where James' caption_layer.py draws a cue, stays clean in declared suppression ranges, and the rest matches.")}
    a.out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("pass", "no_motion_outside_planned_windows", "caption_band_changes_with_cues",
                                             "captions_suppressed_where_declared", "live_max_capture_vs_base")}))


def timeline_source(ids: dict, f: int) -> int:
    return ids["source_frames"][f]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("base")
    for n in ("source", "edit_map", "crop_ledger", "base_map", "frames", "project", "motion_src"):
        b.add_argument(n, type=Path)
    s = sub.add_parser("sheet")
    for n in ("capture", "frames_dir", "out"):
        s.add_argument(n, type=Path)
    s.add_argument("--max", type=int, default=24)
    s.add_argument("--font", default="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    c = sub.add_parser("check")
    for n in ("final", "base_map", "project", "base_dir", "picture_dir", "out"):
        c.add_argument(n, type=Path)
    c.add_argument("--caption-dir", type=Path, required=True)
    c.add_argument("--live-threshold", type=float, default=0.002, help="max changed-pixel fraction outside planned windows")
    c.add_argument("--motion-threshold", type=float, default=0.003, help="min changed-pixel fraction somewhere in each beat")
    a = ap.parse_args()
    {"base": base, "sheet": sheet, "check": check}[a.cmd](a)


if __name__ == "__main__":
    main()
