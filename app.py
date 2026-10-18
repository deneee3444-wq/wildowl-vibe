#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
🎬 deAPI AI Video İstemci Modülü & Otomatik Hesap Havuzu (deAPI.ai) 🎬
================================================================================
deAPI VİDEO KURALLARI & NORMALİZASYON DEĞERLERİ (ÖZET REFERANS):
--------------------------------------------------------------------------------
1. FPS Kuralı:
   - Kesinlikle ve sadece 24 FPS zorunludur (MiniMax & LTX 2.5).
   - 5 Saniye: MiniMax = 124 kare, LTX 2.5 = 120 kare.
   - 10 Saniye: MiniMax = 243 kare, LTX 2.5 = 241 kare.

2. Çözünürlük ve Boyut Sınırları:
   - Maksimum kenar: 1344 px.
   - Maksimum piksel alanı: 1344 x 768 = 1.032.192 px (bu alanı aşamaz).
   - Normalizasyon Değerleri (768p Standart):
     * 16:9 -> 1344 x 768 (veya 1024 x 576)
     * 9:16 -> 768 x 1344 (veya 576 x 1024)
     * 1:1  -> 768 x 768
     * 4:3  -> 1024 x 768
     * 3:4  -> 768 x 1024
     * 21:9 -> 1344 x 576

3. Model Limitleri & RPD (Requests Per Day):
   - Hız Sınırı: Her iki modelde de 1 RPM (dakikada 1 istek).
   - MiniMax M3: RPD = 3 (Hesap başına günlük 3 video).
   - LTX 2.5:    RPD = 15 (Hesap başına günlük 15 video), payload'da steps: 1 zorunludur.

4. Medya Referans Kuralları:
   - MiniMax M3: En fazla 3 referans medya (görsel + video + ses <= 3).
     * Görsel maks 3 (ref_images[0..2]), Video maks 1 (ref_videos[0]), Ses maks 1 (ref_audios[0]).
     * Ses referansı tek başına verilemez (yanında en az 1 görsel veya video şart).
   - LTX 2.5: Sadece Start veya Start+End Keyframe kabul eder. Harici ses veya video referansı almaz.
   - Keyframe modu (first_frame_image / last_frame_image) ile Full-Reference modu birbirini dışlar.
================================================================================

RENDER 512MB OOM FİKSİ (v2):
--------------------------------------------------------------------------------
Eski sürümde tarayıcı her Cloudflare yenilemesinde AÇILIP KAPATILIYORDU.
Chromium cold-start anı ~300+ MB RAM spike üretir; aç-kapat döngüsü ve
arka arkaya gelen açılışlar Render free (512MB) limitini aşıp OOM kill ->
container restart -> "refresh atıp çökme" sorununa yol açıyordu.

