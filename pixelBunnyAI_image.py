#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixel Bunny AI - Resim Üretim Modülü
Wild Owl Studio Entegrasyonu
"""

import io
import json
import os
import random
import re
import string
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzbmRocGFzb3hyd3p4cHpqbGZnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNDgxNjgsImV4cCI6MjA4NzkyNDE2OH0.cStXgyUmRDoaIctjoH4aNL2DUjjcnZLn_7VFNyEbdzE"
SUPABASE_URL = "https://esndhpasoxrwzxpzjlfg.supabase.co"
DEFAULT_PASSWORD = "SifreniYaz123!"

# app.py'daki model listesinin aynısı
MODELS_CONFIG = {
    "MiniMax H3 Image": {
        "model_id": "minimax-h3-image",
        "tiers": ["1k", "2k"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
        "resolutions": ["1K", "2K"],
        "resolution": "1K"
    },
    "Wan 2.7": {
        "model_id": "wan-2.7-image",
        "tiers": ["standard", "pro"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "resolution": "1K"
    },
    "Seedream 5 Pro": {
        "model_id": "seedream-5-pro",
        "tiers": ["1k", "2k"],
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
        "resolutions": ["1K", "2K"],
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
        "resolutions": ["1K", "2K", "4K"],
        "resolution": "1K"
    },
    "GPT Image 1.5": {
        "model_id": "gpt-image-1.5",
        "tiers": ["low", "medium", "high"],
        "aspect_ratios": ["1:1", "3:2", "2:3"],
        "resolution": "1K"
    },
    "Qwen 2.1": {
        "model_id": "qwen-image-2.1",
        "tiers": ["standard"],
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
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
        "resolutions": ["1K", "2K"],
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
    }
}


# ===================== TEMP EMAIL =====================
class eTemp:
    def random_email(self, length=15):
        return ''.join(
            random.SystemRandom().choice(string.ascii_lowercase + string.digits)
            for _ in range(length)
        )

    def getEmail(self):
        return self.random_email(15) + '@spamok.com'

    def getConfirmLink(self, mail, timeout=40):
        address = mail.replace('@spamok.com', '')
        for _ in range(timeout):
            try:
                r = requests.get(f'https://api.spamok.com/v2/EmailBox/{address}', timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    for m in data.get('mails', []):
                        if 'Confirm' in m.get('subject', '') or 'Pixel Bunny' in m.get('fromDisplay', ''):
                            mail_id = m['id']
                            email_r = requests.get(f'https://api.spamok.com/v2/Email/{address}/{mail_id}', timeout=8)
                            if email_r.status_code == 200:
                                html = email_r.json().get('messageHtml', '')
                                match = re.search(
                                    r'href="(https://mt-link\.pixelbunny\.ai/cl/[^\"]+)"[^>]*background-color:#7c3aed',
                                    html
                                )
                                if match:
                                    return match.group(1)
                                links = re.findall(r'href="(https://mt-link\.pixelbunny\.ai/cl/[^\"]+)"', html)
                                if len(links) >= 2:
                                    return links[1]
                                elif links:
                                    return links[0]
            except Exception:
                pass
            time.sleep(1)
        return None


# ===================== HESAP KAYDI =====================
def register_pixelbunny(
    password: str = DEFAULT_PASSWORD,
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    is_active: Optional[Callable[[], bool]] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Pixel Bunny için geçici e-posta ile otomatik hesap açar ve onaylar."""
    if log_callback:
        log_callback("Pixel Bunny için geçici e-posta alınıyor...", "registering", 10)

    temp = eTemp()
    email = temp.getEmail()

    if is_active and not is_active():
        return None, None

    if log_callback:
        log_callback(f"Pixel Bunny geçici e-posta oluşturuldu: {email}", "registering", 15)

    signup_url = f"{SUPABASE_URL}/auth/v1/signup"
    params = {"redirect_to": "https://pixelbunny.ai"}
    headers = {
        "apikey": API_KEY,
        "authorization": f"Bearer {API_KEY}",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://pixelbunny.ai",
        "referer": "https://pixelbunny.ai/",
        "x-client-info": "supabase-js-web/2.98.0",
        "x-supabase-api-version": "2024-01-01",
    }
    payload = {
        "email": email,
        "password": password,
        "data": {},
        "gotrue_meta_security": {},
        "code_challenge": None,
        "code_challenge_method": None,
    }

    if log_callback:
        log_callback("Pixel Bunny (Supabase Auth) kayıt isteği gönderiliyor...", "registering", 20)

    try:
        r = requests.post(signup_url, params=params, headers=headers, json=payload, timeout=15)
        if r.status_code not in [200, 201]:
            if log_callback:
                log_callback(f"Pixel Bunny kayıt hatası: {r.text}", "error", 20)
            return None, None
    except Exception as e:
        if log_callback:
            log_callback(f"Pixel Bunny kayıt bağlantı hatası: {str(e)}", "error", 20)
        return None, None

    if is_active and not is_active():
        return None, None

    if log_callback:
        log_callback("Pixel Bunny doğrulama e-postası bekleniyor...", "registering", 25)

    confirm_link = temp.getConfirmLink(email, timeout=40)
    if not confirm_link:
        if log_callback:
            log_callback("Pixel Bunny doğrulama e-postası zaman aşımına uğradı.", "error", 25)
        return None, None

    if is_active and not is_active():
        return None, None

    if log_callback:
        log_callback(f"Pixel Bunny onay linki yakalandı: {confirm_link}", "registering", 35)

    try:
        confirm_r = requests.get(confirm_link, allow_redirects=True, timeout=15)
        if log_callback:
            log_callback(f"Pixel Bunny e-postası başarıyla onaylandı (Durum: {confirm_r.status_code})", "registering", 40)
        return email, password
    except Exception as e:
        if log_callback:
            log_callback(f"Pixel Bunny onay linki tetiklenirken hata: {str(e)}", "error", 40)
        return None, None


