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


def cut_regions(words, blocks, duration):
    """Keep/drop regions for James' speech_cut_audit.py built from the ASSEMBLED blocks (sample-exact edit-map
    segments), so every region's retained time equals what it claims. A word crossing a block edge is split into
    a keep part and a drop part; drop regions for the cuts are the exact gaps between blocks. Returns
    (regions, removed_words, kept_words) where a word counts as removed when most of it lies outside the blocks."""
    spans = sorted((float(b["start_s"]), float(b["end_s"])) for b in blocks)
    gaps, cursor = [], 0.0
    for a, b in spans:
        if a - cursor > 1e-9:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if duration - cursor > 1e-9:
        gaps.append((cursor, float(duration)))
    regions, removed, kept = [], [], []
    for w in words:
        s, e = float(w["start"]), float(w["end"])
        if e - s < 0.005:
            continue
        inside = 0.0
        for a, b in spans:
            lo, hi = max(s, a), min(e, b)
            if hi - lo >= 0.001:
                regions.append({"mode": "keep", "start_s": lo, "end_s": hi, "word": str(w["word"])[:100]})
                inside += hi - lo
        for a, b in gaps:
            lo, hi = max(s, a), min(e, b)
            if hi - lo >= 0.001:
                regions.append({"mode": "drop", "start_s": lo, "end_s": hi, "word": str(w["word"])[:100], "reason": "inside an approved cut"})
        (kept if inside >= (e - s) / 2 else removed).append(w["word"])
    for a, b in gaps:
        regions.append({"mode": "drop", "start_s": a, "end_s": b, "reason": "approved cut (exact assembled gap)"})
    regions.sort(key=lambda r: (r["start_s"], r["end_s"]))
    return regions, removed, kept


def align_words(a, b, indices=False):
    """Minimal-edit word alignment (banded Levenshtein on normalized tokens). Returns (lost, added): tokens of `a`
    missing from `b` and tokens of `b` not in `a`. Unlike difflib's longest-block matching, repeated phrases can't
    shift the alignment by a whole repetition, so one dropped word in a long repetitive transcript is reported as
    exactly that word. indices=True returns positions in `a` and `b` instead of tokens."""
    n, m = len(a), len(b)
    band = abs(n - m) + 256
    INF = n + m + 1
    rows = []  # per i: (lo, list of costs for j in lo..hi)
    prev_lo, prev = 0, list(range(0, min(m, band) + 1))
    rows.append((prev_lo, prev))
    for i in range(1, n + 1):
        lo, hi = max(0, i - band), min(m, i + band)
        cur = []
        for j in range(lo, hi + 1):
            best = INF
            if j == 0:
                best = i
            else:
                if prev_lo <= j - 1 < prev_lo + len(prev):
                    best = prev[j - 1 - prev_lo] + (a[i - 1] != b[j - 1])
                if cur:
                    best = min(best, cur[-1] + 1)
            if prev_lo <= j < prev_lo + len(prev):
                best = min(best, prev[j - prev_lo] + 1)
            cur.append(best)
        rows.append((lo, cur))
        prev_lo, prev = lo, cur
    cost = lambda i, j: rows[i][1][j - rows[i][0]] if rows[i][0] <= j < rows[i][0] + len(rows[i][1]) else INF
    lost, added = [], []
    i, j = n, m
    while i > 0 or j > 0:
        c = cost(i, j)
        if i > 0 and j > 0 and c == cost(i - 1, j - 1) + (a[i - 1] != b[j - 1]):
            if a[i - 1] != b[j - 1]:
                lost.append(i - 1); added.append(j - 1)
            i, j = i - 1, j - 1
        elif i > 0 and c == cost(i - 1, j) + 1:
            lost.append(i - 1); i -= 1
        else:
            added.append(j - 1); j -= 1
    lost, added = lost[::-1], added[::-1]
    if indices:
        return lost, added
    return [a[k] for k in lost], [b[k] for k in added]


# ---------- silence checks and edit candidates (pure; used by mcp_server.py) ----------

