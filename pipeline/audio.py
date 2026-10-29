#!/usr/bin/env python3
"""Procedural, copyright-free audio for reels: a lo-fi beat + UI sound effects.

No voice. Everything is synthesized with numpy, so there is nothing to license.
make_track(duration, events, seed) -> float32 stereo array at SR.
events: list of (time_sec, kind) with kind in {"key", "send", "pop", "whoosh"}.
"""
import numpy as np, wave

SR = 44100

# chord progressions (MIDI notes); one chord per bar
PROGS = [
    [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]],   # Fmaj7 Em7 Dm7 Cmaj7
    [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 65]],   # Am7 Fmaj7 Cmaj7 G7
    [[50, 53, 57, 60], [55, 59, 62, 65], [48, 52, 55, 59], [57, 60, 64, 67]],   # Dm7 G7 Cmaj7 Am7
]


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    # vectorised one-pole via lfilter-like loop is slow in python; use cumulative trick in blocks
    try:
        from scipy.signal import lfilter
        return lfilter([1 - a], [1, -a], x).astype(np.float32)
    except Exception:
        for i in range(len(x)):
            acc = (1 - a) * x[i] + a * acc
            y[i] = acc
        return y


def env(n, attack, decay):
    t = np.arange(n) / SR
    e = np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-t / decay)
    return e.astype(np.float32)


def add(buf, start, sig, gain=1.0):
    i = int(start * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def epiano(freq, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t / 0.4) \
        + 0.12 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t / 0.15)
    trem = 1 + 0.12 * np.sin(2 * np.pi * 4.5 * t)
    return (s * trem * env(n, 0.01, 1.6)).astype(np.float32)


def kick():
    n = int(0.45 * SR); t = np.arange(n) / SR
    f = 45 + 85 * np.exp(-t / 0.045)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t / 0.18)).astype(np.float32)


def snare(rng):
    n = int(0.3 * SR); t = np.arange(n) / SR
    noise = lowpass(rng.standard_normal(n).astype(np.float32), 5000)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    return (0.7 * noise * np.exp(-t / 0.09) + 0.5 * body).astype(np.float32)


def hat(rng):
    n = int(0.06 * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n).astype(np.float32)
    hp = noise - lowpass(noise, 7000)
    return (hp * np.exp(-t / 0.018)).astype(np.float32)


def beat(duration, seed=0, bpm=82):
    rng = np.random.default_rng(seed)
    prog = PROGS[seed % len(PROGS)]
    n = int((duration + 2) * SR)
    music = np.zeros(n, np.float32)
    drums = np.zeros(n, np.float32)
    spb = 60.0 / bpm
    bar = 4 * spb
    swing = 0.06 * spb
    k, h = kick(), hat(rng)
    bars = int(duration / bar) + 2
    for b in range(bars):
        t0 = b * bar
        chord = prog[b % len(prog)]
        # e-piano chord, slightly strummed
        for j, m in enumerate(chord):
            add(music, t0 + j * 0.012, epiano(hz(m), bar + 0.4), 0.11)
        # second hit on beat 3 "and" for movement
        for j, m in enumerate(chord[1:]):
            add(music, t0 + 2.5 * spb + j * 0.01, epiano(hz(m + 12), 1.0), 0.035)
        # bass
        root = hz(chord[0] - 24)
        for pos, dur in ((0, 1.4 * spb), (1.5 * spb, 0.5 * spb), (2.5 * spb, 1.3 * spb)):
            nn = int(dur * SR); tt = np.arange(nn) / SR
            add(music, t0 + pos, (np.sin(2 * np.pi * root * tt) * env(nn, 0.008, 0.5)).astype(np.float32), 0.32)
        # drums
        for pos in (0, 1.5 * spb, 2.5 * spb):
            add(drums, t0 + pos, k, 0.9)
        for pos in (spb, 3 * spb):
            add(drums, t0 + pos, snare(rng), 0.32)
        for e in range(8):
            pos = e * spb / 2 + (swing if e % 2 else 0)
            add(drums, t0 + pos, h, 0.10 if e % 2 else 0.16)
    music = lowpass(music, 3200)
    mix = music + lowpass(drums, 9000)
    # vinyl crackle + soft hiss
    crackle = np.zeros(n, np.float32)
    idx = rng.integers(0, n, size=int(duration * 25))
    crackle[idx] = rng.uniform(-0.25, 0.25, size=len(idx))
    mix += lowpass(crackle, 4000) * 0.5 + rng.standard_normal(n).astype(np.float32) * 0.0025
    return mix[: int(duration * SR)]


def sfx(kind, rng):
    if kind == "key":
        n = int(0.025 * SR); t = np.arange(n) / SR
        noise = rng.standard_normal(n).astype(np.float32)
        click = (noise - lowpass(noise, 2500)) * np.exp(-t / 0.004)
        tone = np.sin(2 * np.pi * rng.uniform(1700, 2300) * t) * np.exp(-t / 0.006)
        return (0.5 * click + 0.25 * tone).astype(np.float32)
    if kind == "send":
        n = int(0.22 * SR); t = np.arange(n) / SR
        f = 500 + 900 * (t / t[-1])
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.005, 0.07)).astype(np.float32)
    if kind == "pop":
        n = int(0.12 * SR); t = np.arange(n) / SR
        f = 1200 * np.exp(-t / 0.03) + 500
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.035)).astype(np.float32)
    if kind == "whoosh":
        n = int(0.6 * SR); t = np.arange(n) / SR
        noise = rng.standard_normal(n).astype(np.float32)
        sweep = lowpass(noise, 1800) * np.sin(np.pi * t / t[-1]) ** 2
        return sweep.astype(np.float32)
    if kind == "ding":
        n = int(0.9 * SR); t = np.arange(n) / SR
        s = np.sin(2 * np.pi * 1318.5 * t) + 0.5 * np.sin(2 * np.pi * 1975.5 * t)
        return (s * env(n, 0.003, 0.25)).astype(np.float32)
    raise ValueError(kind)


SFX_GAIN = {"key": 0.22, "send": 0.25, "pop": 0.28, "whoosh": 0.35, "ding": 0.16}


def make_track(duration, events, seed=0, voice=None):
    rng = np.random.default_rng(seed + 99)
    m = beat(duration, seed)
    fx = np.zeros_like(m)
    for t, kind in events:
        add(fx, t, sfx(kind, rng), SFX_GAIN[kind] * (0.6 if voice is not None else 1.0))
    m = m / (np.max(np.abs(m)) + 1e-9) * 0.42
    if voice is not None:
        v = np.zeros_like(m); n = min(len(v), len(voice)); v[:n] = voice[:n]
        # duck the music under speech (smoothed envelope)
        envv = lowpass(np.abs(v), 6.0)
        envv = envv / (envv.max() + 1e-9)
        m = m * (1 - 0.65 * np.clip(envv * 4, 0, 1))
        mix = 0.85 * v + 0.55 * m + fx
    else:
        mix = m + fx
    # gentle fade out over the last 0.6s (fade-in deliberately absent: the hook must hit at frame 0)
    fo = int(0.6 * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)
    mix = np.tanh(mix * 1.2) / np.tanh(1.2)
    # fake stereo: tiny delay on right channel
    r = np.concatenate([np.zeros(int(0.012 * SR), np.float32), mix])[: len(mix)]
    return np.stack([mix, 0.85 * mix + 0.15 * r], axis=1)


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(data.tobytes())


if __name__ == "__main__":
    import sys
    write_wav(sys.argv[1] if len(sys.argv) > 1 else "/tmp/beat.wav", make_track(16, [(1, "pop")], 0))
