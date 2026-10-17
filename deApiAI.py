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
import cloakbrowser
from cloakbrowser import launch_persistent_context

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

# Cloudflare Turnstile Çerez & UA Önbelleği (Cookie bayatlamadıysa tarayıcı açılmaz)
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
PROXY_MODE = 1
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
    Tarayıcıyı (CloakBrowser) sadece Cloudflare Turnstile'ı çözüp giriş çerezlerini
    almak için kısa süreli çalıştırır ve HEMEN KAPATIR.
    Proxy ayarı (PROXY_MODE=1 ise) yalnızca tarayıcı açık kaldığı süre boyunca devrededir.
    """
    if log_callback:
        log_callback("Cloudflare Turnstile doğrulaması için CloakBrowser açılıyor...", "registering", 12)
    print(f"[*] Cloudflare Turnstile doğrulaması için CloakBrowser başlatılıyor... (Proxy Modu: {'Açık' if PROXY_MODE == 1 else 'Kapalı'})", flush=True)

    os.makedirs(PROFILE_DIR, exist_ok=True)

    context_kwargs = {
        "user_data_dir": PROFILE_DIR,
        "headless": True,
        "humanize": True,
        "stealth_args": True,
        "args": [
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1920,1080",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    }

    # Proxy yalnızca CloakBrowser oturumunda kullanılır
    if PROXY_MODE == 1 and CLOAK_PROXY_URL and CLOAK_PROXY_URL.strip().lower() not in ["none", "direct", "no", "off", ""]:
        context_kwargs["proxy"] = CLOAK_PROXY_URL.strip()

    context = launch_persistent_context(**context_kwargs)

    try:
        # Önceki login çerezlerini temizle
        for c in context.cookies():
            if "appdeapiai" in c.get("name", ""):
                try:
                    context.clear_cookies()
                except Exception:
                    pass
                break

        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://app.deapi.ai/register", wait_until="domcontentloaded")

        t0 = time.time()
        last_click_time = 0
        clicked_logged = False
        while time.time() - t0 < 120:
            try:
                title = page.title()
            except Exception:
                title = ""

            cookies_dict = {c["name"]: c["value"] for c in context.cookies()}

            bypassed = False
            if "Just a moment" not in title and "Bir dakika" not in title and ("Register" in title or "deAPI" in title or "Sign" in title or "Hesap" in title):
                bypassed = True
            elif "cf_clearance" in cookies_dict:
                bypassed = True

            if bypassed:
                try:
                    content = page.content()
                    if "wire:snapshot" in content or "csrf-token" in content:
                        break
                except Exception:
                    if bypassed:
                        break

            now = time.time()
            if now - last_click_time >= 1.5:
                for frame in page.frames:
                    if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                        try:
                            cb = frame.locator("input[type='checkbox'], .ctp-checkbox-label, #challenge-stage")
                            if cb.count() > 0:
                                cb.first.click(timeout=1000)
                            else:
                                frame.locator("body").click(timeout=1000)
                            last_click_time = now
                            if log_callback and not clicked_logged:
                                log_callback("Cloudflare Turnstile kutucuğu tıklandı, çözülüyor...", "registering", 15)
                                clicked_logged = True
                            break
                        except Exception:
                            try:
                                frame.locator("body").click(timeout=1000)
                                last_click_time = now
                                break
                            except Exception:
                                pass
            time.sleep(1)

        # Cookiebot engelini kaldır (varsa)
        try:
            page.evaluate("""() => {
                const el = document.getElementById('CybotCookiebotDialog');
                if (el) el.remove();
                const underlay = document.getElementById('CybotCookiebotDialogBodyUnderlay');
                if (underlay) underlay.remove();
            }""")
        except Exception:
            pass

        time.sleep(1)
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        ua = page.evaluate("() => navigator.userAgent")
        page_html = page.content()

    finally:
        context.close()
        if log_callback:
            log_callback("Tarayıcı kapatıldı. İşlemler arka planda hızlı HTTP ile devam ediyor...", "registering", 18)
        print("[+] CloakBrowser kapatıldı.", flush=True)

    return cookies, ua, page_html

def _get_or_refresh_cf_session(log_callback: Optional[Callable[[str, str, int], None]] = None) -> Tuple[Dict[str, str], str, str]:
    """
    Eğer bellekteki cf_clearance çerezleri hala geçerliyse doğrudan HTTP ile register HTML'ini alır.
    Tarayıcıyı (CloakBrowser) YALNIZCA çerez yoksa veya bayatladıysa (403 / challenge) açar!
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
                    log_callback("Cloudflare çerezi hala taze! Tarayıcı açılmadan doğrudan hızlı HTTP ile hesap açılıyor...", "registering", 15)
                print("[+] Cloudflare çerezi hala geçerli, tarayıcı AÇILMADAN doğrudan devam ediliyor.", flush=True)
                return cached_cookies, cached_ua, resp.text
            else:
                print(f"[*] Cloudflare çerezi bayatlamış (HTTP {resp.status_code}), Turnstile için tarayıcı açılacak.", flush=True)
        except Exception as e:
            print(f"[!] Çerez test hatası: {e}, tarayıcı açılacak.", flush=True)

    # Çerez yok veya bayatlamış -> CloakBrowser ile Turnstile çöz
    if log_callback:
        log_callback("Cloudflare çerezi tazelemek için CloakBrowser açılıyor...", "registering", 12)
    cookies, ua, page_html = _get_cf_session_via_browser(log_callback)
    _CACHED_CF_SESSION["cookies"] = cookies
    _CACHED_CF_SESSION["ua"] = ua
    _CACHED_CF_SESSION["created_at"] = time.time()
    return cookies, ua, page_html

