#!/usr/bin/env python3
"""
================================================================================
🎬 MORPH STUDIO AI - SEEDANCE PRO FAST & GPT IMAGE 2.5 (SUNBURST / FLARE) 🎬
================================================================================
Bu modül PopVid, TopVid ve VibeVideo gibi dışarıdan aktarılabilir ve thread-safe
oturum havuzuna sahip bağımsız bir istemcidir.

Desteklenen Modeller:
1. Seedance Pro Fast (Video):
   - model_id: "seedance_v1_pro_fast"
   - Süre seçenekleri: 5, 10 saniye
   - Çözünürlük: 480p, 720p
   - Başlangıç referans görseli desteği
2. GPT Image 2.5 (Görsel):
   - model_id: "openai/gpt-image-2.5"
   - 2 Farklı Mod: "sunburst" ve "flare"
   - Çözünürlük: 1k, 2k, 4k
   - Kalite: low, medium
   - En-boy oranları: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9
   - Çoklu referans görsel (I2I) veya salt metin (T2I)
================================================================================
"""

import os
import re
import time
import base64
import random
import string
import threading
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

FALLBACK_1X1_JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA='
)

# ── Ortak Headers (Chromium / Web Session) ──────────────────────────────────
BASE_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://app.morphstudio.com",
    "priority": "u=1, i",
    "referer": "https://app.morphstudio.com/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}

GCS_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://app.morphstudio.com",
    "referer": "https://app.morphstudio.com/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}

DEFAULT_PASSWORD = "gAAAAABpxPNrzSpgynpZv_bnHzlIf--xIbpSHDNVbLKG6nsox_eUgWjgfoyXdTPe6gPw2ELclPktqE59ViIQB8WR2AoT2wUh2Q=="


# ==============================================================================
# 1. SPAMOK GEÇİCİ E-POSTA SERVİSİ
# ==============================================================================
class eTemp:
    @staticmethod
    def random_email(length: int = 15) -> str:
        return ''.join(
            random.SystemRandom().choice(string.ascii_lowercase + string.digits)
            for _ in range(length)
        )

    def get_email(self) -> str:
        return self.random_email(15) + '@spamok.com'

    def get_verify_link(self, mail: str, max_attempts: int = 30, log_callback=None) -> Optional[str]:
        username = mail.replace('@spamok.com', '')
        if log_callback:
            log_callback("SpamOK gelen kutusu taranıyor...", "registering", 20)

        for attempt in range(max_attempts):
            try:
                r = requests.get(f'https://api.spamok.com/v2/EmailBox/{username}', timeout=10)
                if r.status_code == 200:
                    mails = r.json().get('mails', [])
                    for m in mails:
                        subject = m.get('subject', '')
                        if 'Verify' in subject or 'Confirm' in subject:
                            mail_id = m['id']
                            detail = requests.get(f'https://api.spamok.com/v2/Email/{username}/{mail_id}', timeout=10)
                            if detail.status_code == 200:
                                html = detail.json().get('messageHtml', '')
                                soup = BeautifulSoup(html, 'html.parser')
                                for a in soup.find_all('a', href=True):
                                    href = a['href']
                                    if 'morphstudio.com/redirect-verify-email' in href:
                                        return href

                                match = re.search(
                                    r'(https://app\.morphstudio\.com/redirect-verify-email[^\s\'"<>]+)',
                                    html
                                )
                                if match:
                                    return match.group(1).strip()
            except Exception as e:
                print(f"[MorphStudio eTemp] Hata: {e}")

            if log_callback and (attempt + 1) % 5 == 0:
                pct = 20 + min(15, (attempt + 1))
                log_callback(f"Doğrulama maili bekleniyor... ({(attempt + 1) * 2}s)", "registering", pct)
            time.sleep(2)

        return None