# ===================== GÖRSEL ÜRETİMİ =====================
def run_image(
    prompt: str,
    model_name: str,
    aspect_ratio: str = "1:1",
    num_images: int = 1,
    tier: str = "standard",
    resolution: str = "",
    images: Optional[List[Any]] = None,
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    job_id: Optional[str] = None,
    is_active: Optional[Callable[[], bool]] = None
) -> Dict[str, Any]:
    """
    Pixel Bunny AI Resim Üretim Motoru.
    Görsel üretir ve üretilen görsellerin URL listesini döndürür.
    """
    if log_callback:
        log_callback("Pixel Bunny motoru hazırlanıyor...", "registering", 5)

    # 1. Kayıt Ol & E-posta Onayla
    email, password = register_pixelbunny(log_callback=log_callback, is_active=is_active)
    if not email:
        raise RuntimeError("Pixel Bunny hesap kaydı veya onaylama başarısız oldu.")

    if is_active and not is_active():
        return {"outputs": []}

    # 2. Giriş Yap
    if log_callback:
        log_callback("Pixel Bunny hesabına giriş yapılıyor...", "login", 45)

    login_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    login_headers = {
        "apikey": API_KEY,
        "content-type": "application/json;charset=UTF-8",
    }
    login_payload = {"email": email, "password": password}

    login_res = requests.post(login_url, headers=login_headers, json=login_payload, timeout=15)
    if login_res.status_code != 200:
        raise RuntimeError(f"Pixel Bunny giriş başarısız! {login_res.text}")

    login_data = login_res.json()
    access_token = login_data.get("access_token")
    user_id = login_data.get("user", {}).get("id")

    if log_callback:
        log_callback(f"Pixel Bunny girişi başarılı! User ID: {user_id}", "login", 50)

    if is_active and not is_active():
        return {"outputs": []}

    # 3. Referans Görselleri Yükle (varsa en fazla 3 adet)
    uploaded_image_urls = []
    if images:
        upload_url = f"{SUPABASE_URL}/functions/v1/upload-input"
        upload_headers = {
            "authorization": f"Bearer {access_token}",
            "origin": "https://pixelbunny.ai",
            "referer": "https://pixelbunny.ai/",
            "accept": "*/*",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        for idx, img in enumerate(images[:3]):
            if is_active and not is_active():
                return {"outputs": []}

            if log_callback:
                log_callback(f"Pixel Bunny referans görsel {idx+1} yükleniyor...", "uploading", 55 + idx * 5)

            files = None
            if isinstance(img, dict):
                # Bellekteki görsel sözlüğü: {'filename': ..., 'content': bytes, 'content_type': ...}
                f_name = img.get('filename') or f"image_{idx+1}.jpg"
                f_content = img.get('content')
                c_type = img.get('content_type') or 'image/jpeg'
                files = {"file": (f_name, io.BytesIO(f_content), c_type)}
            elif isinstance(img, str) and os.path.exists(img):
                with open(img, "rb") as f:
                    files = {"file": (os.path.basename(img), f.read(), "image/jpeg")}

            if files:
                try:
                    up_res = requests.post(upload_url, headers=upload_headers, files=files, timeout=25)
                    if up_res.status_code == 200:
                        url = up_res.json().get("url")
                        if url:
                            uploaded_image_urls.append(url)
                            if log_callback:
                                log_callback(f"Görsel {idx+1} yüklendi: {url}", "uploading", 60 + idx * 5)
                    else:
                        if log_callback:
                            log_callback(f"Görsel {idx+1} yükleme uyarısı (Kod: {up_res.status_code})", "warning", 60 + idx * 5)
                except Exception as up_err:
                    if log_callback:
                        log_callback(f"Görsel {idx+1} yükleme hatası: {str(up_err)}", "warning", 60 + idx * 5)

    if is_active and not is_active():
        return {"outputs": []}

    # 4. Üretimi Tetikle
    config = MODELS_CONFIG.get(model_name)
    if not config:
        config = {
            "model_id": model_name.lower().replace(" ", "-"),
            "resolution": resolution or "1K",
            "aspect_ratios": ["1:1"],
            "tiers": ["standard"]
        }

    gen_url = f"{SUPABASE_URL}/functions/v1/generate"
    gen_headers = {
        "authorization": f"Bearer {access_token}",
        "apikey": API_KEY,
        "content-type": "application/json",
        "origin": "https://pixelbunny.ai",
        "referer": "https://pixelbunny.ai/",
        "x-client-info": "supabase-js-web/2.98.0"
    }

    valid_tiers = config.get("tiers", ["standard"])
    chosen_tier = (tier or "").lower().strip()
    if chosen_tier not in [t.lower() for t in valid_tiers]:
        res_cand = (resolution or config.get("resolution", "")).lower()
        if res_cand in [t.lower() for t in valid_tiers]:
            chosen_tier = res_cand
        else:
            chosen_tier = valid_tiers[0]

    effective_resolution = resolution if resolution else config.get("resolution", "1K")
    if chosen_tier in ["1k", "2k", "4k"]:
        effective_resolution = chosen_tier.upper()

    effective_num_images = max(1, min(4, int(num_images or 1)))

    target_model_id = config.get("model_id")
    if target_model_id == "wan-2.7-image" and chosen_tier == "pro":
        target_model_id = "wan-2.7-image-pro"
    elif target_model_id == "qwen-image-2" and chosen_tier == "pro":
        target_model_id = "qwen-image-2-pro"

    gen_payload = {
        "generation_type": "image",
        "prompt": prompt,
        "num_images": effective_num_images,
        "aspect_ratio": aspect_ratio or "1:1",
        "resolution": effective_resolution,
        "tier": chosen_tier,
        "model_id": target_model_id
    }

    if uploaded_image_urls:
        gen_payload["image_urls"] = uploaded_image_urls

    if log_callback:
        log_callback(f"Pixel Bunny görsel üretimi tetikleniyor (Model: {model_name})...", "generating", 75)

    gen_res = requests.post(gen_url, headers=gen_headers, json=gen_payload, timeout=20)
    if gen_res.status_code != 200:
        raise RuntimeError(f"Pixel Bunny üretim tetikleme başarısız: {gen_res.text}")

    if log_callback:
        log_callback("Pixel Bunny üretim kuyruğa alındı. Sonuçlar bekleniyor...", "generating", 80)

    # 5. Durum Sorgulama (Polling)
    check_url = f"{SUPABASE_URL}/rest/v1/generations"
    check_params = {
        "select": "id,output_urls,thumbnail_url,prompt,metadata,generation_type,status,created_at,is_published,publish_status,error_message,model_id,credits_charged,user_id,publisher_nickname,local_only",
        "user_id": f"eq.{user_id}",
        "deleted_at": "is.null",
        "order": "created_at.desc",
        "offset": "0",
        "limit": "24"
    }
    check_headers = {
        "authorization": f"Bearer {access_token}",
        "apikey": API_KEY,
    }

    start_time = time.time()
    max_duration = 300  # 5 dakika

    while True:
        if is_active and not is_active():
            return {"outputs": []}

        if time.time() - start_time > max_duration:
            raise TimeoutError("Pixel Bunny üretim zaman aşımına uğradı (5 dakika limit doldu).")

        try:
            check_res = requests.get(check_url, headers=check_headers, params=check_params, timeout=12)
            if check_res.status_code == 200:
                data = check_res.json()
                if len(data) > 0:
                    latest = data[0]
                    status = latest.get("status")

                    if status == "completed":
                        outputs = latest.get("output_urls", [])
                        if log_callback:
                            log_callback("Pixel Bunny üretimi başarıyla tamamlandı!", "completed", 100)
                        return {"outputs": outputs, "metadata": latest}
                    elif status == "failed":
                        err_msg = latest.get("error_message") or "Bilinmeyen sunucu hatası"
                        raise RuntimeError(f"Pixel Bunny sunucu hatası: {err_msg}")
                    else:
                        if log_callback:
                            log_callback(f"Pixel Bunny üretim durumu: '{status}'. Bekleniyor...", "generating", 85)
                else:
                    if log_callback:
                        log_callback("Pixel Bunny durumu sorgulanıyor (Kuyruk başlatılıyor)...", "generating", 82)
            else:
                if log_callback:
                    log_callback(f"Pixel Bunny sorgu yanıtı: {check_res.status_code}. Tekrar deneniyor...", "warning", 83)
        except (requests.RequestException, ValueError) as poll_err:
            if log_callback:
                log_callback(f"Sorgulama hatası: {str(poll_err)}. Devam ediliyor...", "warning", 83)

        time.sleep(3)


# Geriye dönük uyumluluk / standalone kullanım
def generate_pixelbunny_image(
    email: str,
    password: str,
    image_paths: List[str] = None,
    prompt: str = "hello",
    model_name: str = "Qwen Image 2",
    aspect_ratio: str = "1:1",
    num_images: int = 1,
    tier: str = "standard"
):
    """Standalone / CLI kullanım fonksiyonu"""
    images_list = image_paths or []
    def _print_cb(msg, status, pct):
        print(f"[{status.upper()}] ({pct}%) {msg}")

    return run_image(
        prompt=prompt,
        model_name=model_name,
        aspect_ratio=aspect_ratio,
        num_images=num_images,
        tier=tier,
        images=images_list,
        log_callback=_print_cb
    )


if __name__ == "__main__":
    print("[*] Pixel Bunny Image Test Başlatılıyor...")
    res = run_image(
        prompt="A cute white fluffy bunny sitting in a fantasy flower meadow, 8k resolution, cinematic lighting",
        model_name="Wan 2.7",
        aspect_ratio="16:9",
        num_images=1,
        tier="standard",
        log_callback=lambda msg, status, pct: print(f"[{pct}%] {msg}")
    )
    print("\nSonuç:", res)
