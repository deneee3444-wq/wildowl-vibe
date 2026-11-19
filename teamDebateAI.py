#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
🎬 Team Debate AI Video İstemci Modülü & Otomatik Hesap Havuzu (P-Video-2-Pro) 🎬
================================================================================
Model: PrunaAI P-Video-2-Pro (Sesli & Çok Modlu Referans Destekli Video Modeli)
Desteklenen Özellikler:
  - txt2vid (Sadece metin istemi)
  - img2vid (Başlangıç karesi / First Frame)
  - First + Last Frame (Başlangıç ve Bitiş karesi ile interpolasyon)
  - ref2vid (Görsel, Ses ve Video referansları)
  - Çözünürlük: 480p, 768p
  - En-Boy Oranı: 16:9, 9:16
  - Süre: 5 - 15 Saniye
================================================================================
"""

import os
import re
import sys
import time
import random
import string
import mimetypes
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

import requests

API_BASE = "https://api.teamdebate.ai"
TOOL_KEY = "p_video_2_pro"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate",
    "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://teamdebate.ai",
    "referer": "https://teamdebate.ai/",
    "sec-ch-ua": '"Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
}

# ==============================================================================
# QTP MAIL (qtpmail.com) ENTEGRASYONU & PROXY AYARLARI (Gömülü / Self-Contained)
# ==============================================================================
WHITELIST_DOMAINS = [
    "080080568.xyz",
    "080080789.xyz",
    "080080888.xyz",
    "080080999.xyz",
    "gugia.com",
    "qtpmail.com",
]

# PROXY_MODE:
#   1 -> Webshare proxy üzerinden bağlanır (IP rate-limit engellerini aşar).
#   0 -> Proxy devre dışı kalır, doğrudan yerel/sunucu IP'si ile bağlanır.
PROXY_MODE = 1

PROXY_CONFIG = {
    "http": "http://nrrbciri-rotate:5cauzsujeluf@p.webshare.io:80",
    "https": "http://nrrbciri-rotate:5cauzsujeluf@p.webshare.io:80",
}


class QTMailClient:
    """QTP Mail (qtpmail.com) API İstemcisi"""

    BASE_URL = "https://qtpmail.com"

    def __init__(
        self,
        domain: Optional[str] = None,
        proxy_mode: int = PROXY_MODE,
        proxy_config: Optional[dict] = None,
    ):
        self.domain = domain
        self.address = None
        self.token = None
        self.expires_at = None
        self._seen_ids = set()
        self.proxy_mode = proxy_mode
        self.proxy_config = proxy_config if proxy_config is not None else PROXY_CONFIG

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        })

        if self.proxy_mode == 1 and self.proxy_config:
            self.session.proxies.update(self.proxy_config)

    def get_email(self, domain: Optional[str] = None) -> Optional[str]:
        target_domain = domain or self.domain
        if not target_domain:
            target_domain = WHITELIST_DOMAINS[0] if WHITELIST_DOMAINS else "080080568.xyz"

        url = f"{self.BASE_URL}/api/mailboxes"
        max_retries = 3 if self.proxy_mode == 1 else 0
        resp = None

        for attempt in range(max_retries + 1):
            payload = {
                "requestId": str(uuid.uuid4()),
                "domain": target_domain,
            }
            try:
                resp = self.session.post(url, json=payload, timeout=15)
                if resp.status_code == 429:
                    if self.proxy_mode == 1 and attempt < max_retries:
                        time.sleep(1)
                        self.session.close()
                        if self.proxy_config:
                            self.session.proxies.update(self.proxy_config)
                        continue
                    return None

                resp.raise_for_status()
                break
            except Exception:
                if self.proxy_mode == 1 and attempt < max_retries:
                    time.sleep(1)
                    continue
                return None

        if resp is None or not resp.ok:
            return None

        data = resp.json()
        self.address = data.get("address")
        self.token = data.get("token")
        self.expires_at = data.get("expiresAt")
        self.domain = target_domain
        self._seen_ids.clear()
        return self.address

    def get_messages(self) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        headers = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(f"{self.BASE_URL}/api/messages", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("messages", [])

    def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        if not self.token:
            return {}
        headers = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(f"{self.BASE_URL}/api/messages/{message_id}", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _extract_code(self, text: str, detail_otp: Optional[str] = None, html: Optional[str] = None) -> Optional[str]:
        # 1. HTML içinde letter-spacing veya 6 haneli kod (Team Debate vb. e-postalar için)
        if html:
            m_ls = re.search(r'letter-spacing[^>]*>\s*(?:&nbsp;|\s)*(\d{4,8})', html)
            if m_ls:
                return m_ls.group(1).strip()
            six_codes = [c for c in re.findall(r'\b\d{6}\b', html) if not c.startswith(('2024', '2025', '2026'))]
            if six_codes:
                return six_codes[0]

        # 2. detail_otp eğer telif yılı (2024 vb.) değilse doğrudan kullan
        if detail_otp and str(detail_otp).strip() not in ("2024", "2025", "2026"):
            return str(detail_otp).strip()

        # 3. Metin içinde 6 haneli kodlar
        if text:
            six_codes = [c for c in re.findall(r'\b\d{6}\b', text) if not c.startswith(('2024', '2025', '2026'))]
            if six_codes:
                return six_codes[0]

        # 4. Genel 4-8 haneli kodlar (yılları filtreleyerek)
        all_text = (text or "") + " " + (html or "")
        if all_text.strip():
            codes = [c for c in re.findall(r'\b\d{4,8}\b', all_text) if c not in ("2024", "2025", "2026")]
            if codes:
                return codes[0]

        return str(detail_otp).strip() if detail_otp else None

    def wait_for_code(self, timeout: int = 90, interval: int = 2) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                messages = self.get_messages()
                for msg in messages:
                    msg_id = str(msg.get("id"))
                    if msg_id not in self._seen_ids:
                        self._seen_ids.add(msg_id)
                        detail = self.get_message_detail(msg_id)
                        otp = detail.get("otp")
                        html_body = detail.get("html_body") or detail.get("html") or ""
                        text_body = detail.get("text_body") or detail.get("text") or ""
                        content = html_body + "\n" + text_body
                        code = self._extract_code(content, detail_otp=otp, html=html_body)
                        if code:
                            return code
            except Exception:
                pass
            time.sleep(interval)
        return None

    def delete_mailbox(self) -> bool:
        if not self.token:
            return False
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = self.session.delete(f"{self.BASE_URL}/api/mailbox", headers=headers, timeout=10)
            return resp.status_code in (200, 204)
        except Exception:
            return False


def register_account(log_callback: Optional[Callable[[str, str, int], None]] = None) -> Optional[str]:
    """Her video işlemi için QTP Mail ile sıfırdan hesap açıp OTP doğrulamasıyla access_token alır."""
    if log_callback:
        log_callback("Team Debate için geçici e-posta alınıyor (QTP Mail)...", "registering", 8)

    mail_client = QTMailClient(proxy_mode=PROXY_MODE, proxy_config=PROXY_CONFIG)
    email = mail_client.get_email()
    if not email:
        if log_callback:
            log_callback("QTP Mail ile geçici e-posta oluşturulamadı!", "error", 10)
        return None

    prefix = email.split("@")[0].replace(".", "_")
    username = f"u_{prefix}"
    password = "Wenke500@"

    if log_callback:
        log_callback(f"Kayıt isteği gönderiliyor ({email})...", "registering", 12)

    url = f"{API_BASE}/auth/register-and-subscribe"
    payload = {
        "email": email,
        "username": username,
        "password": password,
        "subscription_plan_id": 1
    }
    h = {**HEADERS, "content-type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=h, timeout=25)
        data = resp.json()
    except Exception as e:
        if log_callback:
            log_callback(f"Kayıt bağlantı hatası: {e}", "error", 15)
        return None

    # Doğrudan token döndüyse
    if "access_token" in data:
        if log_callback:
            log_callback("Hesap başarıyla aktifleştirildi!", "registering", 20)
        return data["access_token"]

    verification_token = data.get("verification_token")
    if not verification_token:
        err_msg = data.get("message") or data.get("error") or str(data)
        if log_callback:
            log_callback(f"Doğrulama belirteci alınamadı: {err_msg}", "error", 15)
        print(f"[-] Team Debate kayıt hatası: {data}", flush=True)
        return None

    if log_callback:
        log_callback("Gelen kutusundan OTP doğrulama kodu bekleniyor...", "registering", 16)

    otp = mail_client.wait_for_code(timeout=90, interval=2)
    if not otp:
        if log_callback:
            log_callback("OTP kodu zaman aşımına uğradı!", "error", 18)
        return None

    if log_callback:
        log_callback(f"OTP Kodu alındı ({otp}), hesap onaylanıyor...", "registering", 20)

    verify_url = f"{API_BASE}/auth/verify-otp"
    verify_payload = {
        "email": email,
        "verification_token": verification_token,
        "otp": otp
    }

    try:
        v_resp = requests.post(verify_url, json=verify_payload, headers=h, timeout=25)
        v_data = v_resp.json()
        token = v_data.get("access_token")
        if token:
            if log_callback:
                log_callback("Hesap başarıyla doğrulandı ve aktifleştirildi!", "registering", 22)
            return token
        else:
            err_msg = v_data.get("message") or v_data.get("error") or str(v_data)
            if log_callback:
                log_callback(f"OTP doğrulama reddedildi: {err_msg}", "error", 22)
            return None
    except Exception as e:
        if log_callback:
            log_callback(f"OTP onay hatası: {e}", "error", 22)
        return None

def upload_reference_media(
    token: str,
    file_path_or_url: str,
    media_kind: str = "image",
    log_callback: Optional[Callable[[str, str, int], None]] = None
) -> Optional[str]:
    """Yerel dosya ise Team Debate API'ye yükler, URL ise doğrudan döndürür."""
    val = str(file_path_or_url or "").strip().strip('"').strip("'")
    if not val:
        return None
    if val.startswith("http://") or val.startswith("https://"):
        return val

    if not os.path.exists(val):
        print(f"[-] Referans dosya bulunamadı: {val}")
        return None

    mime_type, _ = mimetypes.guess_type(val)
    if not mime_type:
        mime_map = {"image": "image/jpeg", "video": "video/mp4", "audio": "audio/mpeg"}
        mime_type = mime_map.get(media_kind, "application/octet-stream")

    filename = os.path.basename(val)
    if log_callback:
        log_callback(f"Medya yükleniyor: {filename} ({media_kind})...", "registering", 25)

    url = f"{API_BASE}/media/reference-upload"
    h = {"authorization": f"Bearer {token}", **HEADERS}

    try:
        with open(val, "rb") as f:
            files = {"file": (filename, f, mime_type)}
            data = {"tool_key": TOOL_KEY, "media_kind": media_kind}
            resp = requests.post(url, headers=h, files=files, data=data, timeout=90)
            res_json = resp.json()
            if resp.status_code == 200 and res_json.get("ok"):
                return res_json["media"]["url"]
            else:
                print(f"[!] Medya yükleme hatası: {resp.text}")
                return None
    except Exception as e:
        print(f"[!] Medya yüklenirken istisna: {e}")
        return None