# ==============================================================================
# 2. MORPH STUDIO İSTEMCİSİ
# ==============================================================================
class MorphStudioClient:
    def __init__(self):
        self.session = requests.Session()
        self.email: Optional[str] = None
        self.user_id: Optional[str] = None

    def signup_and_verify(self, log_callback=None) -> bool:
        def _log(msg, status="info", pct=None):
            print(f"[MorphStudioClient] {msg}")
            if log_callback:
                log_callback(msg, status, pct)

        temp = eTemp()
        email = temp.get_email()
        self.email = email
        _log(f"Geçici e-posta oluşturuldu: {email}", "registering", 15)

        # 1. Kayıt Ol
        _log("Morph Studio kayıt isteği gönderiliyor...", "registering", 18)
        reg_resp = self.session.post(
            "https://api.morphstudio.com/api/user/register",
            headers=BASE_HEADERS,
            json={"email": email, "password": DEFAULT_PASSWORD},
            timeout=15
        )
        if reg_resp.status_code not in (200, 201):
            _log(f"Kayıt isteği başarısız: {reg_resp.text}", "error", 20)
            return False

        user_id = reg_resp.json().get("userId")
        if not user_id:
            _log("Kayıt yanıtında userId bulunamadı.", "error", 20)
            return False
        self.user_id = user_id
        _log(f"Kullanıcı oluşturuldu! User ID: {user_id}", "registering", 22)

        # 2. Doğrulama E-postası Gönder
        _log("Aktivasyon maili gönderiliyor...", "registering", 25)
        send_resp = self.session.post(
            "https://api.morphstudio.com/api/user/send-verify-email",
            headers=BASE_HEADERS,
            json={"userId": user_id},
            timeout=15
        )
        if send_resp.status_code != 200:
            _log(f"Doğrulama maili gönderilemedi: {send_resp.text}", "error", 25)
            return False

        # 3. SpamOK'tan Doğrulama Linkini Al
        verify_link = temp.get_verify_link(email, max_attempts=30, log_callback=log_callback)
        if not verify_link:
            _log("Doğrulama e-postası zaman aşımına uğradı (SpamOK 30s limit doldu).", "error", 30)
            return False

        _log(f"Doğrulama linki yakalandı: {verify_link}", "registering", 40)

        # 4. Linkteki parametreleri ayrıştır ve doğrula
        parsed = urlparse(verify_link)
        params = parse_qs(parsed.query)

        verify_payload = {
            "email": unquote(params["email"][0]),
            "token": params["token"][0],
            "userId": params["userId"][0],
        }

        ver_resp = self.session.post(
            "https://api.morphstudio.com/api/user/verify-email",
            headers=BASE_HEADERS,
            json=verify_payload,
            timeout=15
        )
        if ver_resp.status_code != 200:
            _log(f"E-posta doğrulama yanıtı başarısız: {ver_resp.text}", "error", 45)
            return False

        _log("Morph Studio oturumu başarıyla doğrulandı ve aktifleştirildi.", "login", 50)
        return True

    def upload_image(self, file_path_or_bytes: Union[str, bytes], filename: str = "image.jpg", log_callback=None) -> Dict[str, str]:
        def _log(msg, status="info", pct=None):
            print(f"[MorphStudio Upload] {msg}")
            if log_callback:
                log_callback(msg, status, pct)

        if isinstance(file_path_or_bytes, str):
            if not os.path.exists(file_path_or_bytes):
                _log(f"Dosya bulunamadı: {file_path_or_bytes}", "error", 65)
                return {}
            filename = os.path.basename(file_path_or_bytes)
            with open(file_path_or_bytes, "rb") as f:
                file_data = f.read()
        else:
            file_data = file_path_or_bytes

        create_data = {}
        for attempt in range(3):
            try:
                create_resp = self.session.post(
                    "https://api.morphstudio.com/api/v1/storage/create",
                    headers=BASE_HEADERS,
                    json={"displayName": filename, "isPublic": True},
                    timeout=45
                )
                if create_resp.status_code == 200:
                    create_data = create_resp.json()
                    break
                else:
                    _log(f"Depolama yanıt uyarısı ({create_resp.status_code}): {create_resp.text}", "warning", 66)
            except Exception as up_e:
                _log(f"Depolama isteği zaman aşımı/hata ({up_e}), yeniden deneniyor ({attempt+1}/3)...", "warning", 66)
                time.sleep(2)

        if not create_data:
            _log("Depolama nesnesi oluşturulamadı.", "error", 68)
            return {}
        object_id = create_data.get("objectId")
        presigned = create_data.get("presigned", {})
        upload_url = presigned.get("url")
        fields = presigned.get("fields", {})

        if not object_id or not upload_url:
            _log("Presigned upload bilgisi eksik.", "error", 68)
            return {}

        content_type = "image/jpeg"
        if filename.lower().endswith(".png"):
            content_type = "image/png"

        upload_resp = requests.post(
            upload_url,
            headers=GCS_HEADERS,
            data=fields,
            files={"file": (filename, file_data, content_type)},
            timeout=30
        )
        if upload_resp.status_code not in (200, 204):
            _log(f"GCS dosya yükleme hatası: {upload_resp.text}", "error", 70)
            return {}

        key = fields.get("key")

        # Dosyayı CDN'de aktif hale getir
        self.session.get(
            f"https://api.morphstudio.com/api/v1/storage/{object_id}/info",
            headers=BASE_HEADERS,
            timeout=15
        )
        _log(f"Görsel başarıyla yüklendi (ID: {object_id})", "uploading", 72)
        return {"objectId": object_id, "key": key}

    def create_video(self, prompt: str, object_id: str = "", model_id: str = "seedance_v1_pro_fast", duration: int = 5, resolution: str = "480p", log_callback=None) -> dict:
        params = {
            "prompt": prompt,
            "duration": int(duration),
            "resolution": resolution,
        }
        if object_id:
            params["start_image_url"] = object_id

        payload = {
            "session_id": "",
            "model_id": model_id,
            "sessionType": "video",
            "params": params
        }

        if log_callback:
            log_callback(f"Video üretim isteği iletiliyor (Model: {model_id}, {duration}s, {resolution})...", "generating", 75)

        resp = self.session.post(
            "https://api.morphstudio.com/api/v1/moca/media_session/video/node/create",
            headers=BASE_HEADERS,
            json=payload,
            timeout=20
        )
        if resp.status_code != 200:
            if log_callback:
                log_callback(f"Video isteği hatası: {resp.text}", "error", 75)
            return {}
        return resp.json()

    def poll_video(self, node_id: str = None, timeout: int = 360, interval: int = 4, log_callback=None) -> Optional[str]:
        if log_callback:
            log_callback("Video işleme durumu takip ediliyor (Polling)...", "generating", 78)

        start_time = time.time()
        last_reported_pct = 0

        while time.time() - start_time < timeout:
            try:
                list_resp = self.session.get(
                    "https://api.morphstudio.com/api/v1/moca/media_session/video/list?limit=100",
                    headers=BASE_HEADERS,
                    timeout=15
                )
                if list_resp.status_code == 200:
                    data = list_resp.json()
                    for date, sessions_list in data.get("sessions", {}).items():
                        for s in sessions_list:
                            for node in s.get("recentNodes", []):
                                if node_id and node.get("external_id") != node_id and node.get("nodeId") != node_id and node.get("id") != node_id:
                                    continue

                                status = node.get("status", "")
                                cdn_url = node.get("cdn_url", "")
                                raw_progress = node.get("progress", {}).get("progress", 0)

                                pct = 78 + int(raw_progress * 0.21)
                                if pct > last_reported_pct:
                                    last_reported_pct = pct
                                    if log_callback:
                                        log_callback(f"Video işleniyor: %{raw_progress} (Durum: {status})", "generating", pct)

                                if status == "failed":
                                    err_msg = node.get("error_message") or "Bilinmeyen hata"
                                    if log_callback:
                                        log_callback(f"Video üretimi başarısız: {err_msg}", "error", 90)
                                    return None

                                if cdn_url or status == "finished":
                                    if cdn_url:
                                        if log_callback:
                                            log_callback(f"Video başarıyla üretildi!", "completed", 100)
                                        return cdn_url
            except Exception as e:
                print(f"[MorphStudio Video Polling] Hata: {e}")

            time.sleep(interval)

        if log_callback:
            log_callback("Video üretimi zaman aşımına uğradı.", "error", 90)
        return None

    def create_image(self, prompt: str, input_images: list = None, model_id: str = "openai/gpt-image-2.5", aspect_ratio: str = "1:1", mode: str = "sunburst", quality: str = "medium", resolution: str = "2k", log_callback=None) -> dict:
        params = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "mode": mode,
            "quality": quality,
            "resolution": resolution,
        }

        if input_images:
            media_inputs = []
            for idx, img in enumerate(input_images, start=1):
                key = img["key"]
                media_inputs.append({
                    "id": f"media-input-upload-{int(time.time() * 1000)}-{idx}",
                    "alias": f"fig{idx}",
                    "kind": "image",
                    "source_type": "url",
                    "source": f"https://morph-app-cmr-prod.morphstudio.com/{key}",
                    "role": "generic",
                    "order": idx
                })
            params["media_inputs_v2"] = media_inputs

        payload = {
            "session_id": "",
            "model_id": model_id,
            "params": params
        }

        if log_callback:
            img_info = f" ({len(input_images)} Referans Görsel)" if input_images else ""
            log_callback(f"Görsel üretim isteği iletiliyor (Model: {model_id}, Mod: {mode}, {resolution}, {quality}){img_info}...", "generating", 75)

        resp = self.session.post(
            "https://api.morphstudio.com/api/v1/moca/image_session/node/create",
            headers=BASE_HEADERS,
            json=payload,
            timeout=20
        )
        if resp.status_code != 200:
            if log_callback:
                log_callback(f"Görsel isteği hatası: {resp.text}", "error", 75)
            return {}
        return resp.json()

    def poll_image(self, node_id: str = None, timeout: int = 360, interval: int = 4, log_callback=None) -> List[str]:
        if log_callback:
            log_callback("Görsel işleme durumu takip ediliyor (Polling)...", "generating", 78)

        start_time = time.time()
        last_reported_pct = 0

        while time.time() - start_time < timeout:
            try:
                list_resp = self.session.get(
                    "https://api.morphstudio.com/api/v1/moca/image_session/list?limit=100",
                    headers=BASE_HEADERS,
                    timeout=15
                )
                if list_resp.status_code == 200:
                    data = list_resp.json()
                    for date, sessions_list in data.get("sessions", {}).items():
                        for s in sessions_list:
                            for node in s.get("recentNodes", []):
                                if node_id and node.get("external_id") != node_id and node.get("nodeId") != node_id and node.get("id") != node_id:
                                    continue

                                status = node.get("status", "")
                                raw_progress = node.get("progress", {}).get("progress", 0)

                                pct = 78 + int(raw_progress * 0.21)
                                if pct > last_reported_pct:
                                    last_reported_pct = pct
                                    if log_callback:
                                        log_callback(f"Görsel işleniyor: %{raw_progress} (Durum: {status})", "generating", pct)

                                if status == "failed":
                                    if log_callback:
                                        log_callback("Görsel üretimi başarısız oldu!", "error", 90)
                                    return []

                                urls = []
                                multi = node.get("multi_outputs")
                                if isinstance(multi, dict):
                                    urls = multi.get("cdn_urls", [])

                                if (status == "finished" or urls) and len(urls) > 0:
                                    if log_callback:
                                        log_callback(f"{len(urls)} görsel başarıyla hazırlandı!", "completed", 100)
                                    return urls
            except Exception as e:
                print(f"[MorphStudio Image Polling] Hata: {e}")

            time.sleep(interval)

        if log_callback:
            log_callback("Görsel üretimi zaman aşımına uğradı.", "error", 90)
        return []


