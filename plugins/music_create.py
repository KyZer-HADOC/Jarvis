"""
Music Create — compose an original instrumental track, fully offline, no API key.

    "Jarvis, make a lo-fi beat for studying"
    "Compose a 60 second epic cinematic track in D minor"
    "Make upbeat music for my video"          (then: "put it under my video" -> video_toolkit add_music)

JARVIS writes the chords, bass line, melody and drums itself and renders them to a WAV
(and an MP3 when ffmpeg is installed) in ~/Music/JARVIS.

Be realistic: this is synthesized background music, good for video backing tracks, study
loops and ideas. It is not a vocal / full-band generator like Suno. The same seed always
gives the same track, so "make another one" gives a new tune.
"""
from __future__ import annotations

import math
import random
import re
import time
import wave
from pathlib import Path

import numpy as np

from plugins import _media as M

PLUGIN = {
    "name": "music_create",
    "description": (
        "Composes an original instrumental music track (no vocals) and saves it as an audio file. "
        "Use when the user asks to make / create / compose music, a beat, a lo-fi track, "
        "background music or a soundtrack. style: lofi, chill, happy, energetic, sad, epic, dark "
        "(pick from the user's mood words). Optional duration in seconds (15-180), tempo and key "
        "like 'A minor'. Do NOT use to play existing songs (use video_player / spotify_control) "
        "and it cannot sing lyrics."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "style": {"type": "STRING", "description": "lofi | chill | happy | energetic | sad | epic | dark. Or describe the mood in 'mood'."},
            "mood": {"type": "STRING", "description": "Free-text description, e.g. 'rainy night study session'. Used to pick a style if none given."},
            "duration": {"type": "INTEGER", "description": "Length in seconds, 15-180. Default 45."},
            "tempo": {"type": "INTEGER", "description": "Beats per minute, 50-170. Default depends on style."},
            "key": {"type": "STRING", "description": "Optional key, e.g. 'C major', 'F# minor', 'D'."},
            "seed": {"type": "INTEGER", "description": "Same seed = same tune. Leave empty for a new tune each time."},
            "open_result": {"type": "BOOLEAN", "description": "True to play it when done."},
        },
        "required": [],
    },
}

SR = 44100
_SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10]}

# bpm range, scale, chord progressions (scale degrees, 0 = tonic), sevenths, swing (fraction of a beat),
# drum kit, lead sound, lowpass cutoff (Hz) for warmth, vinyl crackle, melody density
_STYLES = {
    "lofi":      dict(bpm=(68, 82),   scale="minor",  prog=[[0, 5, 2, 6], [0, 3, 5, 4], [1, 4, 0, 0]], sev=True,  swing=.14, drums="lofi", lead="soft",   lp=3800, crackle=True,  dens=.50),
    "chill":     dict(bpm=(86, 100),  scale="major",  prog=[[0, 4, 5, 3], [0, 5, 3, 4], [3, 4, 2, 5]], sev=True,  swing=.06, drums="soft", lead="soft",   lp=6000, crackle=False, dens=.45),
    "happy":     dict(bpm=(112, 126), scale="major",  prog=[[0, 4, 5, 3], [0, 3, 4, 4], [0, 5, 3, 4]], sev=False, swing=0,   drums="pop",  lead="bright", lp=12000, crackle=False, dens=.62),
    "energetic": dict(bpm=(124, 138), scale="major",  prog=[[5, 3, 0, 4], [0, 4, 5, 3]],               sev=False, swing=0,   drums="four", lead="bright", lp=14000, crackle=False, dens=.70),
    "sad":       dict(bpm=(58, 72),   scale="minor",  prog=[[0, 5, 2, 6], [0, 3, 6, 2], [5, 6, 0, 0]], sev=True,  swing=0,   drums="none", lead="soft",   lp=5000, crackle=False, dens=.38),
    "epic":      dict(bpm=(88, 108),  scale="minor",  prog=[[0, 5, 2, 6], [0, 6, 5, 4], [0, 2, 6, 4]], sev=False, swing=0,   drums="epic", lead="bright", lp=9000, crackle=False, dens=.48),
    "dark":      dict(bpm=(76, 92),   scale="dorian", prog=[[0, 0, 5, 6], [0, 1, 0, 6], [0, 3, 0, 4]], sev=True,  swing=0,   drums="soft", lead="soft",   lp=4500, crackle=False, dens=.40),
}
_KEYWORDS = [
    ("lofi", r"lo-?fi|study|focus|rain|relax|sleep|coffee|beat"),
    ("energetic", r"energ|workout|gym|dance|hype|party|fast|run"),
    ("epic", r"epic|cinematic|trailer|battle|hero|heroic|orchestr"),
    ("dark", r"dark|horror|suspense|mystery|creepy|thriller|tense"),
    ("sad", r"\bsad|emotional|melanchol|cry|lonely|heartbreak|nostalg"),
    ("happy", r"happy|upbeat|fun|summer|joy|cheer|bright|vlog"),
    ("chill", r"chill|calm|ambient|peace|soft|travel|sunset|cafe"),
]
# drum grids on 16 steps per bar
_DRUMS = {
    "lofi": dict(k="x.....x...x.....", s="....x.......x...", h="x.x.x.x.x.x.x.x."),
    "soft": dict(k="x.......x.......", s="........x.......", h="..x...x...x...x."),
    "pop":  dict(k="x...x...x...x...", s="....x.......x...", h="x.x.x.x.x.x.x.x."),
    "four": dict(k="x...x...x...x...", s="....x.......x...", h="..x...x...x...x."),
    "epic": dict(k="x.......x.....x.", s="........x.......", h=""),
    "none": dict(k="", s="", h=""),
}
_NOTE_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


