"""Bounded externally authored editing decisions; no model/runtime dependency.

Acoustic review follows the per-edge +/-0.8 second window contract in recovered
DeFleur speech_cut_audit.py. FFmpeg replaces its numpy/matplotlib renderer here;
we do not execute that CLI or pretend generated evidence is reviewed evidence.
"""
import math


class Rejected(ValueError):
    pass


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def timed_rows(rows, duration, text_key, maximum):
    if not isinstance(rows, list) or not 1 <= len(rows) <= maximum:
        raise Rejected("timed rows must be a bounded nonempty list")
    previous = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"start_s", "end_s", text_key}:
            raise Rejected("timed row has unknown or missing fields")
        start, end, text = row["start_s"], row["end_s"], row[text_key]
        if not number(start) or not number(end) or not previous <= start < end <= duration:
            raise Rejected("timings must be finite, ordered, nonoverlapping and within timeline")
        if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(c) < 32 and c != "\n" for c in text):
            raise Rejected("invalid timed text")
        previous = end


def validate_options(plan, metadata):
    duration = sum(row["end_s"] - row["start_s"] for row in plan["segments"])
    if "captions" in plan:
        timed_rows(plan["captions"], duration, "text", 64)
        for cue in plan["captions"]:
            lines = cue["text"].split("\n")
            # Fixed monospaced font, 16px, 24 columns, two lines in 246x64 box.
            # No font fallback, arbitrary markup, expression or user font path.
            if len(lines) > 2 or any(not line.strip() or len(line) > 24 for line in lines) or any(not 32 <= ord(c) <= 126 for c in cue["text"] if c != "\n"):
                raise Rejected("captions support printable ASCII, 1-2 lines, at most 24 columns each")
            if cue["end_s"] - cue["start_s"] < 1 / 24:
                raise Rejected("caption must last at least one preview frame")
    framing = plan.get("framing", {"mode": "contain"})
    if not isinstance(framing, dict):
        raise Rejected("invalid framing")
    if framing == {"mode": "contain"}:
        return
    if set(framing) != {"mode", "crop", "protected_region"} or framing["mode"] != "crop":
        raise Rejected("framing must be contain or fixed crop with protected_region")
    if metadata is None:
        raise Rejected("crop requires source metadata")
    if metadata.get("sample_aspect_ratio") not in ("1:1", "0:1") or metadata.get("rotation") != 0:
        raise Rejected("crop requires square-pixel unrotated source")
    for name in ("crop", "protected_region"):
        rect = framing[name]
        if not isinstance(rect, dict) or set(rect) != {"x", "y", "width", "height"} or any(type(v) is not int for v in rect.values()):
            raise Rejected("rectangles require integer x/y/width/height")
        if not (0 <= rect["x"] < rect["x"] + rect["width"] <= metadata["width"] and 0 <= rect["y"] < rect["y"] + rect["height"] <= metadata["height"]):
            raise Rejected("rectangle outside source")
    crop, protected = framing["crop"], framing["protected_region"]
    if any(crop[k] % 2 for k in crop) or crop["width"] * 16 != crop["height"] * 9:
        raise Rejected("crop must use even coordinates/dimensions and exact 9:16 ratio")
    for axis, size in (("x", "width"), ("y", "height")):
        margin = crop[size] * .05
        if protected[axis] < crop[axis] + margin or protected[axis] + protected[size] > crop[axis] + crop[size] - margin:
            raise Rejected("protected region must remain inside crop with five percent safety margin")
    if plan.get("captions") and (protected["y"] + protected["height"] - crop["y"]) * 480 / crop["height"] > 392:
        raise Rejected("protected region overlaps reserved caption band; revise framing or captions")


def validate_transcript(value, duration):
    if not isinstance(value, dict) or set(value) != {"language", "provenance", "words"}:
        raise Rejected("transcript requires language, provenance, words")
    for key in ("language", "provenance"):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 500:
            raise Rejected("transcript language and truthful provenance required")
    timed_rows(value["words"], duration, "word", 1000)
    return value


