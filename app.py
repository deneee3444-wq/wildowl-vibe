import os
import re
import sys
import uuid
import json
import time
import string
import random
import io
import requests
import threading
import queue
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for

# Ensure parent root directory is in sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# --- OPSİYONEL IMPORTLAR ---
try:
    import vibeVideo
except ImportError:
    vibeVideo = None

try:
    import popVidAI
except ImportError:
    popVidAI = None

try:
    import topVidAI
except ImportError:
    topVidAI = None

try:
    import pixelBunnyAI
except ImportError:
    pixelBunnyAI = None

try:
    import morphStudioAI
except ImportError:
    morphStudioAI = None

try:
    import agnesAI
except ImportError:
    agnesAI = None

try:
    import deApiAI
except ImportError:
    deApiAI = None

# --- wildOwlAI OPSİYONEL IMPORT ---
# Bu dosya repo'da yok, fallback config kullan
try:
    from wildOwlAI import SupabaseSignup as _WO
    eTemp = _WO
except ImportError:
    _WO = None
    eTemp = None

# --- MODELS CONFIG ---
MODELS_CONFIG = {
    "MiniMax M3 Video": {
        "model_id": "MiniMaxH3_33B_Turbo_INT8",
        "model_slug": "MiniMaxH3_33B_Turbo_INT8",
        "type": "video",
        "provider": "deapi",
        "tiers": ["5", "10"],
        "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "resolutions": ["768p", "720p"],
        "resolution": "768p",
        "extra_settings": {
            "fps": 24,
            "enable_prompt_expansion": False,
            "negative_prompt": "",
            "seed": ""
        }
    },
    "LTX 2.5 Video": {
        "model_id": "Ltx2_5_22B_Dist_INT8",
        "model_slug": "Ltx2_5_22B_Dist_INT8",
        "type": "video",
        "provider": "deapi",
        "tiers": ["5", "10"],
        "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "resolutions": ["768p", "720p"],
        "resolution": "768p",
        "extra_settings": {
            "fps": 24,
            "enable_prompt_expansion": False,
            "negative_prompt": "",
            "seed": ""
        }
    },
    "Vibe Video": {
        "model_id": "vibe-video",
        "type": "video",
        "tiers": ["standard"],
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolution": "720p"
    },
    "Pop Vid": {
        "model_id": "pop-vid",
        "type": "video",
        "tiers": ["standard"],
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolution": "720p"
    },
    "Wan 2.6 Video": {
        "model_id": "wan-2.6-video",
        "type": "video",
        "tiers": ["5", "10", "15"],
        "tier_labels": {"5": "5 Saniye", "10": "10 Saniye", "15": "15 Saniye"},
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "resolutions": ["720p", "1080p"],
        "resolution": "720p",
        "extra_settings": {
            "enable_safety_checker": False,
            "enable_prompt_expansion": False,
            "multi_shots": False,
            "camerafixed": False,
            "loop": False,
            "auto_fix": False,
            "generate_audio": True,
            "audio_url": "",
            "negative_prompt": "",
            "movement_amplitude": "auto",
            "movement_amplitudes": ["auto", "small", "medium", "large"],
            "movement_amplitude_labels": {
                "auto": "Otomatik",
                "small": "Düşük",
                "medium": "Orta",
                "large": "Yüksek"
            }
        }
    },
    "Agnes Video 2.0": {
        "model_id": "agnes-video-v2.0",
        "type": "video",
        "provider": "agnes",
        "tiers": ["3", "5", "8", "10", "15", "20", "30", "40"],
        "tier_labels": {
            "3": "3 Saniye", "5": "5 Saniye", "8": "8 Saniye",
            "10": "10 Saniye", "15": "15 Saniye", "20": "20 Saniye",
            "30": "30 Saniye", "40": "40 Saniye"
        },
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "resolution": "720p",
        "extra_settings": {
            "fps": 24,
            "fps_options": [24, 30, 60],
            "fps_labels": {
                "24": "24 FPS (Sinema)",
                "30": "30 FPS (Akıcı)",
                "60": "60 FPS (Ultra)"
            },
            "enable_prompt_expansion": False,
            "negative_prompt": "",
            "seed": ""
        }
    },
    "Seedance 1.0 Pro Fast": {
        "model_id": "seedance_v1_pro_fast",
        "type": "video",
        "provider": "morph",
        "tiers": ["5", "10"],
        "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "resolution": "480p"
    },
    "Nano Banana 2.1": {
        "model_id": "google/nano-banana-2.1",
        "type": "image",
        "provider": "morph",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1"],
        "resolutions": ["1k", "2k", "4k"],
        "resolution": "1k"
    },
    "GPT Image 2.5 (Sunburst)": {
        "model_id": "openai/gpt-image-2.5",
        "type": "image",
        "provider": "morph",
        "mode": "sunburst",
        "tiers": ["low", "medium", "high", "xhigh"],
        "tier_labels": {"low": "Low Kalite", "medium": "Medium Kalite", "high": "High Kalite", "xhigh": "Xhigh Kalite"},
        "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "2:1", "1:2", "3:1", "1:3"],
        "resolutions": ["1k", "2k", "4k"],
        "resolution": "2k"
    },
    "GPT Image 2.5 (Flare)": {
        "model_id": "openai/gpt-image-2.5",
        "type": "image",
        "provider": "morph",
        "mode": "flare",
        "tiers": ["low", "medium", "high", "xhigh"],
        "tier_labels": {"low": "Low Kalite", "medium": "Medium Kalite", "high": "High Kalite", "xhigh": "Xhigh Kalite"},
        "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "2:1", "1:2", "3:1", "1:3"],
        "resolutions": ["1k", "2k", "4k"],
        "resolution": "2k"
    },
    "Wan 2.7": {
        "model_id": "wan-2.7-image",
        "tiers": ["standard", "pro"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "1K"
    },
    "Seedream 5 Pro": {
        "model_id": "seedream-5-pro",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
        "resolution": "1K"
    },
    "Seedream 5 Lite": {
        "model_id": "seedream-5-lite",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "3K"
    },
    "Grok Imagine": {
        "model_id": "grok-image",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "2:1", "20:9", "19.5:9", "4:3", "3:2", "2:3", "3:4", "9:19.5", "9:20", "1:2"],
        "resolution": "HD"
    },
    "Flux 2": {
        "model_id": "flux-2",
        "tiers": ["low", "medium", "high"],
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        "resolution": "1K"
    },
    "GPT Image 2": {
        "model_id": "gpt-image-2",
        "tiers": ["low", "medium", "high"],
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        "resolution": "1K"
    },
    "GPT Image 1.5": {
        "model_id": "gpt-image-1.5",
        "tiers": ["low", "medium", "high"],
        "aspect_ratios": ["1:1", "3:2", "2:3"],
        "resolution": "1K"
    },
    "Qwen 2.1": {
        "model_id": "qwen-2.1",
        "tiers": ["standard", "pro", "turbo"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "resolutions": ["1K", "2K"],
        "resolution": "1K"
    },
    "Qwen Image 2": {
        "model_id": "qwen-image-2",
        "tiers": ["standard", "pro"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "HD"
    },
    "Qwen Image 3": {
        "model_id": "qwen-image-3",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "resolution": "1K"
    },
    "Wan 2.6": {
        "model_id": "wan-2.6-image",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "1K"
    },
    "Z-Image Turbo": {
        "model_id": "z-image-turbo",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "HD"
    },
    "Agnes Image 2.5 Flash": {
        "model_id": "agnes-image-2.5-flash",
        "type": "image",
        "provider": "agnes",
        "tiers": ["standard"],
        "aspect_ratios": ["1:1", "16:9", "9:16"],
        "resolution": "1K"
    }
}

# --- THREAD-SAFE GÖREV KUYRUĞU ---
# Ağır işlemler (video üretimi, browser işlemleri) bu kuyruğa girer
task_queue = queue.Queue()
task_results = {}
task_lock = threading.Lock()

# Aktif görev sayacı (aynı anda sadece 1 ağır işlem)
active_tasks = {"count": 0, "max": 1}
active_lock = threading.Lock()


def run_heavy_task(task_id, func, *args, **kwargs):
    """Ağır işlemleri sırayla çalıştırır. Aynı anda sadece 1 görev."""
    with active_lock:
        active_tasks["count"] += 1

    try:
        result = func(*args, **kwargs)
        with task_lock:
            task_results[task_id] = {"status": "done", "result": result}
    except Exception as e:
        with task_lock:
            task_results[task_id] = {"status": "error", "error": str(e)}
    finally:
        with active_lock:
            active_tasks["count"] -= 1


def task_worker():
    """Arka plan thread'i: Kuyruktan görev alıp sırayla çalıştırır."""
    while True:
        try:
            task_id, func, args, kwargs = task_queue.get(timeout=5)
            run_heavy_task(task_id, func, *args, **kwargs)
            task_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[TASK WORKER ERROR] {e}")


# Arka plan worker thread'i başlat
worker_thread = threading.Thread(target=task_worker, daemon=True)
worker_thread.start()


# --- FLASK APP ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wildowl-secret-key-change-me")


@app.route("/")
def index():
    return render_template("index.html", models=MODELS_CONFIG)


@app.route("/api/models")
def get_models():
    return jsonify(MODELS_CONFIG)


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    model_name = data.get("model", "")
    prompt = data.get("prompt", "")
    tier = data.get("tier", "standard")

    if not model_name or model_name not in MODELS_CONFIG:
        return jsonify({"error": "Invalid model"}), 400

    # Görev ID oluştur
    task_id = str(uuid.uuid4())

    # Model provider'a göre doğru modülü çağır
    model_cfg = MODELS_CONFIG[model_name]
    provider = model_cfg.get("provider", "")

    def _run():
        if provider == "deapi" and deApiAI:
            return deApiAI.run_once(prompt=prompt, model=model_cfg["model_id"], tier=tier)
        elif provider == "agnes" and agnesAI:
            return agnesAI.run_once(prompt=prompt, model=model_cfg["model_id"], tier=tier)
        elif provider == "morph" and morphStudioAI:
            return morphStudioAI.run_once(prompt=prompt, model=model_cfg["model_id"], tier=tier)
        elif model_cfg.get("model_id") == "vibe-video" and vibeVideo:
            return vibeVideo.run_once(prompt=prompt)
        elif model_cfg.get("model_id") == "pop-vid" and popVidAI:
            return popVidAI.run_once(prompt=prompt)
        elif model_cfg.get("model_id") == "wan-2.6-video" and topVidAI:
            return topVidAI.run_once(prompt=prompt)
        else:
            return {"error": f"No handler for model {model_name}"}

    # Kuyruğa ekle
    task_queue.put((task_id, _run, (), {}))

    return jsonify({
        "task_id": task_id,
        "status": "queued",
        "message": "Görev kuyruğa alındı"
    })


@app.route("/api/task/<task_id>")
def get_task(task_id):
    with task_lock:
        if task_id in task_results:
            result = task_results[task_id]
            # Temizlik: Sonucu okuduktan sonra sil (bellek tasarrufu)
            del task_results[task_id]
            return jsonify(result)
    return jsonify({"status": "processing"})


@app.route("/api/status")
def status():
    with active_lock:
        return jsonify({
            "active_tasks": active_tasks["count"],
            "queue_size": task_queue.qsize()
        })


# --- SAĞLIK KONTROLÜ ---
@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