Yeni yapı: browser_manager.py içindeki kalıcı BrowserManager, tarayıcıyı
TEK bir arka plan thread'inde sürekli açık tutar ve tüm işleri kuyrukla
seri olarak yapar. RAM sabit kalır, thread çakışması ve SingletonLock
problemi tamamen ortadan kalkar.
================================================================================
"""

import os
import re
import sys
import time
import json
import html
import random
import secrets
import string
import mimetypes
import math
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from contextlib import ExitStack

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

# Kalıcı tarayıcı yöneticisi (tek thread, açık tutulan tek Chromium)
from browser_manager import BROWSER_MANAGER

def _ensure_browser_binary():
    """
    CloakBrowser Chromium binary'si Docker build anında (Dockerfile) indirilir.
    Runtime sırasında GitHub API 403 Rate Limit hatası alıp servisin kapanmasını
    önlemek için burada ağ sorgusu yapılmaz.
    """
    pass

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "browser_profile_deapi")
BASE_URL = "https://api.deapi.ai/api/v2"

# Model Eşlemeleri
MODEL_SLUGS = {
    "MiniMax M3 Video": "MiniMaxH3_33B_Turbo_INT8",
    "MiniMax M3": "MiniMaxH3_33B_Turbo_INT8",
    "MiniMaxH3_33B_Turbo_INT8": "MiniMaxH3_33B_Turbo_INT8",
    "LTX 2.5 Video": "Ltx2_5_22B_Dist_INT8",
    "LTX 2.5": "Ltx2_5_22B_Dist_INT8",
    "Ltx2_5_22B_Dist_INT8": "Ltx2_5_22B_Dist_INT8"
}

# Çözünürlük Normalizasyon Değerleri (Maksimum 1344x768, 1.032.192 maks piksel alanı)
RESOLUTION_TABLE = {
    "16:9": {"width": 1344, "height": 768},
    "9:16": {"width": 768, "height": 1344},
    "1:1":  {"width": 768, "height": 768},
    "4:3":  {"width": 1024, "height": 768},
    "3:4":  {"width": 768, "height": 1024},
    "21:9": {"width": 1344, "height": 576}
}

# 720p / Düşük çözünürlük alternatifleri
RESOLUTION_TABLE_720P = {
    "16:9": {"width": 1024, "height": 576},
    "9:16": {"width": 576, "height": 1024},
    "1:1":  {"width": 768, "height": 768},
    "4:3":  {"width": 1024, "height": 768},
    "3:4":  {"width": 768, "height": 1024},
    "21:9": {"width": 1344, "height": 576}
}

# Cloudflare Turnstile Çerez & UA Önbelleği (Cookie bayatlamadıysa tarayıcıya gidilmez)
_CACHED_CF_SESSION: Dict[str, Any] = {
    "cookies": None,
    "ua": None,
    "created_at": 0
}

_ACCOUNT_CREATION_LOCK = threading.Lock()

# ==============================================================================
# PROXY AYARI (RENDER VB. SUNUCULARDA CLOUDFLARE 403 ENGELİNİ AŞMAK İÇİN)
# ------------------------------------------------------------------------------
# PROXY_MODE: 0 -> Kapalı (Lokal testlerde proxy kullanmaz)
#             1 -> Açık   (Render.com vb. sunucularda Cloudflare Turnstile & 403 aşımı için)
PROXY_MODE = int(os.environ.get("PROXY_MODE", "1"))
CLOAK_PROXY_URL = os.environ.get("PROXY", "http://tghpxuwn:dxrsnpsyz3df@45.38.107.97:6014")


# ==============================================================================
# 1. CLOAKBROWSER CLOUDFLARE CLEARANCE & YENİ HESAP AÇMA MOTORU
# ==============================================================================

def _random_box(length=10):
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def _random_name():
    first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
    return f"{secrets.choice(first_names)} {secrets.choice(last_names)}"

def _random_password():
    chars = string.ascii_letters + string.digits
    return "DeApi#" + "".join(secrets.choice(chars) for _ in range(8)) + "1"

def _get_cf_session_via_browser(log_callback: Optional[Callable[[str, str, int], None]] = None) -> Tuple[Dict[str, str], str, str]:
    """
    Kalıcı BrowserManager üzerinden Cloudflare Turnstile çözümü alır.
    Tarayıcı AÇILIP KAPATILMAZ; arka planda zaten açık olan tek Chromium
    instance'ına kuyruk üzerinden sıralı görev atılır. Bu sayede:
      - RAM spike yok (OOM / Render restart çözülür)
      - Playwright sync API her zaman tek thread'den çağrılır (thread-safe)
      - Profil SingletonLock çakışması yaşanmaz
    """
    if log_callback:
        log_callback("Cloudflare Turnstile doğrulaması arka plan tarayıcısında çözülüyor...", "registering", 12)
    print("[*] Cloudflare Turnstile için kalıcı tarayıcıya görev atılıyor...", flush=True)

    session_data = BROWSER_MANAGER.get_fresh_session()

    if log_callback:
        log_callback("Turnstile geçildi. İşlemler hızlı HTTP ile devam ediyor...", "registering", 18)
    print("[+] Turnstile oturumu kalıcı tarayıcıdan alındı.", flush=True)

    return session_data["cookies"], session_data["user_agent"], session_data["html"]

def _get_or_refresh_cf_session(log_callback: Optional[Callable[[str, str, int], None]] = None) -> Tuple[Dict[str, str], str, str]:
    """
    Eğer bellekteki cf_clearance çerezleri hala geçerliyse doğrudan HTTP ile register HTML'ini alır.
    Tarayıcıya YALNIZCA çerez yoksa veya bayatladıysa (403 / challenge) gidilir!
    """
    cached_cookies = _CACHED_CF_SESSION.get("cookies")
    cached_ua = _CACHED_CF_SESSION.get("ua")

    if cached_cookies and cached_ua:
        try:
            if log_callback:
                log_callback("Mevcut Cloudflare çerezi test ediliyor...", "registering", 11)
            test_session = cffi_requests.Session(impersonate="chrome120")
            if PROXY_MODE == 1 and CLOAK_PROXY_URL and CLOAK_PROXY_URL.strip().lower() not in ["none", "direct", "no", "off", ""]:
                test_session.proxies = {"http": CLOAK_PROXY_URL.strip(), "https": CLOAK_PROXY_URL.strip()}
            test_session.cookies.update(cached_cookies)
            test_session.headers.update({
                "user-agent": cached_ua,
                "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            })
            resp = test_session.get("https://app.deapi.ai/register", timeout=15)
            if resp.status_code == 200 and "wire:snapshot" in resp.text:
                if log_callback:
                    log_callback("Cloudflare çerezi hala taze! Tarayıcıya hiç dokunmadan hızlı HTTP ile hesap açılıyor...", "registering", 15)
                print("[+] Cloudflare çerezi hala geçerli, tarayıcı KULLANILMADAN doğrudan devam ediliyor.", flush=True)
                return cached_cookies, cached_ua, resp.text
            else:
                print(f"[*] Cloudflare çerezi bayatlamış (HTTP {resp.status_code}), Turnstile tazelenecek.", flush=True)
        except Exception as e:
            print(f"[!] Çerez test hatası: {e}, Turnstile tazelenecek.", flush=True)

    # Çerez yok veya bayatlamış -> kalıcı tarayıcıdan Turnstile çöz
    if log_callback:
        log_callback("Cloudflare çerezi tazeleniyor (arka plan tarayıcısı)...", "registering", 12)
    cookies, ua, page_html = _get_cf_session_via_browser(log_callback)
    _CACHED_CF_SESSION["cookies"] = cookies
    _CACHED_CF_SESSION["ua"] = ua
    _CACHED_CF_SESSION["created_at"] = time.time()
    return cookies, ua, page_html

def _create_new_deapi_account(log_callback: Optional[Callable[[str, str, int], None]] = None) -> str:
    """
    Tarayıcıdan alınan çerezlerle arka planda otomatik geçici e-posta alır,
    kaydı tamamlar, e-postayı onaylar ve $5 bakiyeli yeni API anahtarı üretir.
    Çerez taze ise tarayıcıya hiç gidilmez!
    """
    cookies, ua, register_html = _get_or_refresh_cf_session(log_callback)

    if log_callback:
        log_callback("Geçici e-posta kutusu oluşturuluyor ve kayıt formu iletiliyor...", "registering", 20)

    session = cffi_requests.Session(impersonate="chrome120")
    if PROXY_MODE == 1 and CLOAK_PROXY_URL and CLOAK_PROXY_URL.strip().lower() not in ["none", "direct", "no", "off", ""]:
        session.proxies = {"http": CLOAK_PROXY_URL.strip(), "https": CLOAK_PROXY_URL.strip()}
    session.cookies.update(cookies)
    session.headers.update({
        "user-agent": ua,
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    soup = BeautifulSoup(register_html, "html.parser")
    csrf_token_tag = soup.find("meta", {"name": "csrf-token"})
    csrf_token = csrf_token_tag.get("content") if csrf_token_tag else ""
    elem = soup.find(attrs={"wire:snapshot": True})
    if not elem:
        raise RuntimeError("Livewire snapshot register sayfasında bulunamadı.")
    raw_snapshot = elem["wire:snapshot"]
    update_uri_match = re.search(r'data-update-uri="([^"]+)"', register_html)
    if not update_uri_match:
        raise RuntimeError("data-update-uri register sayfasında bulunamadı.")
    update_uri = update_uri_match.group(1)

    box = _random_box()
    email = f"{box}@tm.od2.in"
    name = _random_name()
    password = _random_password()

    # 1. Kayıt POST isteği
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": raw_snapshot,
                "updates": {
                    "name": name,
                    "email": email,
                    "password": password,
                    "password_confirmation": password
                },
                "calls": [{"method": "register", "params": [], "metadata": {}}]
            }
        ]
    }
    lw_headers = {
        "content-type": "application/json",
        "x-livewire": "1",
        "referer": "https://app.deapi.ai/register",
        "origin": "https://app.deapi.ai",
        "accept": "*/*",
    }
    r_post = session.post(update_uri, json=payload, headers=lw_headers)
    if r_post.status_code != 200:
        raise RuntimeError(f"Kayıt isteği başarısız oldu: HTTP {r_post.status_code}")

    # 2. Doğrulama e-postasını bekle
    if log_callback:
        log_callback(f"Aktivasyon e-postası bekleniyor (Kutu: {box})...", "registering", 23)
    print(f"[*] Aktivasyon e-postası bekleniyor (Kutu: {box})...", flush=True)

    verify_url = None
    t_start = time.time()
    while time.time() - t_start < 90:
        try:
            m_res = requests.get(
                "https://od2.in/api/get-email",
                params={"id": box},
                headers={
                    "user-agent": "Mozilla/5.0",
                    "accept": "*/*",
                    "referer": f"https://od2.in/temp-mail?id={box}",
                },
                timeout=15
            ).json()
            if m_res and isinstance(m_res, list) and len(m_res) > 0:
                for item in m_res:
                    email_id = item.get("_id")
                    if not email_id:
                        continue
                    try:
                        msg = requests.get(
                            "https://od2.in/api/get-email",
                            params={"emailId": email_id},
                            headers={"user-agent": "Mozilla/5.0"},
                            timeout=15
                        ).json()
                        content = (msg.get("text") or "") + "\n" + (msg.get("html") or "")
                        match = re.search(r'https://app\.deapi\.ai/verify-email/[^\s"\'<>]+', content)
                        if not match:
                            match = re.search(r'https?://[^\s"\'<>]*verify-email[^\s"\'<>]*', content)
                        if match:
                            verify_url = html.unescape(match.group(0))
                            break
                    except Exception:
                        pass
                if verify_url:
                    break
        except Exception:
            pass
        time.sleep(3)

    if not verify_url:
        raise RuntimeError("Doğrulama e-postası zamanında gelmedi.")

    # 3. E-postayı onayla
    if log_callback:
        log_callback("E-posta başarıyla onaylandı. $5 kredili API anahtarı üretiliyor...", "registering", 26)
    session.get(verify_url)

    # 4. API Keys sayfasından yeni anahtar üret
    r_keys = session.get("https://app.deapi.ai/settings/api-keys")
    soup_keys = BeautifulSoup(r_keys.text, "html.parser")
    csrf_tag = soup_keys.find("meta", {"name": "csrf-token"})
    csrf_keys = csrf_tag.get("content") if csrf_tag else ""
    elem_keys = soup_keys.find("section", {"wire:name": "settings.api-keys"})
    if not elem_keys:
        elem_keys = soup_keys.find(attrs={"wire:snapshot": True})

    raw_snap_keys = elem_keys["wire:snapshot"]
    update_uri_keys_match = re.search(r'data-update-uri="([^"]+)"', r_keys.text)
    if not update_uri_keys_match:
        raise RuntimeError("API Keys sayfasında update URI bulunamadı.")
    update_uri_keys = update_uri_keys_match.group(1)

    key_payload = {
        "_token": csrf_keys,
        "components": [
            {
                "snapshot": raw_snap_keys,
                "updates": {"keyName": f"Key_{_random_box(4)}"},
                "calls": [{"method": "createKey", "params": [], "metadata": {}}]
            }
        ]
    }
    lw_headers["referer"] = "https://app.deapi.ai/settings/api-keys"
    r_create = session.post(update_uri_keys, json=key_payload, headers=lw_headers)

    m_key = re.search(r'\b(\d{5}\|[a-zA-Z0-9]{40,65})\b', r_create.text)
    if not m_key:
        m_key = re.search(r'createdKey\\?":\s*\\?"([^\\"]+)', r_create.text)

    if not m_key:
        raise RuntimeError(f"API anahtarı yanıttan alınamadı: {r_create.text[:300]}")

    api_key = m_key.group(1)
    if log_callback:
        log_callback(f"Yeni deAPI hesabı açıldı! API Key hazır (3 kullanım tanımlandı).", "success", 28)

    return api_key


# ==============================================================================
# 2. ÇOKLU HESAP HAVUZU & PARALEL GPU YÖNETİMİ (1 GPU CONCURRENCY PER ACCOUNT)
# ==============================================================================

class KeyBucket:
    """
    Her bir deAPI hesabını/anahtarını yönetir:
    - deAPI Kuralı: Tek bir ücretsiz deAPI hesabı aynı anda SADECE 1 GPU GÖREVİ işleyebilir!
    - Eğer bir hesap GPU'da video üretirken (active_gpu_jobs > 0) 2. bir görev gönderilirse,
      deAPI 2. görevi kuyrukta (progress: 0.0) tam 205 saniye BEKLETİR!
    - Bu nedenle:
      * active_gpu_jobs > 0 iken BU HESABA ASLA YENİ GÖREV ATANMAZ!
      * Eşzamanlı gelen tüm görevler anında bağımsız yeni hesaplarda eşzamanlı (paralel) başlar!
      * Hesap sadece GPU'su BOŞTA ise ve 60 sn (1 RPM) geçmişse tekrar kullanılır (MiniMax: 3, LTX: 15 kota).
    """
    def __init__(self, bucket_id: int, max_slots: int = 3):
        self.bucket_id = bucket_id
        self.max_slots = max_slots
        self.api_key: Optional[str] = None
        self.key_lock = threading.Lock()
        self.created_at = time.time()
        self.last_dispatch_time = 0.0
        self.used_count = 0
        self.active_gpu_jobs = 0
        self.lock = threading.RLock()

    def can_accept(self) -> bool:
        with self.lock:
            # 1. Günlük kota kontrolü (MiniMax: 3, LTX: 15)
            if self.used_count >= self.max_slots:
                return False
            # 2. GPU MEŞGULİYET KONTROLÜ (En kritik nokta: Asla GPU kuyruğuna sokma!)
            if self.active_gpu_jobs > 0:
                return False
            # 3. 1 RPM Hız Sınırı: Son istekten bu yana 60 saniye geçmiş olmalı
            now = time.time()
            if self.last_dispatch_time > 0 and (now - self.last_dispatch_time) < 60.0:
                return False
            return True

    def get_api_key(self, force_new: bool = False, log_callback: Optional[Callable[[str, str, int], None]] = None) -> str:
        with self.key_lock:
            if not self.api_key or force_new:
                if log_callback:
                    if self.bucket_id > 1:
                        log_callback(f"Hesap #{self.bucket_id} için yeni deAPI hesabı hazırlanıyor...", "registering", 8)
                    else:
                        log_callback("deAPI hesabı ve API anahtarı hazırlanıyor...", "registering", 8)
                with _ACCOUNT_CREATION_LOCK:
                    self.api_key = _create_new_deapi_account(log_callback)
            return self.api_key

    def mark_started(self):
        with self.lock:
            self.active_gpu_jobs += 1
            self.used_count += 1
            self.last_dispatch_time = time.time()

    def mark_finished(self):
        with self.lock:
            if self.active_gpu_jobs > 0:
                self.active_gpu_jobs -= 1


class DeApiKeyManager:
    """
    Eşzamanlı gelen tüm video isteklerini yönetir:
    - Eğer mevcut hesapların tamamı GPU'da meşgulse: HİÇ BEKLEMEDEN anında yeni hesap açar!
    - Görevler birbirini 205 saniye kuyrukta beklemez; paralel GPUs'larda eşzamanlı üretilir.
    - Boşta hesap varsa ve kotası yetiyorsa hesabı tekrar kullanarak tasarruf sağlar.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets: List[KeyBucket] = []
        self.bucket_counter = 0

    def get_or_create_bucket(self, model_slug: str = "") -> KeyBucket:
        is_ltx = "ltx" in model_slug.lower()
        limit = 15 if is_ltx else 3
        with self.lock:
            # 1. Mevcut hesaplardan GPU'su boşta, kotası olan ve 1 RPM geçmiş olan var mı bak
            for b in self.buckets:
                if b.max_slots == limit and b.can_accept():
                    return b

            # 2. Boşta hesap yoksa (hepsi GPU'da render yapıyor veya kotası doldu):
            # 205 saniye kuyruk beklemek YERİNE ANINDA YENİ HESAP AÇ VE PARALEL BAŞLAT!
            self.bucket_counter += 1
            new_bucket = KeyBucket(self.bucket_counter, max_slots=limit)
            self.buckets.append(new_bucket)
            return new_bucket