# ==============================================================================
# 3. OTURUM HAVUZU (SESSION POOL)
# ==============================================================================
GLOBAL_CLIENT: Optional[MorphStudioClient] = None
CLIENT_LOCK = threading.Lock()


def get_or_create_client(log_callback=None) -> MorphStudioClient:
    """Mevcut oturum varsa onu kullanır, yoksa yeni hesap açar."""
    global GLOBAL_CLIENT
    with CLIENT_LOCK:
        if GLOBAL_CLIENT is not None and GLOBAL_CLIENT.user_id:
            if log_callback:
                log_callback(f"Mevcut Morph Studio hesabı kullanılıyor ({GLOBAL_CLIENT.email})...", "login", 20)
            return GLOBAL_CLIENT

        if log_callback:
            log_callback("Morph Studio oturumu oluşturuluyor...", "registering", 10)

        new_client = MorphStudioClient()
        if not new_client.signup_and_verify(log_callback=log_callback):
            raise RuntimeError("Morph Studio hesabı oluşturulamadı veya doğrulanamadı.")
        GLOBAL_CLIENT = new_client
        return GLOBAL_CLIENT


def create_new_client(log_callback=None) -> MorphStudioClient:
    """Zorla yeni bir Morph Studio hesabı açar ve global oturumu günceller."""
    global GLOBAL_CLIENT
    with CLIENT_LOCK:
        if log_callback:
            log_callback("Yeni Morph Studio hesabı oluşturuluyor...", "registering", 10)
        new_client = MorphStudioClient()
        if not new_client.signup_and_verify(log_callback=log_callback):
            raise RuntimeError("Morph Studio hesabı oluşturulamadı.")
        GLOBAL_CLIENT = new_client
        return GLOBAL_CLIENT