# ── tiny synth ─────────────────────────────────────────────────────────────────
def _freq(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _wave(kind: str, f: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    ph = 2 * np.pi * f * t
    if kind == "soft":
        return np.sin(ph) + 0.25 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    if kind == "bright":                     # a few harmonics of a saw: bright but not harsh
        return sum(np.sin(k * ph) / k for k in range(1, 7)) * 0.7
    if kind == "bass":
        return np.sin(ph) + 0.3 * np.sin(2 * ph)
    return np.sin(ph)


def _place(buf: np.ndarray, start_s: float, w: np.ndarray, gain: float) -> None:
    i = int(start_s * SR)
    if i >= len(buf) or i < 0:
        return
    j = min(len(buf), i + len(w))
    buf[i:j] += w[: j - i] * gain


def _adsr(n: int, a: float, r: float, decay_tau: float | None = None) -> np.ndarray:
    e = np.ones(n)
    if decay_tau:
        e = np.exp(-np.arange(n) / (SR * decay_tau))
    na, nr = min(n, max(1, int(a * SR))), min(n, max(1, int(r * SR)))
    e[:na] *= np.linspace(0, 1, na)
    e[n - nr:] *= np.linspace(1, 0, nr)
    return e


def _kick() -> np.ndarray:
    n = int(0.32 * SR)
    t = np.arange(n) / SR
    f = 45 + 95 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _snare(rng: np.random.Generator) -> np.ndarray:
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    return (rng.standard_normal(n) * 0.7 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 20)


def _hat(rng: np.random.Generator) -> np.ndarray:
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    x = np.diff(x, prepend=0)                # crude high-pass
    return x * np.exp(-t * 70) * 0.5


def _reverb(x: np.ndarray, rng: np.random.Generator, secs: float = 1.5, tau: float = 0.38) -> np.ndarray:
    n = int(secs * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * tau))
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(math.ceil(math.log2(len(x) + n)))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(spec / (1 + (f / cutoff) ** 4), len(x))


# ── composition ────────────────────────────────────────────────────────────────
def _pick_style(style: str, mood: str) -> str:
    s = (style or "").lower().strip()
    if s in _STYLES:
        return s
    text = f"{s} {mood or ''}".lower()
    for name, pat in _KEYWORDS:
        if re.search(pat, text):
            return name
    return "lofi"


def _parse_key(key: str, default_scale: str) -> tuple[int, str, str]:
    """-> (pitch class, scale name, pretty name)"""
    m = re.match(r"\s*([a-gA-G])\s*([#b♯♭]?)\s*(major|minor|maj|min|m)?", key or "")
    if not m:
        return -1, default_scale, ""
    pc = _NOTE_PC[m.group(1).lower()] + {"#": 1, "♯": 1, "b": -1, "♭": -1}.get(m.group(2), 0)
    q = (m.group(3) or "").lower()
    scale = "minor" if q in ("minor", "min", "m") else "major" if q in ("major", "maj") else default_scale
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return pc % 12, scale, f"{names[pc % 12]} {scale}"


def _rhythm(rng: random.Random, dens: float, bars: int = 4) -> list[list[tuple[int, int]]]:
    """Per bar: [(step on the 8th-note grid, length in steps), ...]."""
    out = []
    for _ in range(bars):
        notes, step = [], 0
        while step < 8:
            p = min(1.0, dens + 0.3) if step in (0, 4) else dens
            if rng.random() < p:
                ln = min(rng.choice([1, 1, 2, 2, 3]), 8 - step)
                notes.append((step, ln))
                step += ln
            else:
                step += 1
        out.append(notes)
    return out


def _pitches(rng: random.Random, chords: list[int], rhythm, center: int) -> list[list[tuple[int, int, int]]]:
    cur, phrase = center, []
    for ch, bar in zip(chords, rhythm):
        tones = {(ch + k) % 7 for k in (0, 2, 4)}
        notes = []
        for step, ln in bar:
            cand = max(center - 4, min(center + 5, cur + rng.choice([-2, -1, -1, 0, 1, 1, 2])))
            if step in (0, 4) and cand % 7 not in tones:
                cand = min((c for c in range(cand - 3, cand + 4) if c % 7 in tones), key=lambda c: abs(c - cand))
            cur = cand
            notes.append((step, cur, ln))
        phrase.append(notes)
    return phrase


def compose(style: str, duration: float, bpm: int | None, key: str, seed: int) -> tuple[np.ndarray, dict]:
    cfg = _STYLES[style]
    rnd = random.Random(seed)
    rng = np.random.default_rng(seed)

    bpm = int(bpm) if bpm else rnd.randint(*cfg["bpm"])
    beat = 60.0 / bpm
    bar_s = beat * 4
    n_bars = max(4, int(round(duration / bar_s)))
    total = n_bars * bar_s + 2.5                      # tail for release / reverb
    n = int(total * SR)

    pc, scale_name, pretty = _parse_key(key, cfg["scale"])
    if pc < 0:
        pc = rnd.choice([0, 2, 3, 5, 7, 9, 10])
        pretty = f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][pc]} {scale_name}"
    sc = _SCALES[scale_name]
    base = 48 + (pc if pc <= 6 else pc - 12)

    def deg(d: int, root: int) -> int:
        return root + sc[d % 7] + 12 * (d // 7)

    # chord per bar: pick a progression, repeat it, resolve to the tonic at the end
    progs = [rnd.choice(cfg["prog"]) for _ in range((n_bars + 3) // 4)]
    chords = [progs[b // 4][b % 4] for b in range(n_bars)]
    chords[-1] = 0

    pad_l, pad_r = np.zeros(n), np.zeros(n)
    bass, lead, drums = np.zeros(n), np.zeros(n), np.zeros(n)

    # pad + bass
    for b, d in enumerate(chords):
        t0 = b * bar_s
        steps = [d, d + 2, d + 4] + ([d + 6] if cfg["sev"] else [])
        nn = int((bar_s + 0.35) * SR)
        env = _adsr(nn, 0.30, 0.55)
        for k, s in enumerate(steps):
            f = _freq(deg(s, base + 12))
            _place(pad_l, t0, _wave("soft", f * 0.997, nn) * env, 0.075)
            _place(pad_r, t0, _wave("soft", f * 1.003, nn) * env, 0.075)
        rootf = _freq(deg(d, base - 12))
        pattern = [(0, 3.0), (3, 1.0), (6, 1.5)] if cfg["drums"] in ("lofi", "soft", "none") else \
                  [(i, 1.0) for i in range(0, 8, 1 if cfg["drums"] == "four" else 2)]
        for step, lng in pattern:
            ln = max(0.2, min(lng * beat * 0.5, bar_s - step * beat / 2))
            nb = int(ln * SR)
            _place(bass, t0 + step * beat / 2, _wave("bass", rootf, nb) * _adsr(nb, 0.01, 0.08, 0.45), 0.34)

    # melody: a rhythmic motif is reused for every 4-bar block, with new pitches
    motif = _rhythm(rnd, cfg["dens"])
    for blk in range((n_bars + 3) // 4):
        b0 = blk * 4
        if b0 < 2 and n_bars > 8:                      # let the intro breathe
            continue
        blk_chords = chords[b0:b0 + 4] + [0] * (4 - len(chords[b0:b0 + 4]))
        phrase = _pitches(rnd, blk_chords, motif, center=2)
        for bi, notes in enumerate(phrase):
            b = b0 + bi
            if b >= n_bars - 1:                        # last bar: let the chord ring out
                break
            for step, d, ln in notes:
                if rnd.random() < 0.08:                # occasional rest keeps it human
                    continue
                st = b * bar_s + step * beat / 2
                if cfg["swing"] and step % 2 == 1:
                    st += cfg["swing"] * beat
                dur = ln * beat / 2
                nb = int((dur + 0.2) * SR)
                w = _wave(cfg["lead"], _freq(deg(d, base + 24)), nb)
                _place(lead, st, w * _adsr(nb, 0.008, 0.18, max(0.12, dur * 0.8)), 0.17)

    # drums
    kit = _DRUMS[cfg["drums"]]
    k_w, s_w, h_w = _kick(), _snare(rng), _hat(rng)
    boom = cfg["drums"] == "epic"
    for b in range(2 if n_bars > 8 else 0, n_bars - 1):
        for i in range(16):
            st = b * bar_s + i * beat / 4
            if cfg["swing"] and i % 4 == 2:
                st += cfg["swing"] * beat
            st += rnd.uniform(-0.004, 0.004)
            v = rnd.uniform(0.85, 1.0)
            if i < len(kit["k"]) and kit["k"][i] == "x":
                _place(drums, st, k_w * (1.4 if boom else 1.0), 0.55 * v)
            if i < len(kit["s"]) and kit["s"][i] == "x":
                _place(drums, st, s_w, 0.32 * v)
            if i < len(kit["h"]) and kit["h"][i] == "x":
                _place(drums, st, h_w, 0.20 * v * (0.6 if i % 4 else 1.0))

    # echo on the lead, then reverb on the tonal parts
    d_n = int(beat * 0.75 * SR)
    lead_fx = lead.copy()
    lead_fx[d_n:] += lead[:-d_n] * 0.32
    tonal = pad_l + pad_r + lead_fx
    wet = _reverb(tonal, rng) * (0.30 if boom else 0.20)

    left = pad_l + bass + lead_fx + drums + wet
    right = pad_r + bass + np.roll(lead_fx, int(0.012 * SR)) + drums + wet
    stereo = np.stack([left, right], axis=1)

    for ch in (0, 1):
        stereo[:, ch] = _lowpass(stereo[:, ch], cfg["lp"])
    if cfg["crackle"]:
        pops = (rng.random(n) < 0.0005) * rng.standard_normal(n) * 0.10
        hiss = rng.standard_normal(n) * 0.0015
        stereo += np.stack([pops + hiss, np.roll(pops, 7) + hiss], axis=1)

    stereo = np.tanh(stereo * 1.15)
    fade_in, fade_out = int(0.25 * SR), int(2.2 * SR)
    stereo[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    stereo[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = float(np.max(np.abs(stereo))) or 1.0
    stereo *= 0.89 / peak
    return stereo.astype(np.float32), {"bpm": bpm, "key": pretty, "seconds": total, "bars": n_bars}


def write_wav(path: Path, stereo: np.ndarray) -> None:
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ── entry point ────────────────────────────────────────────────────────────────
def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        style = _pick_style(str(parameters.get("style", "")), str(parameters.get("mood", "")))
        try:
            duration = max(15, min(180, int(parameters.get("duration") or 45)))
        except (TypeError, ValueError):
            duration = 45
        try:
            bpm = int(parameters.get("tempo") or 0) or None
            if bpm is not None:
                bpm = max(50, min(170, bpm))
        except (TypeError, ValueError):
            bpm = None
        try:
            seed = int(parameters.get("seed")) if parameters.get("seed") not in (None, "") else int(time.time() * 1000) % 10_000_000
        except (TypeError, ValueError):
            seed = int(time.time() * 1000) % 10_000_000

        M.log(player, f"Composing a {style} track…")
        stereo, meta = compose(style, duration, bpm, str(parameters.get("key", "")), seed)

        label = M.slug(str(parameters.get("mood") or style), 24)
        wav_path = M.unique(M.out_dir("audio") / f"{label}_{style}.wav")
        write_wav(wav_path, stereo)
        final = wav_path
        try:                                                # a smaller MP3 when ffmpeg is around
            mp3 = wav_path.with_suffix(".mp3")
            M.run_ffmpeg(["-i", str(wav_path), "-c:a", "libmp3lame", "-q:a", "2", str(mp3)], timeout=120)
            final = mp3
        except M.MediaError:
            pass
        M.log(player, f"Track saved: {final.name}")
        opened = ""
        if parameters.get("open_result"):
            opened = " Playing it now." if M.open_path(final) else ""
        return (f"Done. Composed a {int(meta['seconds'])} second {style} track, {meta['bpm']} BPM in "
                f"{meta['key']}, saved as {final.name} in {final.parent.parent.name}/{final.parent.name}. "
                f"Seed {seed} if you want this exact tune again.{opened}")
    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, music_create failed: {e}"