def visual_filters(plan, directory, stem):
    framing = plan.get("framing", {"mode": "contain"})
    if framing["mode"] == "contain":
        filters = ["scale=270:480:force_original_aspect_ratio=decrease:force_divisible_by=2", "pad=270:480:(ow-iw)/2:(oh-ih)/2"]
    else:
        c = framing["crop"]
        filters = [f"crop={c['width']}:{c['height']}:{c['x']}:{c['y']}", "scale=270:480"]
    filters += ["setsar=1", "fps=24"]
    for i, cue in enumerate(plan.get("captions", [])):
        name = f"{stem}-caption-{i}.txt"
        (directory / name).write_text(cue["text"], encoding="ascii")
        filters.append("drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:"
                       f"textfile={name}:expansion=none:fontsize=16:fontcolor=white:"
                       "borderw=1:bordercolor=black:box=1:boxcolor=black@0.65:boxborderw=4:"
                       "x=(w-text_w)/2:y=400:line_spacing=4:"
                       f"enable='gte(t,{cue['start_s']})*lt(t,{cue['end_s']})'")
    return ",".join(filters)


def review_artifacts(source, target, plan, metadata, native, input_args, digest):
    """Separate source-edge waveform/spectrum/WAV plus exact-preview WAV.

    Numeric coordinates and content hashes identify evidence, never a fabricated
    acoustic pass. Images have no axes; the manifest carries exact time/frequency
    scales and cut-marker positions for independent clients.
    """
    root, stem = target.parent, target.stem
    artifacts, edges = {}, []

    def register(name, kind):
        path = root / name
        artifacts[name] = {"sha256": digest(path), "bytes": path.stat().st_size, "content_type": kind}
        return name

    base = ["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-n", *input_args()]
    for i, row in enumerate(plan["segments"]):
        for edge in ("start", "end"):
            point = row[edge + "_s"]
            low, high = max(0, point - .8), min(metadata["duration"], point + .8)
            # Source windows, not edited windows, expose removed context too.
            prefix = f"{stem}-edge-{i}-{edge}"
            wav, wave, spectrum = [root / (prefix + suffix) for suffix in (".wav", "-waveform.png", "-spectrogram.png")]
            marker = min(639, max(0, round((point - low) / (high - low) * 640)))
            filters = (f"[0:a]atrim=start={low}:end={high},asetpts=PTS-STARTPTS,aresample=16000,"
                       "aformat=channel_layouts=mono,asplit=3[a][w][s];"
                       f"[w]showwavespic=s=640x200:colors=white,drawbox=x={marker}:y=0:w=1:h=200:color=red:t=fill[wave];"
                       f"[s]showspectrumpic=s=640x200:legend=0:scale=log:fscale=lin,drawbox=x={marker}:y=0:w=1:h=200:color=white:t=fill[spec]")
            native([*base, "-filter_complex_threads", "1", "-filter_complex", filters,
                    "-map", "[a]", "-c:a", "pcm_s16le", wav,
                    "-map", "[wave]", "-frames:v", "1", "-threads", "1", wave,
                    "-map", "[spec]", "-frames:v", "1", "-threads", "1", spectrum], source, timeout=20)
            edges.append({"segment": i, "edge": edge, "source_s": point, "window_start_s": low,
                          "window_end_s": high, "cut_marker_x": marker, "frequency_hz": [0, 8000],
                          "time_axis": "left-to-right", "frequency_axis": "bottom-to-top, linear",
                          "waveform": register(wave.name, "image/png"),
                          "spectrogram": register(spectrum.name, "image/png"),
                          "audio": register(wav.name, "audio/wav"), "review_status": "unreviewed"})
    audio = root / (stem + "-preview-audio.wav")
    native([*base, "-map", "0:a:0", "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", audio], target, timeout=30)
    register(audio.name, "audio/wav")
    return {"artifacts": artifacts, "edges": edges, "preview_audio": audio.name,
            "basis": "Source +/-0.8s edge windows per recovered speech_cut_audit contract; native FFmpeg adapter.",
            "audio_lock": False, "human_audition": False,
            "caption_timing_basis": "externally supplied output seconds, 24fps quantization; alignment unverified",
            "protected_region_basis": "caller assertion; geometry checked, no face detection or tracking"}