# ==============================================================================
# 4. FLASK ENTEGRASYON FONKSİYONLARI (RUN_VIDEO & RUN_IMAGE)
# ==============================================================================
def run_video(
    prompt: str,
    image_path: Optional[str] = None,
    model_id: str = "seedance_v1_pro_fast",
    duration: int = 5,
    resolution: str = "480p",
    log_callback=None
) -> Dict[str, Any]:
    """
    Seedance Pro Fast video üretimi fonksiyonu.
    Mevcut hesabı kullanır, hata durumunda yeni hesap açıp tekrar dener.
    """
    def _log(msg, status="info", pct=None):
        print(f"[run_video] {msg}")
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    _log("Morph Studio video motoru hazırlanıyor...", "registering", 10)
    client = get_or_create_client(log_callback=_log)

    object_id = ""
    if image_path and os.path.exists(image_path):
        _log(f"Referans görsel işleniyor: {image_path}", "uploading", 60)
        up_res = client.upload_image(image_path, log_callback=_log)
        if not up_res.get("objectId"):
            _log("Görsel yüklenemedi, yeni oturum ile tekrar deneniyor...", "registering", 20)
            client = create_new_client(log_callback=_log)
            up_res = client.upload_image(image_path, log_callback=_log)
        object_id = up_res.get("objectId", "")

    # Video modeli başlangıç karesi gerektiriyorsa ve kullanıcı vermediyse 1x1 geçerli JPEG yükle
    if not object_id:
        up_res = client.upload_image(FALLBACK_1X1_JPEG, filename="fallback.jpg", log_callback=_log)
        object_id = up_res.get("objectId", "")

    _log(f"Video oluşturma isteği gönderiliyor (Model: {model_id}, Süre: {duration}s, Çözünürlük: {resolution})...", "generating", 75)
    video_res = client.create_video(
        prompt=prompt,
        object_id=object_id,
        model_id=model_id,
        duration=duration,
        resolution=resolution,
        log_callback=_log
    )

    if not video_res or not video_res.get("nodeId"):
        _log("İstek başarısız veya oturum süresi dolmuş olabilir. Yeni hesap açılıp tekrar deneniyor...", "registering", 20)
        client = create_new_client(log_callback=_log)
        if image_path and os.path.exists(image_path):
            up_res = client.upload_image(image_path, log_callback=_log)
            object_id = up_res.get("objectId", "")
        else:
            up_res = client.upload_image(FALLBACK_1X1_JPEG, filename="fallback.jpg", log_callback=_log)
            object_id = up_res.get("objectId", "")

        video_res = client.create_video(
            prompt=prompt,
            object_id=object_id,
            model_id=model_id,
            duration=duration,
            resolution=resolution,
            log_callback=_log
        )

    if not video_res or not video_res.get("nodeId"):
        raise RuntimeError("Morph Studio video üretim isteği reddedildi.")

    node_id = video_res.get("nodeId")
    cdn_url = client.poll_video(node_id=node_id, timeout=360, interval=4, log_callback=_log)
    if not cdn_url:
        raise RuntimeError("Morph Studio video tamamlandı ancak URL alınamadı veya işlem başarısız oldu.")

    return {
        "output": cdn_url,
        "node_id": node_id,
        "model": model_id,
        "duration": duration,
        "resolution": resolution,
        "user_id": client.user_id
    }