KEY_MANAGER = DeApiKeyManager()


# ==============================================================================
# 3. VİDEO ÇÖZÜNÜRLÜK & PARAMETRE NORMALİZASYONU
# ==============================================================================

def normalize_dimensions(aspect_ratio: str, resolution: str = "768p") -> Tuple[int, int]:
    """
    Kullanıcının seçtiği Aspect Ratio ve Resolution değerlerini
    deAPI'nin desteklediği 1344x768 piksel (maks 1.032.192 piksel) sınırlarına normalize eder.
    """
    ar = aspect_ratio.strip() if aspect_ratio else "16:9"
    res = resolution.lower() if resolution else "768p"

    if res in ("720p", "standard", "low", "480p"):
        dims = RESOLUTION_TABLE_720P.get(ar, RESOLUTION_TABLE_720P["16:9"])
    else:
        dims = RESOLUTION_TABLE.get(ar, RESOLUTION_TABLE["16:9"])

    return dims["width"], dims["height"]

def normalize_duration(duration_choice: str, model_slug: str) -> Tuple[int, int]:
    """
    Ön yüzden gelen saniye seçimini (5 veya 10 saniye) modelin desteklediği kare ve FPS değerine çevirir.
    """
    d_str = str(duration_choice).strip() if duration_choice else "5"
    is_minimax = "minimax" in model_slug.lower()

    if d_str in ("10", "10s", "10 Saniye"):
        frames = 243 if is_minimax else 241
    else:
        # Varsayılan 5 saniye
        frames = 124 if is_minimax else 120

    fps = 24
    return frames, fps


