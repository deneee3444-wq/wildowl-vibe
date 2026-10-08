#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes AI İstemci Modülü (Wild Owl Studio Entegrasyonu)
==============================================================================
Desteklenen Modeller:
  - Video: agnes-video-v2.0 (Kare tabanlı, Image-to-Video ve Keyframe geçişi)
  - Resim: agnes-image-2.5-flash, agnes-image-2.1-flash, agnes-image-2.0-flash
==============================================================================
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import random
import re
import time
from typing import Any, Callable

import requests

API_KEY = os.environ.get("AGNES_API_KEY", "sk-KZhob2kogDQGnUhsOvm3U1254J4BTQ9oRjZrwuRcgtR8vWeA")
API_ROOT = "https://apihub.agnes-ai.com"
BASE_URL = f"{API_ROOT}/v1"

ALLOWED_FRAMES = (81, 121, 161, 241, 361, 441, 481, 721, 961)

VIDEO_PRESETS: dict[str, dict[str, Any]] = {
    "480p":  {"max_frames": 961, "16:9": (832, 448),   "9:16": (448, 832),   "1:1": (512, 512)},
    "720p":  {"max_frames": 481, "16:9": (1280, 704),  "9:16": (704, 1280),  "1:1": (768, 768)},
    "1080p": {"max_frames": 241, "16:9": (1920, 1088), "9:16": (1088, 1920), "1:1": (1088, 1088)},
}

IMAGE_SIZE_PRESETS: dict[str, dict[str, str]] = {
    "1:1":  {"1K": "1024x1024", "2K": "2048x2048", "3K": "3072x3072", "4K": "4096x4096"},
    "16:9": {"1K": "1280x720",  "2K": "1920x1080", "3K": "2560x1440", "4K": "3840x2160"},
    "9:16": {"1K": "720x1280",  "2K": "1080x1920", "3K": "1440x2560", "4K": "2160x3840"},
    "4:3":  {"1K": "1024x768",  "2K": "2048x1536", "3K": "3072x2304", "4K": "4096x3072"},
    "3:4":  {"1K": "768x1024",  "2K": "1536x2048", "3K": "2304x3072", "4K": "3072x4096"},
    "3:2":  {"1K": "1080x720",  "2K": "2160x1440", "3K": "3240x2160", "4K": "4320x2880"},
    "2:3":  {"1K": "720x1080",  "2K": "1440x2160", "3K": "2160x3240", "4K": "2880x4320"},
    "21:9": {"1K": "1344x576",  "2K": "2560x1080", "3K": "3440x1440", "4K": "5040x2160"},
}