def run_image(
    prompt: str,
    image_paths: Optional[List[str]] = None,
    model_id: str = "openai/gpt-image-2.5",
    mode: str = "sunburst",
    aspect_ratio: str = "1:1",
    quality: str = "medium",
    resolution: str = "2k",
    log_callback=None
) -> Dict[str, Any]:
    """
    GPT Image 2.5 (Sunburst veya Flare modu) görsel üretimi fonksiyonu.
    Mevcut hesabı kullanır, hata durumunda yeni hesap açıp tekrar dener.
    """
    def _log(msg, status="info", pct=None):
        print(f"[run_image] {msg}")
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    _log("Morph Studio görsel motoru hazırlanıyor...", "registering", 10)
    client = get_or_create_client(log_callback=_log)

    uploaded_images = []
    if image_paths:
        for idx, p in enumerate(image_paths):
            if os.path.exists(p):
                _log(f"Referans görsel {idx+1}/{len(image_paths)} yükleniyor: {os.path.basename(p)}", "uploading", 60 + idx * 4)
                up_res = client.upload_image(p, log_callback=_log)
                if up_res.get("objectId") and up_res.get("key"):
                    uploaded_images.append({"objectId": up_res["objectId"], "key": up_res["key"]})

    _log(f"Görsel üretim isteği gönderiliyor (Model: {model_id}, Mod: {mode}, Oran: {aspect_ratio}, Kalite: {quality}, Çözünürlük: {resolution})...", "generating", 75)
    image_res = client.create_image(
        prompt=prompt,
        input_images=uploaded_images if uploaded_images else None,
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        mode=mode,
        quality=quality,
        resolution=resolution,
        log_callback=_log
    )

    if not image_res or not image_res.get("nodeId"):
        _log("İstek başarısız veya oturum süresi dolmuş olabilir. Yeni hesap açılıp tekrar deneniyor...", "registering", 20)
        client = create_new_client(log_callback=_log)
        uploaded_images = []
        if image_paths:
            for p in image_paths:
                if os.path.exists(p):
                    up_res = client.upload_image(p, log_callback=_log)
                    if up_res.get("objectId") and up_res.get("key"):
                        uploaded_images.append({"objectId": up_res["objectId"], "key": up_res["key"]})
        image_res = client.create_image(
            prompt=prompt,
            input_images=uploaded_images if uploaded_images else None,
            model_id=model_id,
            aspect_ratio=aspect_ratio,
            mode=mode,
            quality=quality,
            resolution=resolution,
            log_callback=_log
        )

    if not image_res or not image_res.get("nodeId"):
        raise RuntimeError("Morph Studio görsel üretim isteği reddedildi.")

    node_id = image_res.get("nodeId")
    cdn_urls = client.poll_image(node_id=node_id, timeout=360, interval=4, log_callback=_log)
    if not cdn_urls:
        raise RuntimeError("Morph Studio görsel tamamlandı ancak URL alınamadı veya işlem başarısız oldu.")

    return {
        "outputs": cdn_urls,
        "node_id": node_id,
        "model": model_id,
        "mode": mode,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "resolution": resolution,
        "user_id": client.user_id
    }