def _create_new_deapi_account(log_callback: Optional[Callable[[str, str, int], None]] = None) -> str:
    """
    Tarayıcıdan alınan çerezlerle arka planda otomatik geçici e-posta alır,
    kaydı tamamlar, e-postayı onaylar ve $5 bakiyeli yeni API anahtarı üretir.
    Çerez taze ise tarayıcı açılmaz!
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
# 2. ÇOKLU ANAHTAR HAVUZU & 3 KULLANIMLIK SLOT YÖNETİMİ
# ==============================================================================

class KeyBucket:
    """
    Her bir deAPI hesabını/anahtarını ve model RPD kotasına göre (MiniMax: 3, LTX: 15) slotlarını yönetir.
    - Slot 0 (1. İşlem): Hemen başlar (cooldown yoksa).
    - Slot 1+ (Sıradaki İşlemler): Önceki slotun API'ye iletilmesini bekler, ardından 1 RPM (60 sn) cooldown'ını bekler.
    """
    def __init__(self, bucket_id: int, max_slots: int = 3):
        self.bucket_id = bucket_id
        self.max_slots = max_slots
        self.api_key: Optional[str] = None
        self.key_lock = threading.Lock()
        self.created_at = time.time()
        self.last_dispatch_time = 0.0
        self.slots_assigned = 0
        self.dispatched_events: Dict[int, threading.Event] = {}
        self.slots_lock = threading.RLock()

    def get_event(self, slot_idx: int) -> threading.Event:
        with self.slots_lock:
            if slot_idx not in self.dispatched_events:
                self.dispatched_events[slot_idx] = threading.Event()
            return self.dispatched_events[slot_idx]

    def get_api_key(self, force_new: bool = False, log_callback: Optional[Callable[[str, str, int], None]] = None) -> str:
        with self.key_lock:
            if not self.api_key or force_new:
                if log_callback:
                    if self.bucket_id > 1:
                        log_callback(f"Anahtar #{self.bucket_id} için otomatik yeni deAPI hesabı açılıyor...", "registering", 8)
                    else:
                        log_callback("deAPI hesabı ve API anahtarı hazırlanıyor...", "registering", 8)
                with _ACCOUNT_CREATION_LOCK:
                    self.api_key = _create_new_deapi_account(log_callback)
            return self.api_key

    def mark_dispatched(self, slot_idx: int):
        with self.slots_lock:
            self.last_dispatch_time = time.time()
            if slot_idx not in self.dispatched_events:
                self.dispatched_events[slot_idx] = threading.Event()
            self.dispatched_events[slot_idx].set()

    def mark_failed_or_skipped(self, slot_idx: int):
        """Eğer bir slot hata alırsa veya iptal edilirse sonraki slotların kilitlenmemesi için sinyal verir."""
        with self.slots_lock:
            if slot_idx not in self.dispatched_events:
                self.dispatched_events[slot_idx] = threading.Event()
            self.dispatched_events[slot_idx].set()


class DeApiKeyManager:
    """
    Tüm gelen deAPI işlerini model RPD kotalarına göre paketler (KeyBucket) halinde yönetir:
    - MiniMax M3: RPD = 3 (1 anahtar ile en fazla 3 video)
    - LTX 2.5:    RPD = 15 (1 anahtar ile en fazla 15 video)
    - Her iki modelde de 1 RPM (60 sn) hız sınırı korunur.
    - Kota dolduğunda sıradaki görev beklemeden hemen yeni anahtar başlatır.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets: List[KeyBucket] = []
        self.current_bucket: Optional[KeyBucket] = None
        self.bucket_counter = 0

    def assign_slot(self, job_id: str, model_slug: str = "") -> Tuple[KeyBucket, int]:
        is_ltx = "ltx" in model_slug.lower()
        limit = 15 if is_ltx else 3
        with self.lock:
            if self.current_bucket is None or self.current_bucket.slots_assigned >= self.current_bucket.max_slots:
                self.bucket_counter += 1
                new_bucket = KeyBucket(self.bucket_counter, max_slots=limit)
                self.buckets.append(new_bucket)
                self.current_bucket = new_bucket

            bucket = self.current_bucket
            if bucket.slots_assigned >= limit:
                self.bucket_counter += 1
                new_bucket = KeyBucket(self.bucket_counter, max_slots=limit)
                self.buckets.append(new_bucket)
                self.current_bucket = new_bucket
                bucket = new_bucket

            slot_idx = bucket.slots_assigned
            bucket.slots_assigned += 1
            return bucket, slot_idx

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

    # Model RPD Kotasına göre (MiniMax: 3, LTX: 15) Slot Tahsisi
    bucket, slot_idx = KEY_MANAGER.assign_slot(job_id or str(time.time()), model_slug)

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
        log_callback(f"deAPI motoru hazırlanıyor: {model} ({mode_str}, {width}x{height} px, {duration}s, {actual_fps} FPS) [Anahtar #{bucket.bucket_id}, Sıra: {slot_idx + 1}/{bucket.max_slots}]...", "registering", 5)

    request_id = None
    api_key = None
    try:
        # 1. Eğer bu anahtarda önceki bir slot varsa onun deAPI'ye isteği göndermesini bekle
        if slot_idx > 0:
            prev_slot = slot_idx - 1
            while not bucket.get_event(prev_slot).is_set():
                if is_active and not is_active():
                    bucket.mark_failed_or_skipped(slot_idx)
                    return {"error": "İşlem iptal edildi."}
                if log_callback:
                    log_callback(f"Önceki deAPI video işleminin gönderimi bekleniyor (Anahtar #{bucket.bucket_id}, Sıra: {slot_idx + 1}/{bucket.max_slots})...", "queued", 10)
                bucket.get_event(prev_slot).wait(timeout=2.0)

        # 2. Bu anahtarın 1 RPM (60 saniye) hız sınırı koruması
        while True:
            if is_active and not is_active():
                bucket.mark_failed_or_skipped(slot_idx)
                return {"error": "İşlem iptal edildi."}
            now = time.time()
            elapsed = now - bucket.last_dispatch_time
            needed_wait = 60.0 - elapsed
            if needed_wait <= 0 or bucket.last_dispatch_time <= 0:
                break
            wait_sec = int(math.ceil(needed_wait))
            if log_callback:
                log_callback(f"deAPI 1 RPM hız sınırı korunuyor: İşlem {wait_sec} sn sonra iletilecek... (Sıra: {slot_idx + 1}/{bucket.max_slots})", "queued", 15)
            step = min(2.0, max(0.5, needed_wait))
            time.sleep(step)

        # 3. API Anahtarını al (Anahtar 4. iş içinse hemen yeni hesap açılır)
        api_key = bucket.get_api_key(force_new=False, log_callback=log_callback)

        max_send_attempts = 4
        for attempt in range(max_send_attempts):
            if is_active and not is_active():
                bucket.mark_failed_or_skipped(slot_idx)
                return {"error": "İşlem iptal edildi."}

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json"
            }

            if log_callback:
                log_callback(f"Video üretim isteği deAPI sunucusuna gönderiliyor (Anahtar #{bucket.bucket_id}, Sıra: {slot_idx + 1}/{bucket.max_slots})...", "registering", 30)

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
                bucket.mark_failed_or_skipped(slot_idx)
                raise RuntimeError(f"deAPI bağlantı hatası: {net_err}")

            # 429 Rate Limit (1 RPM) Kontrolü
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 20))
                if retry_after <= 0:
                    retry_after = 20
                rem = min(retry_after, 60)
                while rem > 0:
                    if is_active and not is_active():
                        bucket.mark_failed_or_skipped(slot_idx)
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
                    bucket.mark_dispatched(slot_idx)
                    if log_callback:
                        log_callback(f"İş deAPI GPU kuyruğuna alındı (ID: {request_id[:8]}...). Anahtar #{bucket.bucket_id} (Kullanım: {slot_idx + 1}/{bucket.max_slots})", "generating", 35)
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
            bucket.mark_failed_or_skipped(slot_idx)
            raise RuntimeError(f"deAPI Hatası (HTTP {resp.status_code}): {err_msg}")

    except Exception as e:
        bucket.mark_failed_or_skipped(slot_idx)
        raise e

    if not request_id:
        bucket.mark_failed_or_skipped(slot_idx)
        raise RuntimeError("deAPI video isteği başlatılamadı.")

    # 5. Polling (İşin durumunu takip et)
    poll_url = f"{BASE_URL}/jobs/{request_id}"
    start_poll_time = time.time()
    last_reported_pct = 35
    last_heartbeat_time = time.time()

    while True:
        time.sleep(3)
        now_t = time.time()
        elapsed_total = int(now_t - start_poll_time)

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
                    # Progress %0 iken (GPU sırası beklenirken) kullanıcının dondu sanmaması için canlı kalp atışı
                    last_heartbeat_time = now_t
                    if log_callback:
                        log_callback(f"deAPI GPU kuyruğu işleniyor ({elapsed_total} sn)...", "generating", 35)

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
                        raise RuntimeError("Video tamamlandı ancak deAPI indirme bağlantısı (result_url) vermedi.")

                    if log_callback:
                        log_callback("Video başarıyla hazırlandı ve sunuldu!", "completed", 100)

                    return {
                        "output": result_url,
                        "request_id": request_id,
                        "model": model,
                        "status": "completed"
                    }

                elif status == "error":
                    err_code = p_info.get("error_code", "ERROR")
                    err_reason = p_info.get("error_reason", "Bilinmeyen hata")
                    raise RuntimeError(f"deAPI video üretimi başarısız: {err_code} - {err_reason}")

        except requests.RequestException as e:
            # Geçici sorgu ağ hatalarını tolere et
            print(f"[!] Durum sorgulama ağ hatası: {e}", flush=True)

        if time.time() - start_poll_time > 600:
            raise TimeoutError("deAPI video üretimi zaman aşımına uğradı (10 dakika).")


# Alias fonksiyonu (diğer modüllerle uyumluluk için)
def run_once(
    prompt: str,
    image_path: Optional[str] = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "768p",
    model: str = "MiniMaxH3_33B_Turbo_INT8",
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    images = [image_path] if image_path else []
    return run_video(
        prompt=prompt,
        images=images,
        aspect_ratio=aspect_ratio,
        duration=duration,
        resolution=resolution,
        model=model,
        negative_prompt=kwargs.get("negative_prompt", ""),
        enhance_prompt=bool(kwargs.get("enhance_prompt", False)),
        seed=kwargs.get("seed"),
        log_callback=log_callback
    )
