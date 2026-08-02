#!/usr/bin/env python3
"""Generate SUSPENSEFUL, MYSTERY-style ambient music for SKILLOR (US Science).

Optimized for: High-retention mystery/science shorts.
Logic: 100% original synthesis using numpy. No external samples.

Tracks:
  1. brain_tension.wav   (High-frequency neuro-synths + deep heartbeat)
  2. cosmic_mystery.wav  (Spacey drones + shimmering metallic swells)
  3. dark_biology.wav    (Deep organic drones + fast rhythmic pulse)
  4. medical_horror.wav  (Cold hospital ambiance + sharp discordant bells)
  5. deep_secret.wav     (Subtle breathing drone + cinematic tension sweep)

Usage: python scripts/generate_mystery_music.py
"""

import os
import wave
import numpy as np

SR = 44100           # Full quality for US audience
DUR = 60.0           # Seconds (standard Short duration)
OUT_DIR = os.path.join("assets", "music")

def hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)

def _fade_env(n: int, attack_s: float, release_s: float) -> np.ndarray:
    env = np.ones(n)
    a = min(int(SR * attack_s), n // 2)
    r = min(int(SR * release_s), n // 2)
    if a > 0:
        env[:a] = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    if r > 0:
        env[-r:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(r) / r)
    return env

# ═══════════════════════════════════════════════════════════════════════════
# MYSTERY SYNTHESIS
# ═══════════════════════════════════════════════════════════════════════════

def drone_pad(midis, dur: float, gain: float = 0.5, dissonance: float = 0.002) -> np.ndarray:
    """Creates a thick, slightly dissonant mystery drone."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    left, right = np.zeros(n), np.zeros(n)
    
    for m in midis:
        f = hz(m)
        # Multiple oscillators per note for thickness
        for voice in range(4):
            detune = 1.0 + np.random.uniform(-dissonance, dissonance)
            lfo = 1.0 + 0.001 * np.sin(2 * np.pi * np.random.uniform(0.1, 0.5) * t)
            
            phase = 2 * np.pi * f * detune * np.cumsum(lfo) / SR
            # Mix of Sine and soft Triangle for "Mystery" texture
            sig = 0.7 * np.sin(phase) + 0.3 * (np.abs((phase % (2*np.pi)) - np.pi) / np.pi - 0.5)
            
            pan = np.random.uniform(-0.5, 0.5)
            left += sig * (1.0 - pan)
            right += sig * (1.0 + pan)
            
    env = _fade_env(n, 4.0, 5.0)
    return np.stack([left * env, right * env]) * gain / (len(midis) * 4)

def heartbeat_pulse(dur: float, bpm: float = 55, gain: float = 0.3) -> np.ndarray:
    """The 'Subliminal Heartbeat' - essential for US high-tension mystery."""
    n = int(SR * dur)
    out = np.zeros(n)
    period = 60.0 / bpm
    
    for i in range(int(dur / period)):
        t0 = i * period
        # LUB pulse (low, deep)
        p1_start = int(t0 * SR)
        p1_len = int(0.12 * SR)
        if p1_start + p1_len < n:
            t = np.arange(p1_len) / SR
            pulse = np.sin(2 * np.pi * 45 * t) * np.exp(-t / 0.03)
            out[p1_start:p1_start+p1_len] += pulse
            
        # DUB pulse (slightly higher, softer)
        p2_start = int((t0 + 0.18) * SR)
        p2_len = int(0.1 * SR)
        if p2_start + p2_len < n:
            t = np.arange(p2_len) / SR
            pulse = np.sin(2 * np.pi * 52 * t) * 0.6 * np.exp(-t / 0.02)
            out[p2_start:p2_start+p2_len] += pulse
            
    return np.stack([out, out]) * gain

def metallic_shimmer(dur: float, gain: float = 0.1) -> np.ndarray:
    """Eerie metallic swells using filtered high-frequency noise."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = np.random.standard_normal((2, n))
    
    # Very slow resonant filter sweep (simulated)
    swells = 0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t)
    
    # Filter: Keep only highs
    k = np.array([1, -2, 1]) # Basic high pass
    noise[0] = np.convolve(noise[0], k, mode='same')
    noise[1] = np.convolve(noise[1], k, mode='same')
    
    return noise * swells * gain

def mystery_bells(dur: float, midis: list, gain: float = 0.2) -> np.ndarray:
    """Occasional sharp discordant 'Bell' hits for jump-scare focus."""
    n = int(SR * dur)
    left, right = np.zeros(n), np.zeros(n)
    
    num_hits = int(dur / 12)
    for _ in range(num_hits):
        t0 = np.random.uniform(5, dur - 5)
        midi = np.random.choice(midis)
        f = hz(midi)
        
        hit_len = int(SR * 4.0)
        t = np.arange(hit_len) / SR
        # FM Synthesis style bell (inharmonic)
        sig = (np.sin(2*np.pi*f*t) + 
               0.6 * np.sin(2*np.pi*f*2.04*t) + 
               0.4 * np.sin(2*np.pi*f*3.51*t))
        env = np.exp(-t / 0.8)
        
        start = int(t0 * SR)
        end = min(n, start + hit_len)
        chunk = sig[:end-start] * env[:end-start]
        
        pan = np.random.uniform(-0.7, 0.7)
        left[start:end] += chunk * (1.0 - pan)
        right[start:end] += chunk * (1.0 + pan)
        
    return np.stack([left, right]) * gain

# ═══════════════════════════════════════════════════════════════════════════
# TRACK BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def master(sig: np.ndarray, name: str):
    sig = np.tanh(sig * 1.2) # Soft clip
    peak = np.abs(sig).max() or 1.0
    pcm = (sig / peak * 0.8 * 32767).astype(np.int16)
    
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.T.tobytes())
    print(f"  Generated: {path}")

def build_brain_tension():
    """Focus: Neuro-science tension."""
    pads = drone_pad([48, 52, 55], DUR, gain=0.6) # C-E-G minor
    heart = heartbeat_pulse(DUR, bpm=62, gain=0.4)
    shimmer = metallic_shimmer(DUR, gain=0.05)
    master(pads + heart + shimmer, "brain_tension.wav")

def build_cosmic_mystery():
    """Focus: Space/Universe unknowns."""
    pads = drone_pad([40, 47, 52], DUR, gain=0.7) # Low drones
    shimmer = metallic_shimmer(DUR, gain=0.15)
    bells = mystery_bells(DUR, [72, 75, 78], gain=0.3)
    master(pads + shimmer + bells, "cosmic_mystery.wav")

if __name__ == "__main__":
    print("🛸 Generating MYSTERY Science Music for SKILLOR...")
    build_brain_tension()
    build_cosmic_mystery()
    print("\n✅ DONE: Mystery beds ready in assets/music/")