class AgnesError(Exception):
    def __init__(self, message: str, status_code: int = 400, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload


def _headers() -> dict[str, str]:
    key = API_KEY or os.environ.get("AGNES_API_KEY", "")
    if not key:
        raise AgnesError("AGNES_API_KEY tanımlı değil.", 500)
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _raise_for_response(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        body = resp.json()
        err = body.get("error", body)
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:
        body, msg = resp.text, resp.text
    hints = {
        403: " (Bu model Pro plan gerektiriyor olabilir.)",
        429: " (Agnes sunucu kapasitesi dolu, tekrar deneniyor...)"
    }
    raise AgnesError(f"{msg}{hints.get(resp.status_code, '')}", resp.status_code, body)


def _request(method: str, path_or_url: str, *, json_body: Any = None,
             timeout: int = 60, max_attempts: int = 5) -> requests.Response:
    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}/{path_or_url.lstrip('/')}"
    last_exc = None

    for attempt in range(max_attempts):
        try:
            resp = requests.request(
                method, url, headers=_headers(), json=json_body, timeout=timeout
            )
        except requests.RequestException as e:
            last_exc = AgnesError(f"Bağlantı hatası: {e}", 502)
            if attempt < max_attempts - 1:
                backoff = min(20.0, 2.0 * (2 ** attempt)) + random.uniform(-0.5, 0.5)
                time.sleep(max(1.0, backoff))
                continue
            raise last_exc from e

        if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts - 1:
            backoff = min(20.0, 2.0 * (2 ** attempt)) + random.uniform(-0.5, 0.5)
            time.sleep(max(1.0, backoff))
            continue

        _raise_for_response(resp)
        return resp

    raise last_exc or AgnesError("İstek başarısız oldu.", 500)


def to_image_ref(src: str | bytes) -> str:
    if isinstance(src, (bytes, bytearray)):
        return _bytes_to_data_uri(bytes(src), "image/jpeg")

    s = src.strip().strip("'\"")
    if not s:
        raise AgnesError("Boş görsel girdisi.")
    if s.startswith(("http://", "https://", "data:")):
        return s
    if not os.path.isfile(s):
        raise AgnesError(f"Görsel dosyası bulunamadı: {s}")
    with open(s, "rb") as f:
        data = f.read()
    return _bytes_to_data_uri(data, mimetypes.guess_type(s)[0] or "image/jpeg")


def _bytes_to_data_uri(data: bytes, fallback_mime: str) -> str:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return f"data:{fallback_mime};base64," + base64.b64encode(data).decode()


def expand_video_prompt(prompt: str) -> str:
    """Agnes 2.0 Flash kullanarak video promptunu sinematik İngilizceye genişletir."""
    if not prompt or len(prompt.strip()) < 3:
        return prompt
    try:
        sys_msg = (
            "You are an expert cinematic director. Expand the user's short video idea into a detailed, "
            "vivid, high-quality cinematic video generation prompt in English. Follow the structure: "
            "[Subject] + [Action] + [Scene Environment] + [Camera Movement & Angle] + [Lighting] + [Atmosphere & Style]. "
            "Respond ONLY with the expanded prompt text, without explanations or quotes."
        )
        payload = {
            "model": "agnes-2.0-flash",
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        res = _request("POST", "/chat/completions", json_body=payload, timeout=30).json()
        choices = res.get("choices") or []
        if choices:
            expanded = choices[0].get("message", {}).get("content", "").strip()
            if expanded:
                return expanded
    except Exception:
        pass
    return prompt


def expand_image_prompt(prompt: str) -> str:
    """Agnes 2.0 Flash kullanarak resim promptunu detaylı İngilizceye genişletir."""
    if not prompt or len(prompt.strip()) < 3:
        return prompt
    try:
        sys_msg = (
            "You are an expert digital artist and visual designer. Expand the user's short prompt into a detailed, "
            "vivid, high-quality image generation prompt in English. Include subject details, lighting, mood, artistic style, "
            "and texture. Respond ONLY with the expanded prompt text, without explanations or quotes."
        )
        payload = {
            "model": "agnes-2.0-flash",
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        res = _request("POST", "/chat/completions", json_body=payload, timeout=30).json()
        choices = res.get("choices") or []
        if choices:
            expanded = choices[0].get("message", {}).get("content", "").strip()
            if expanded:
                return expanded
    except Exception:
        pass
    return prompt


def snap_frames(target: int, max_frames: int = 961) -> int:
    valid = [f for f in ALLOWED_FRAMES if f <= max_frames]
    if not valid:
        return ALLOWED_FRAMES[0]
    return min(valid, key=lambda f: abs(f - target))


def resolve_video_spec(resolution: str = "720p", aspect_ratio: str = "16:9",
                       seconds: float = 5.0, fps: int = 24) -> dict:
    preset = VIDEO_PRESETS.get(resolution)
    if not preset or aspect_ratio not in preset:
        preset = VIDEO_PRESETS["720p"]
        aspect_ratio = "16:9"

    width, height = preset[aspect_ratio]
    max_frames = preset["max_frames"]
    target = round(seconds * fps)
    frames = snap_frames(target, max_frames=max_frames)

    return {
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "num_frames": frames,
        "frame_rate": fps,
        "max_frames": max_frames,
        "seconds": round(frames / fps, 1)
    }


_STATUS_MAP = {
    "queued": "queued", "pending": "queued",
    "inference": "in_progress", "in_progress": "in_progress", "processing": "in_progress",
    "completed": "completed", "succeeded": "completed", "success": "completed", "done": "completed",
    "failed": "failed", "error": "failed", "cancelled": "failed",
}


def _normalize_status(d: dict) -> dict:
    raw = str(d.get("internal_status") or d.get("status") or "unknown").lower()
    progress = d.get("internal_progress")
    if progress is None:
        progress = d.get("progress") or 0

    url = (d.get("video_url") or d.get("url")
           or d.get("remixed_from_video_id")
           or (d.get("output") or {}).get("url") or (d.get("data") or {}).get("url"))

    status = _STATUS_MAP.get(raw, "in_progress")
    if status == "completed":
        progress = 100

    err = d.get("error")
    if isinstance(err, dict):
        err = err.get("message", str(err))

    return {
        "status": status,
        "raw_status": raw,
        "progress": progress,
        "url": url,
        "error": err if status == "failed" else None
    }


def get_video_status(task_id: str | None, video_id: str | None, model: str = "agnes-video-v2.0") -> dict:
    live = None
    if video_id:
        try:
            live = _normalize_status(_request(
                "GET", f"{API_ROOT}/agnesapi?video_id={video_id}&model_name={model}", timeout=10).json())
        except Exception:
            live = None

    if task_id and (live is None or (live["status"] == "completed" and not live["url"]) or live["status"] == "unknown"):
        try:
            fallback = _normalize_status(_request("GET", f"/videos/{task_id}", timeout=15).json())
            if live is None or fallback["url"] or fallback["status"] in ("completed", "failed"):
                live = fallback
        except Exception:
            pass

    return live or {"status": "unknown", "raw_status": "unreachable", "progress": 0, "url": None, "error": None}


def wait_for_video(task_id: str | None, video_id: str | None, model: str = "agnes-video-v2.0",
                   poll_interval: int = 4, max_wait: int = 600,
                   log_callback: Callable[[str, str, int], None] | None = None) -> dict:
    start = time.time()
    last_prog = -1

    while time.time() - start < max_wait:
        st = get_video_status(task_id, video_id, model)
        prog = int(st.get("progress") or 0)
        status_name = st.get("status")

        if prog != last_prog and log_callback:
            last_prog = prog
            mapped_pct = int(15 + (prog * 0.8))  # 15% -> 95%
            log_callback(f"Agnes v2.0 çıkarım yapılıyor (%{prog})...", "rendering", mapped_pct)

        if status_name == "failed":
            raise AgnesError(f"Agnes video üretimi başarısız: {st.get('error') or 'Bilinmeyen hata'}")
        if status_name == "completed" and st.get("url"):
            return st

        time.sleep(poll_interval)

    raise AgnesError(f"Video üretimi zaman aşımına uğradı ({max_wait} sn).")


def run_video(
    prompt: str,
    images: list[str | bytes] | None = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "720p",
    fps: int = 24,
    enable_prompt_expansion: bool = False,
    negative_prompt: str = "",
    seed: int | str | None = None,
    log_callback: Callable[[str, str, int], None] | None = None
) -> dict:
    """
    Agnes Video v2.0 Üretim Fonksiyonu.
    - images: 0 adet ise Text-to-Video
              1 adet ise Image-to-Video (start_image)
              2 adet ise Keyframe Geçişi (start_image + end_image)
    """
    if log_callback:
        log_callback("Agnes Video v2.0 parametreleri hazırlanıyor...", "registering", 5)

    final_prompt = prompt.strip()
    if enable_prompt_expansion:
        if log_callback:
            log_callback("Agnes 2.0 Flash ile sinematik prompt genişletiliyor...", "registering", 10)
        final_prompt = expand_video_prompt(final_prompt)

    # Süre (saniye) hesaplama: "3", "5", "8", "10", "15", "20", "30", "40"
    try:
        sec_val = float(duration)
    except Exception:
        sec_val = 5.0

    spec = resolve_video_spec(
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        seconds=sec_val,
        fps=int(fps) if fps else 24
    )

    payload: dict[str, Any] = {
        "model": "agnes-video-v2.0",
        "prompt": final_prompt,
        "width": spec["width"],
        "height": spec["height"],
        "num_frames": spec["num_frames"],
        "frame_rate": spec["frame_rate"]
    }

    # Görsel / Keyframe yönetimi
    valid_images = [img for img in (images or []) if img]
    if len(valid_images) >= 2:
        if log_callback:
            log_callback("Keyframe geçiş modu yapılandırılıyor (2 görsel)...", "registering", 12)
        start_ref = to_image_ref(valid_images[0])
        end_ref = to_image_ref(valid_images[1])
        payload["extra_body"] = {"image": [start_ref, end_ref], "mode": "keyframes"}
    elif len(valid_images) == 1:
        if log_callback:
            log_callback("Image-to-Video modu yapılandırılıyor...", "registering", 12)
        payload["image"] = to_image_ref(valid_images[0])

    if negative_prompt and negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()

    if seed is not None and str(seed).strip() != "":
        try:
            payload["seed"] = int(seed)
        except Exception:
            pass

    if log_callback:
        log_callback(f"Agnes v2.0 görev gönderiliyor ({spec['width']}x{spec['height']}, {spec['num_frames']} kare)...", "registering", 15)

    resp_data = _request("POST", "/videos", json_body=payload, timeout=60).json()
    task_id = resp_data.get("id") or resp_data.get("task_id")
    video_id = resp_data.get("video_id")

    if not task_id and not video_id:
        raise AgnesError("Agnes API görev kimliği (task_id) döndürmedi.", 502, resp_data)

    if log_callback:
        log_callback("Agnes işlem sırasına alındı, ilerleme takip ediliyor...", "rendering", 20)

    final_status = wait_for_video(task_id, video_id, model="agnes-video-v2.0", poll_interval=4, log_callback=log_callback)
    output_url = final_status.get("url")

    if not output_url:
        raise AgnesError("Agnes üretimi tamamlandı ancak video URL'si alınamadı.")

    if log_callback:
        log_callback("Video üretimi başarıyla tamamlandı!", "completed", 100)

    return {
        "output": output_url,
        "task_id": task_id,
        "video_id": video_id,
        "spec": spec
    }


def run_image(
    prompt: str,
    model: str = "agnes-image-2.5-flash",
    aspect_ratio: str = "1:1",
    resolution: str = "2K",
    negative_prompt: str = "",
    seed: int | str | None = None,
    images: list[str | bytes] | None = None,
    strength: float = 0.75,
    enable_prompt_expansion: bool = False,
    log_callback: Callable[[str, str, int], None] | None = None
) -> dict:
    """
    Agnes Image Üretim Fonksiyonu.
    - model: agnes-image-2.5-flash, agnes-image-2.1-flash, agnes-image-2.0-flash
    - resolution: 1K, 2K, 3K, 4K
    - aspect_ratio: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9
    """
    if log_callback:
        log_callback(f"Agnes Resim motoru ({model}) hazırlanıyor...", "registering", 10)

    final_prompt = prompt.strip()
    if enable_prompt_expansion:
        if log_callback:
            log_callback("Agnes 2.0 Flash ile prompt genişletiliyor...", "registering", 15)
        final_prompt = expand_image_prompt(final_prompt)

    payload: dict[str, Any] = {
        "model": model,
        "prompt": final_prompt,
        "size": resolution.upper() if resolution else "2K",
        "ratio": aspect_ratio or "1:1",
        "extra_body": {"response_format": "url"}
    }

    if negative_prompt and negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()
        payload["extra_body"]["negative_prompt"] = negative_prompt.strip()

    if seed is not None and str(seed).strip() != "":
        try:
            s_val = int(seed)
            if 0 <= s_val:
                payload["seed"] = s_val
                payload["extra_body"]["seed"] = s_val
        except Exception:
            pass

    valid_refs = [to_image_ref(img) for img in (images or []) if img]
    if valid_refs:
        if len(valid_refs) > 6:
            valid_refs = valid_refs[:6]
        payload["image"] = valid_refs
        payload["extra_body"]["image"] = valid_refs
        payload["strength"] = max(0.1, min(1.0, float(strength or 0.75)))
        payload["extra_body"]["strength"] = max(0.1, min(1.0, float(strength or 0.75)))
        if log_callback:
            log_callback(f"{len(valid_refs)} referans görsel dahil ediliyor...", "registering", 20)

    if log_callback:
        log_callback("Agnes Resim API'sine istek gönderiliyor...", "rendering", 40)

    data = _request("POST", "/images/generations", json_body=payload, timeout=180).json()
    image_list = data.get("data") or []
    if not image_list or not image_list[0].get("url"):
        raise AgnesError("Agnes Resim API'si geçerli bir görsel URL'si döndürmedi.", 502, data)

    output_url = image_list[0]["url"]

    if log_callback:
        log_callback("Görsel başarıyla oluşturuldu!", "completed", 100)

    return {"output": output_url}