def run_video(
    prompt: str,
    images: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "480p",
    model: str = "p_video_2_pro",
    negative_prompt: str = "",
    seed: Optional[Union[int, str]] = None,
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
    Team Debate AI (P-Video-2-Pro) Video Üretim Fonksiyonu.
    Desteklenen Modlar:
      - txt2vid: images boş, prompt ile doğrudan üretim.
      - img2vid: ref_mode == 'frames' ve 1 görsel verilirse başlangıç karesi (first frame) olur.
      - Start + End Frame: ref_mode == 'frames' ve 2 görsel verilirse ilk ve son kare olur.
      - ref2vid: ref_mode == 'gallery' veya 'media' ile görseller, ses veya video referansları bağlanır.
    """
    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 1. Süre, Çözünürlük ve En-Boy Oranı Normalizasyonu
    try:
        duration_int = int(duration)
        if duration_int < 5 or duration_int > 15:
            duration_int = 5
    except (ValueError, TypeError):
        duration_int = 5

    res_choice = "768p" if str(resolution).strip().lower() in ["768p", "720p", "high"] else "480p"
    ar_choice = "9:16" if str(aspect_ratio).strip() in ["9:16", "portrait"] else "16:9"

    # Seed
    seed_val = None
    if seed is not None and str(seed).strip() != "" and str(seed).strip() != "-1":
        try:
            seed_val = int(seed)
        except ValueError:
            pass

    # 2. Yeni Hesap Oluştur (Temp Mail + OTP)
    token = register_account(log_callback=log_callback)
    if not token:
        raise RuntimeError("Team Debate AI hesabı açılamadı veya doğrulanamadı!")

    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 3. Medya ve Referansların Yüklenmesi
    if log_callback:
        log_callback("Referans ve kare medyaları hazırlanıyor...", "registering", 26)

    start_image_url = None
    end_image_url = None
    ref_image_urls: List[str] = []
    ref_video_urls: List[str] = []
    ref_audio_urls: List[str] = []

    valid_images = [img for img in (images or []) if img and (os.path.isfile(img) or str(img).startswith("http"))]

    if ref_mode == "frames":
        # Keyframe Modu: 1. resim Start Frame, 2. resim End Frame
        if len(valid_images) >= 1:
            start_image_url = upload_reference_media(token, valid_images[0], "image", log_callback)
        if len(valid_images) >= 2:
            end_image_url = upload_reference_media(token, valid_images[1], "image", log_callback)
    else:
        # Gallery veya Media Modu: Resimler reference_images olarak gönderilir
        for img in valid_images[:9]:
            u = upload_reference_media(token, img, "image", log_callback)
            if u:
                ref_image_urls.append(u)

        # Eğer tek resim varsa ve start_image olarak da kullanılmak istenirse:
        if len(valid_images) == 1 and not start_image_url:
            start_image_url = ref_image_urls[0] if ref_image_urls else None

    # Harici Ses Referansı
    effective_audio = audio_path if (audio_path and os.path.exists(audio_path)) else audio_url
    if effective_audio:
        a_u = upload_reference_media(token, effective_audio, "audio", log_callback)
        if a_u:
            ref_audio_urls.append(a_u)

    # Harici Video Referansı
    effective_video = video_path if (video_path and os.path.exists(video_path)) else video_url
    if effective_video:
        v_u = upload_reference_media(token, effective_video, "video", log_callback)
        if v_u:
            ref_video_urls.append(v_u)

    # 4. Sahne (Scene) ve Görev Yükü Oluşturma
    scene: Dict[str, Any] = {
        "index": 0,
        "duration": duration_int,
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "reference_images": ref_image_urls,
        "reference_videos": ref_video_urls,
        "reference_audios": ref_audio_urls,
    }

    if seed_val is not None:
        scene["seed"] = seed_val
    if start_image_url:
        scene["image_url"] = start_image_url
    if end_image_url:
        scene["end_image_url"] = end_image_url

    base_payload = {
        "tool_key": TOOL_KEY,
        "scenes": [scene],
        "aspect_ratio": ar_choice,
        "resolution": res_choice,
    }

    req_headers = {
        **HEADERS,
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "x-session-id": str(uuid.uuid4())
    }

    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 5. Kredi Maliyeti Hesabı (Quote)
    if log_callback:
        log_callback("Video kredi maliyeti hesaplanıyor...", "registering", 30)

    quote_url = f"{API_BASE}/long-video-studio/run"
    expected_credits = 20
    try:
        q_resp = requests.post(quote_url, headers=req_headers, json={**base_payload, "quote_only": True}, timeout=25)
        q_data = q_resp.json()
        if q_data.get("ok"):
            expected_credits = (
                q_data.get("result", {}).get("quote", {}).get("credits")
                or q_data.get("quote", {}).get("credits")
                or 20
            )
    except Exception as e:
        print(f"[!] Quote hatası: {e}")

    # 6. Üretim Görevini Başlat
    if log_callback:
        log_callback(f"Video üretimi başlatılıyor (Kredi: {expected_credits})...", "processing", 35)

    run_payload = {**base_payload, "expected_credits": expected_credits}
    try:
        run_resp = requests.post(quote_url, headers=req_headers, json=run_payload, timeout=25)
        run_data = run_resp.json()
    except Exception as e:
        raise RuntimeError(f"Video üretim isteği başarısız: {e}")

    if not run_data.get("ok"):
        raise RuntimeError(f"Team Debate API Hatası: {run_resp.text}")

    tool_run_id = run_data.get("result", {}).get("tool_run_id")
    if not tool_run_id:
        raise RuntimeError(f"Tool run ID alınamadı: {run_data}")

    if log_callback:
        log_callback(f"Görev başlatıldı (ID: {tool_run_id}), render ediliyor...", "processing", 40)

    # 7. Polling Loop (Durum Takibi)
    status_url = f"{API_BASE}/long-video-studio/run-status/{tool_run_id}"
    start_time = time.time()
    last_prog = 0

    while True:
        if is_active and not is_active():
            return {"error": "İşlem iptal edildi."}

        time.sleep(3)
        try:
            s_resp = requests.get(status_url, headers=req_headers, timeout=25)
            s_data = s_resp.json()
        except Exception:
            continue

        status = str(s_data.get("status") or "").lower()
        progress = s_data.get("progress") or 0
        stage = s_data.get("stage") or "processing"

        # İlerlemeyi 40 - 95 arasına eşle
        mapped_pct = int(40 + (progress * 0.55))
        if mapped_pct > last_prog:
            last_prog = mapped_pct
            if log_callback:
                log_callback(f"P-Video render ediliyor... %{progress} ({stage})", "processing", mapped_pct)

        if status == "completed":
            scenes = (
                s_data.get("scenes")
                or s_data.get("result", {}).get("scenes")
                or []
            )

            provider_video_url = None
            scene_video_url = None
            if scenes and len(scenes) > 0:
                first_scene = scenes[0]
                provider_video_url = first_scene.get("provider_video_url")
                scene_video_url = first_scene.get("video_url")

            final_video_url = (
                s_data.get("result", {}).get("video_url")
                or s_data.get("video_url")
                or scene_video_url
                or provider_video_url
            )
            credits_val = s_data.get("credits")

            # Konsola sadece talep edilen temiz çıktı
            print("\n" + "=" * 50)
            print(f"Provider URL: {provider_video_url or final_video_url}")
            print(f"Kredi: {credits_val}")
            print("=" * 50)

            if log_callback:
                log_callback("Video üretimi başarıyla tamamlandı!", "completed", 100)

            return {
                "output": provider_video_url or final_video_url,
                "provider_video_url": provider_video_url,
                "video_url": final_video_url,
                "credits": credits_val,
                "request_id": str(tool_run_id),
                "model": model,
                "status": "completed"
            }

        elif status in ("failed", "cancelled", "timeout", "partial_failed"):
            err_msg = s_data.get("error") or s_data.get("result", {}).get("error") or status
            raise RuntimeError(f"Video üretimi başarısız oldu: {err_msg}")
