"""Shared audio/voice utilities for speaker-identification scripts.

Requires numpy; librosa and resemblyzer are imported lazily at call time.
"""
import pathlib, sys

import numpy as np

from utils import name_from_slug

SAMPLING_RATE = 16_000


def download_mp3(url: str, dest: pathlib.Path) -> None:
    try:
        import httpx as _http
        client_cls = _http.Client
        timeout = _http.Timeout(60, read=7200)
    except ImportError:
        import requests as _http  # type: ignore
        client_cls = None
        timeout = (60, 7200)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f'  Downloading {url} …')
    if client_cls:
        with client_cls(timeout=timeout) as client:
            resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    else:
        resp = _http.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
    print(f'  Saved {dest.stat().st_size // 1_000_000} MB')


def load_audio(mp3_path: pathlib.Path, sampling_rate: int = SAMPLING_RATE) -> np.ndarray:
    try:
        import librosa
    except ImportError:
        sys.exit('librosa not found. Install resemblyzer: pip install resemblyzer')
    audio, _ = librosa.load(str(mp3_path), sr=sampling_rate, mono=True)
    return audio.astype(np.float32)


def load_profiles(profiles_dir: pathlib.Path) -> dict[str, np.ndarray]:
    """Return {speaker_name: embedding} for all stored .npy profiles."""
    profiles: dict[str, np.ndarray] = {}
    if not profiles_dir.exists():
        return profiles
    for path in sorted(profiles_dir.glob('*.npy')):
        profiles[name_from_slug(path.stem)] = np.load(path).astype(np.float32)
    return profiles


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def embed_cluster(
    audio: np.ndarray,
    segs: list[dict],
    encoder,
    preprocess_wav,
    min_seg_secs: float = 1.0,
    sampling_rate: int = SAMPLING_RATE,
    max_segs: int | None = None,
) -> np.ndarray | None:
    """Return normalised mean Resemblyzer embedding for a speaker cluster."""
    segs = [s for s in segs if (s['end'] - s['start']) >= min_seg_secs]
    if not segs:
        return None
    if max_segs is not None:
        segs.sort(key=lambda s: s['end'] - s['start'], reverse=True)
        segs = segs[:max_segs]
    embeddings = []
    for seg in segs:
        start_i = int(seg['start'] * sampling_rate)
        end_i = int(seg['end'] * sampling_rate)
        clip = audio[start_i:end_i]
        if len(clip) < sampling_rate:
            continue
        try:
            wav = preprocess_wav(clip, source_sr=sampling_rate)
            embeddings.append(encoder.embed_utterance(wav))
        except Exception:
            pass
    if not embeddings:
        return None
    emb = np.mean(embeddings, axis=0).astype(np.float32)
    return emb / np.linalg.norm(emb)