FILLERS = {"um", "umm", "uhm", "uh", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm"}
# Tokens reported separately when one transcript has them and the other doesn't (James' asr.py: ASR can omit fillers).
REPORT_FILLERS = FILLERS | {"oh", "ahh", "eh"}
PAUSE_S = 0.5          # gaps between words longer than this are pause candidates
HANDLE_S = 0.12        # silence kept on each side of a cut
SPEECH_DROP_DB = 15.0  # a 10 ms frame louder than (file speech level - 15 dB) is speech-like
SPEECH_FLOOR_DB = -50.0
SPEECH_GUARD_S = 0.06  # speech-like audio an applied cut may contain outside transcribed words
REVIEW_MIN_S = 0.1     # speech-like audio inside a gap (after edge tails) that makes it untranscribed_sound
WORD_PAD_S = 0.05
EDGE_GUARD_S = 0.15    # minimum distance from a pause cut to the nearest (aligned) word
TAIL_MARGIN_S = 0.1    # extra silence kept after a word's audible tail / before its audible onset
TAIL_DROP_DB = 30.0    # word tails/onsets (sibilants, soft onsets): frames above (level - 30 dB) or floor + 6 dB


def _norm(word):
    return "".join(c for c in str(word).lower() if c.isalnum())


def speech_level(env, words):
    """Median loudness (dBFS) of transcribed words of at least 80 ms: the file's speech level."""
    fs, db = env["frame_s"], env["dbfs"]
    vals = []
    for w in words:
        if w["end"] - w["start"] < 0.08:
            continue
        frames = db[int(w["start"] / fs):int(w["end"] / fs)]
        if frames:
            power = sum(10 ** (d / 10) for d in frames) / len(frames)
            vals.append(10 * math.log10(power) if power > 0 else -120.0)
    if not vals:
        loud = sorted(db)
        return loud[int(len(loud) * 0.9)] if loud else None
    vals.sort()
    return round(vals[len(vals) // 2], 1)


def speech_like(env, a, b, level, words=()):
    """Seconds of speech-like 10 ms frames in [a, b) outside transcribed word spans (+-50 ms)."""
    if level is None:
        return 0.0
    fs, db = env["frame_s"], env["dbfs"]
    threshold = max(level - SPEECH_DROP_DB, SPEECH_FLOOR_DB)
    spans = [(w["start"] - WORD_PAD_S, w["end"] + WORD_PAD_S) for w in words if w["end"] > a - 1 and w["start"] < b + 1]
    n = 0
    for i in range(max(0, int(a / fs)), min(len(db), int(math.ceil(b / fs)))):
        t = (i + 0.5) * fs
        if a <= t < b and db[i] > threshold and not any(lo <= t <= hi for lo, hi in spans):
            n += 1
    return round(n * fs, 2)


def _edge_threshold(env, level):
    db = sorted(env["dbfs"])
    floor = db[len(db) // 10] if db else -120.0
    return max(level - TAIL_DROP_DB, floor + 6.0)


def quiet_span(env, level, a, b, lead=False, trail=False):
    """Cut range inside the gap [a, b] between two words that keeps their audible tail/onset.

    Starts at least EDGE_GUARD_S after `a` and TAIL_MARGIN_S after the last audible frame of the run that continues
    from `a` (a quiet "ts" or breathy release), and ends symmetrically before `b`. lead/trail: the gap is the file's
    start/end (no word on that side). Returns (lo, hi) or None when nothing safe is left."""
    fs, db = env["frame_s"], env["dbfs"]
    thr = _edge_threshold(env, level)
    lo, hi = (0.0 if lead else a + EDGE_GUARD_S), (b if trail else b - EDGE_GUARD_S)
    if not lead:
        last, i = a, int(a / fs)
        while i < len(db) and (i + 0.5) * fs < b:
            t = (i + 0.5) * fs
            if db[i] > thr:
                last = t + fs / 2
            elif t - last > 0.12:
                break
            i += 1
        lo = max(lo, last + TAIL_MARGIN_S)
    if not trail:
        first, i = b, min(len(db) - 1, int(b / fs))
        while i >= 0 and (i + 0.5) * fs > a:
            t = (i + 0.5) * fs
            if db[i] > thr:
                first = t - fs / 2
            elif first - t > 0.12:
                break
            i -= 1
        hi = min(hi, first - TAIL_MARGIN_S)
    return (round(lo, 3), round(hi, 3)) if hi - lo >= 0.1 else None


def candidates_from(words, duration, env=None):
    """Filler / repeat / pause candidates, the default cut proposal, and gaps with untranscribed sound.

    A pause (or the span around a filler) is proposed only when the audio there is actually near-silent: ASR can skip
    whole sentences, so a transcript gap is not proof of silence. Gaps with speech-like audio go to
    `untranscribed_sound` for owner review and are never proposed. Without an energy envelope nothing but tight
    filler spans is proposed."""
    level = speech_level(env, words) if env else None
    loud = (lambda a, b: speech_like(env, a, b, level, words)) if env else (lambda a, b: None)
    cands, review = [], []
    around = lambda a, b: (" ".join(w["word"] for w in words if w["end"] <= a)[-60:], " ".join(w["word"] for w in words if w["start"] >= b)[:60])
    for i, w in enumerate(words):
        n = _norm(w["word"])
        prev_end = words[i - 1]["end"] if i else 0.0
        next_start = words[i + 1]["start"] if i + 1 < len(words) else duration
        if n in FILLERS:
            cut = [round(max(0.0, w["start"] - 0.02), 3), round(min(duration, w["end"] + 0.02), 3)]
            if env:  # extend into the measured-silent part of the gaps around the filler, never into a neighbour's tail
                left = quiet_span(env, level, prev_end, w["start"], lead=i == 0)
                right = quiet_span(env, level, w["end"], next_start, trail=i + 1 == len(words))
                if left and loud(left[0], w["start"]) <= SPEECH_GUARD_S:
                    cut[0] = left[0]
                if right and loud(w["end"], right[1]) <= SPEECH_GUARD_S:
                    cut[1] = right[1]
            cands.append({"kind": "filler", "word": w["word"], "word_index": i, "start_s": w["start"], "end_s": w["end"],
                          "cut": cut, "reason": f"filler '{w['word']}'"})
        if i + 1 < len(words) and n and n == _norm(words[i + 1]["word"]) and n not in FILLERS:
            cands.append({"kind": "repeat", "word": w["word"], "word_index": i, "start_s": w["start"], "end_s": w["end"],
                          "cut": [round(max(0.0, w["start"] - 0.02), 3), round(max(w["start"], words[i + 1]["start"] - 0.02), 3)],
                          "reason": f"repeated word '{w['word']}' (possible restart; check meaning)"})
    edges = [(0.0, words[0]["start"] if words else duration, "leading silence")]
    edges += [(words[i]["end"], words[i + 1]["start"], "long pause") for i in range(len(words) - 1)]
    if words:
        edges.append((words[-1]["end"], duration, "trailing silence"))
    for a, b, label in edges:
        if b - a < PAUSE_S:
            continue
        span = quiet_span(env, level, a, b, lead=label == "leading silence", trail=label == "trailing silence") if env else (a + HANDLE_S, b - HANDLE_S)
        if not span or span[1] - span[0] < 0.1:
            continue
        lo, hi = span
        sound = loud(lo, hi)
        if sound is None or sound > REVIEW_MIN_S:
            before, after = around(a, b)
            review.append({"start_s": round(a, 3), "end_s": round(b, 3), "speech_like_s": sound, "before": before, "after": after,
                           "note": ("silence not measured (no energy envelope); review before cutting" if sound is None else
                                    f"about {sound:.1f} s of speech-like sound with no transcript in this {label}: possibly a "
                                    "sentence or filler the ASR skipped. Review before cutting; not proposed.")})
            continue
        cands.append({"kind": "pause", "start_s": round(a, 3), "end_s": round(b, 3), "cut": [round(lo, 3), round(hi, 3)],
                      "speech_like_s": sound, "reason": f"{label} {b - a:.2f} s (measured near-silent)"})
    cands.sort(key=lambda c: c["cut"][0])
    merged = []
    for c in cands:
        if c["kind"] == "repeat":
            continue  # repeats are review items, not default cuts
        if merged and c["cut"][0] <= merged[-1]["end_s"] + 0.05:
            merged[-1]["end_s"] = max(merged[-1]["end_s"], c["cut"][1])
            merged[-1]["reason"] += "; " + c["reason"]
        else:
            merged.append({"start_s": c["cut"][0], "end_s": c["cut"][1], "reason": c["reason"]})
    screen = {"speech_level_dbfs": level, "speech_like_threshold_db_below_level": SPEECH_DROP_DB,
              "review_min_s": REVIEW_MIN_S, "edge_guard_s": EDGE_GUARD_S, "tail_margin_s": TAIL_MARGIN_S,
              "tail_threshold_db_below_level": TAIL_DROP_DB, "measured": env is not None,
              "basis": "10 ms RMS envelope of the 48 kHz source vs the median loudness of aligned words; frames inside "
                       "aligned words (+-50 ms) are not counted. Pause cuts stay >= 0.15 s from words and 0.1 s past any "
                       "audible tail/onset (frames above level - 30 dB or noise floor + 6 dB)."}
    return cands, merged, review, screen


def cut_sound_check(cuts, env, words):
    """Measure every applied cut (proposed or hand-written). A cut with more than SPEECH_GUARD_S of speech-like audio
    outside transcribed words fails unless it carries owner_approved_sound: true."""
    level = speech_level(env, words)
    rows, failures = [], []
    for c in cuts:
        s = speech_like(env, c["start_s"], c["end_s"], level, words)
        row = {"start_s": c["start_s"], "end_s": c["end_s"], "speech_like_s": s,
               "owner_approved_sound": bool(c.get("owner_approved_sound"))}
        rows.append(row)
        if s > SPEECH_GUARD_S and not row["owner_approved_sound"]:
            failures.append(f"cut {c['start_s']:.2f}-{c['end_s']:.2f} s contains about {s:.1f} s of speech-like audio "
                            "that the transcript does not account for")
    return {"speech_level_dbfs": level, "guard_s": SPEECH_GUARD_S, "cuts": rows, "failures": failures,
            "pass": not failures,
            "override": "set owner_approved_sound: true on a cut only after the owner listened and approved removing that sound"}


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _phonetic(word):
    """Small Soundex-style key: first letter + consonant classes, vowels/h/w/y dropped, repeats collapsed."""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"), "l": "4",
             **dict.fromkeys("mn", "5"), "r": "6"}
    w = "".join(c for c in word.lower() if c.isalpha())
    if not w:
        return ""
    out, last = [w[0]], codes.get(w[0])
    for c in w[1:]:
        k = codes.get(c)
        if k and k != last:
            out.append(k)
        last = k if c not in "hw" else last
    return "".join(out)


def spelling_variant(a, b):
    """True when two ASR tokens are the same spoken word spelled differently between two transcriptions
    (e.g. trellis/trellies): both >= 4 letters and normalized edit distance <= 0.34 or the same phonetic key."""
    if a == b or len(a) < 4 or len(b) < 4 or not a.isalpha() or not b.isalpha():
        return False
    return _edit_distance(a, b) / max(len(a), len(b)) <= 0.34 or _phonetic(a) == _phonetic(b)


def diff_words(expected, got, variants=False):
    """Content words lost/added between two normalized token lists, with fillers diffed separately.

    Fillers are removed before the alignment (ASR can omit them, James' asr.py), so a filler present in only one
    transcript can never pair with, or hide, a real content word. An aligned substitution between near-identical
    spellings (spelling_variant) is an ASR spelling variant, not a lost word. Returns (lost, added,
    fillers_only_in_expected, fillers_only_in_got) and, with variants=True, a fifth list of [expected, got] pairs."""
    from collections import Counter
    ce, cg = [w for w in expected if w not in REPORT_FILLERS], [w for w in got if w not in REPORT_FILLERS]
    li, ai = align_words(ce, cg, indices=True)
    pairs, lost_set, added_set = [], set(li), set(ai)
    # align_words emits a substitution as a lost/added pair with equal running position; pair them in order.
    for i in li:
        # the substituted counterpart is the added index whose matched-prefix position equals i's
        for j in ai:
            if j in added_set and (i - sum(1 for x in li if x < i)) == (j - sum(1 for y in ai if y < j)) and spelling_variant(ce[i], cg[j]):
                pairs.append([ce[i], cg[j]]); lost_set.discard(i); added_set.discard(j)
                break
    lost, added = [ce[i] for i in li if i in lost_set], [cg[j] for j in ai if j in added_set]
    fe, fg = Counter(w for w in expected if w in REPORT_FILLERS), Counter(w for w in got if w in REPORT_FILLERS)
    out = (lost, added, sorted((fe - fg).elements()), sorted((fg - fe).elements()))
    return (*out, pairs) if variants else out