# ==============================================================================
# 4. VİDEO ÜRETİM & TAKİP MOTORU (RUN_VIDEO / RUN_ONCE)
# ==============================================================================

def open_clean_mime(stack: ExitStack, filepath: str):
    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = "application/octet-stream"
    f = stack.enter_context(open(filepath, "rb"))
    return (os.path.basename(filepath), f, mime_type)

def run_video(
    prompt: str,
    images: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "768p",
    model: str = "MiniMaxH3_33B_Turbo_INT8",
    negative_prompt: str = "",
    enhance_prompt: bool = False,
    seed: Optional[Union[int, str]] = None,
    fps: Optional[Union[int, str]] = None,
    audio_path: Optional[str] = None,
    audio_url: Optional[str] = None,
    video_path: Optional[str] = None,
    video_url: Optional[str] = None,
    ref_mode: str = "gallery",
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    job_id: Optional[str] = None,
    is_active: Optional[Callable[[], bool]] = None
) -> Dict[str, Any]:
    """
    deAPI üzerinden MiniMax M3 veya LTX 2.5 video modelini çalıştırır.
    İş akışı:
      1. Çoklu görev kuyruğu (KeyBucket): 1 anahtar en fazla 3 görev alır.
      2. 1., 2. ve 3. görevler aynı anahtarda sırayla 1 RPM (60 sn) bekler.
      3. 4. görev geldiğinde (anahtar kotası dolunca) beklemeden hemen yeni anahtar açılır ve işlem başlar.
      4. Keyframe (Start/End) ve Full-Reference (Görsel + Video + Ses) medya modları desteklenir.
      5. İşi takip eder ve bitince video bağlantısını döndürür.
    """
    model_slug = MODEL_SLUGS.get(model, model)
    width, height = normalize_dimensions(aspect_ratio, resolution)
    norm_frames, norm_fps = normalize_duration(duration, model_slug)

    # deAPI'de hem MiniMax hem LTX modellerinde FPS kesinlikle ve zorunlu olarak 24'tür
    actual_fps = 24

    # Seed belirleme
    if seed is not None and str(seed).strip() != "" and str(seed).strip() != "-1":
        try:
            seed_val = int(seed)
        except ValueError:
            seed_val = random.randint(1, 2147483647)
    else:
        seed_val = random.randint(1, 2147483647)

    payload = {
        "model": model_slug,
        "prompt": prompt,
        "width": width,
        "height": height,
        "frames": norm_frames,
        "fps": actual_fps,
        "seed": seed_val
    }

    # LTX modeli kuralı: steps: 1 ve kesinlikle yalnızca Keyframe (Start/End) kabul eder
    if "ltx" in model_slug.lower():
        payload["steps"] = 1
        ref_mode = "frames"
        audio_url = None
        video_url = None
        audio_path = None
        video_path = None

    if negative_prompt and negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()

    if enhance_prompt:
        payload["enhance_prompt"] = True

    if audio_url and audio_url.strip():
        payload["audio_url"] = audio_url.strip()

    if video_url and video_url.strip():
        payload["video_url"] = video_url.strip()

    # Dosya ve medya referansı kontrolleri
    valid_images = [img for img in (images or []) if img and os.path.isfile(img)]
    if ref_mode == "frames":
        has_audio_file = False
        has_video_file = False
        audio_path = None
        video_path = None
        payload.pop("audio_url", None)
        payload.pop("video_url", None)
    else:
        has_audio_file = bool(audio_path and os.path.isfile(audio_path))
        has_video_file = bool(video_path and os.path.isfile(video_path))
        if (has_audio_file or (audio_url and audio_url.strip())) and not valid_images and not has_video_file and not (video_url and video_url.strip()):
            raise ValueError("deAPI Kuralı: Ses referansı tek başına verilemez. Yanında en az 1 görsel veya video referansı eklenmelidir.")

    is_animation = bool(valid_images or has_audio_file or has_video_file)

    # Model RPD Kotasına göre (MiniMax: 3, LTX: 15) Hesap Tahsisi (Meşgul GPU'lar asla paylaşılmaz!)
    bucket = KEY_MANAGER.get_or_create_bucket(model_slug)

    if log_callback:
        mode_desc = []
        if ref_mode == "frames":
            mode_desc.append("Start/End Keyframe")
        else:
            if valid_images:
                mode_desc.append(f"{min(3, len(valid_images))} Görsel")
            if has_video_file:
                mode_desc.append("Video")
            if has_audio_file or (audio_url and audio_url.strip()):
                mode_desc.append("Ses")

        mode_str = " + ".join(mode_desc) if mode_desc else "Metinden Video (Text-to-Video)"
        log_callback(f"deAPI motoru hazırlanıyor: {model} ({mode_str}, {width}x{height} px, {duration}s, {actual_fps} FPS) [Hesap #{bucket.bucket_id}, Kullanım: {bucket.used_count + 1}/{bucket.max_slots}]...", "registering", 5)

    request_id = None
    api_key = None
    dispatched = False

    try:
        # 1. 1 RPM (60 saniye) hız sınırı koruması (eğer aynı hesap tekrar kullanılıyorsa)
        while True:
            if is_active and not is_active():
                return {"error": "İşlem iptal edildi."}
            now = time.time()
            elapsed = now - bucket.last_dispatch_time
            needed_wait = 60.0 - elapsed
            if needed_wait <= 0 or bucket.last_dispatch_time <= 0:
                break
            wait_sec = int(math.ceil(needed_wait))
            if log_callback:
                log_callback(f"deAPI 1 RPM hız sınırı korunuyor: İşlem {wait_sec} sn sonra iletilecek...", "queued", 15)
            step = min(2.0, max(0.5, needed_wait))
            time.sleep(step)

        # 2. API Anahtarını al (Hesap boşta değilse veya yeni oluşturulduysa anında temin edilir)
        api_key = bucket.get_api_key(force_new=False, log_callback=log_callback)

        max_send_attempts = 4
        for attempt in range(max_send_attempts):
            if is_active and not is_active():
                return {"error": "İşlem iptal edildi."}

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json"
            }

            if log_callback:
                log_callback(f"Video üretim isteği deAPI sunucusuna gönderiliyor (Hesap #{bucket.bucket_id}, Kullanım: {bucket.used_count + 1}/{bucket.max_slots})...", "registering", 30)

            try:
                if is_animation:
                    endpoint = f"{BASE_URL}/videos/animations"
                    form_data = {}
                    for k, v in payload.items():
                        if v is not None:
                            form_data[k] = "true" if isinstance(v, bool) and v else ("false" if isinstance(v, bool) else str(v))

                    with ExitStack() as stack:
                        files = []
                        if ref_mode == "frames":
                            # Keyframe Modu: SADECE Start / End Kareleri (Ses veya harici medya kabul edilmez)
                            if len(valid_images) >= 1:
                                files.append(("first_frame_image", open_clean_mime(stack, valid_images[0])))
                            if len(valid_images) >= 2:
                                files.append(("last_frame_image", open_clean_mime(stack, valid_images[1])))
                        else:
                            # Full-Reference Modu: Resim, Video ve Ses toplamı EN FAZLA 3 MEDYA
                            ref_total = 0
                            img_idx = 0
                            if valid_images:
                                for img_p in valid_images:
                                    if ref_total < 3:
                                        files.append((f"ref_images[{img_idx}]", open_clean_mime(stack, img_p)))
                                        ref_total += 1
                                        img_idx += 1
                            if has_video_file and ref_total < 3:
                                files.append(("ref_videos[0]", open_clean_mime(stack, video_path)))
                                ref_total += 1
                            if has_audio_file and ref_total < 3:
                                files.append(("ref_audios[0]", open_clean_mime(stack, audio_path)))
                                ref_total += 1

                        resp = requests.post(endpoint, headers=headers, data=form_data, files=files, timeout=120)
                else:
                    endpoint = f"{BASE_URL}/videos/generations"
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)

            except Exception as net_err:
                if attempt < max_send_attempts - 1:
                    if log_callback:
                        log_callback(f"Ağ bağlantı hatası: {net_err}. 5 sn sonra tekrar deneniyor...", "warning", 30)
                    time.sleep(5)
                    continue
                raise RuntimeError(f"deAPI bağlantı hatası: {net_err}")

            # 429 Rate Limit (1 RPM) Kontrolü
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 20))
                if retry_after <= 0:
                    retry_after = 20
                rem = min(retry_after, 60)
                while rem > 0:
                    if is_active and not is_active():
                        return {"error": "İşlem iptal edildi."}
                    if log_callback:
                        log_callback(f"deAPI 1 RPM hız sınırı korunuyor ({rem} sn)...", "warning", 32)
                    st = min(2, rem)
                    time.sleep(st)
                    rem -= st
                continue

            # 401 veya 403 (Yetkisiz / Bakiye Yetersiz / Geçersiz Anahtar)
            if resp.status_code in (401, 403):
                if log_callback:
                    log_callback("API Anahtarı yetkisiz (401/403). Otomatik yeni anahtar üretiliyor...", "warning", 10)
                api_key = bucket.get_api_key(force_new=True, log_callback=log_callback)
                continue

            # Başarılı istek
            if resp.status_code == 200:
                resp_data = resp.json().get("data", {})
                request_id = resp_data.get("request_id")
                if request_id:
                    bucket.mark_started()
                    dispatched = True
                    if log_callback:
                        log_callback(f"İş deAPI GPU işlemine alındı (ID: {request_id[:8]}...). Hesap #{bucket.bucket_id} (Kullanım: {bucket.used_count}/{bucket.max_slots})", "generating", 35)
                    break

            # Diğer hatalar (422 vb.)
            err_msg = resp.text
            try:
                err_json = resp.json()
                if "message" in err_json:
                    err_msg = err_json["message"]
                if "errors" in err_json:
                    err_msg += " -> " + json.dumps(err_json["errors"], ensure_ascii=False)
            except Exception:
                pass
            raise RuntimeError(f"deAPI Hatası (HTTP {resp.status_code}): {err_msg}")

        if not request_id:
            raise RuntimeError("deAPI video isteği başlatılamadı.")

        # 3. Polling (İşin durumunu takip et)
        poll_url = f"{BASE_URL}/jobs/{request_id}"
        start_poll_time = time.time()
        last_reported_pct = 35
        last_heartbeat_time = time.time()

        while True:
            time.sleep(3)
            now_t = time.time()
            elapsed_total = int(now_t - start_poll_time)

            if is_active and not is_active():
                return {"error": "İşlem iptal edildi."}

            try:
                r_poll = requests.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                    timeout=25
                )
                if r_poll.status_code == 200:
                    p_info = r_poll.json().get("data", {})
                    status = p_info.get("status", "processing")
                    progress = float(p_info.get("progress", 0.0))

                    calc_pct = int(35 + min(60.0, progress * 0.6))
                    if calc_pct > last_reported_pct:
                        last_reported_pct = calc_pct
                        if log_callback:
                            log_callback(f"Video kareleri üretiliyor (%{int(progress)})...", "generating", last_reported_pct)
                    elif progress == 0.0 and (now_t - last_heartbeat_time >= 8):
                        last_heartbeat_time = now_t
                        if log_callback:
                            log_callback(f"deAPI GPU işlemi hazırlanıyor ({elapsed_total} sn)...", "generating", 35)

                    if status == "done":
                        if log_callback:
                            log_callback("GPU üretimi tamamlandı! Video CDN bağlantısı alınıyor...", "generating", 95)

                        # CDN S3 yükleme gecikmesi için result_url kontrolü
                        result_url = p_info.get("result_url")
                        sub_retries = 0
                        while not result_url and sub_retries < 12:
                            time.sleep(2)
                            sub_retries += 1
                            sub_resp = requests.get(
                                poll_url,
                                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                                timeout=25
                            )
                            if sub_resp.status_code == 200:
                                result_url = sub_resp.json().get("data", {}).get("result_url")

                        if not result_url:
                            raise RuntimeError("Video tamamlandı ancak deAPI indirme bağlantısı (result_url) verilmedi.")

                        if log_callback:
                            log_callback("Video başarıyla üretildi!", "success", 100)

                        return {
                            "success": True,
                            "video_url": result_url,
                            "request_id": request_id,
                            "account_id": bucket.bucket_id
                        }

                    elif status in ("failed", "error", "cancelled"):
                        err_detail = p_info.get("error") or p_info.get("message") or "Bilinmeyen hata"
                        raise RuntimeError(f"deAPI işi başarısız oldu: {err_detail}")

                elif r_poll.status_code in (401, 403):
                    # Polling sırasında anahtar geçersizleşirse sonucu kaybetmemek için bir süre daha dene
                    print(f"[!] Polling yetki hatası (HTTP {r_poll.status_code}), iş devam ediyor olabilir...", flush=True)

            except requests.RequestException as poll_net_err:
                print(f"[!] Polling ağ hatası: {poll_net_err}", flush=True)

            # Maksimum 15 dakika (900 sn) üretim süresi toleransı
            if elapsed_total > 900:
                raise RuntimeError("Video üretim süresi 15 dakikayı aştı (zaman aşımı).")

    except Exception as e:
        return {"error": str(e)}

    finally:
        if dispatched:
            bucket.mark_finished()


def run_once(
    prompt: str,
    images: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "768p",
    model: str = "MiniMaxH3_33B_Turbo_INT8",
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Dış modüller (app.py vb.) için tek seferlik çalıştırma kısayolu.
    Tüm parametreleri run_video'ya şeffaf şekilde iletir.
    """
    return run_video(
        prompt=prompt,
        images=images,
        aspect_ratio=aspect_ratio,
        duration=duration,
        resolution=resolution,
        model=model,
        log_callback=log_callback,
        **kwargs
    )
