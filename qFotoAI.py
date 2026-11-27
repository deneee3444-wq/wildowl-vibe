#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
🎬 qFoto AI Video İstemci Modülü & Otomatik Hesap Motoru (qfoto-ai.com) 🎬
================================================================================
- Her görev için bağımsız taze Spamok hesabı açılır (tek hesap, tek kullanım).
- Eşzamanlı (paralel) görev yürütmeyi tam destekler.
- Prompt Geliştirme (Prompt Expansion) desteği:
    * Açık  (True)  -> enhance_level: 5 (Audio Motion Model - With Prompt Expansion)
    * Kapalı (False) -> enhance_level: 6 (Audio Motion Model - No Prompt Expansion)
- Negatif prompt desteği.
- Süre seçenekleri: 5, 10, 15 saniye.
- Filigran silme adımı bulunmaz, orijinal üretilen video doğrudan teslim edilir.
================================================================================
"""

import os
import re
import sys
import time
import uuid
import json
import random
import string
import base64
import mimetypes
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import unquote

import requests

BASE_URL = "https://qfoto-ai.com"
SPAMOK_URL = "https://api.spamok.com/v2"
OCR_SPACE_API_KEY = "K8592928255784488957"

SPAMOK_HEADERS = {
    "accept": "*/*",
    "origin": "https://spamok.com",
    "referer": "https://spamok.com/",
    "x-asdasd-platform-id": "blazor-en-us",
    "x-asdasd-platform-version": "blazor-1.0.0",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36",
}

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_spamok_local() -> str:
    """Rakamla başlamayan 10 karakterli random spamok kullanıcı adı üretir."""
    first = random.choice(string.ascii_lowercase)
    rest = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return first + rest


def generate_password() -> str:
    return (
        random.choice(string.ascii_uppercase)
        + "".join(random.choices(string.ascii_lowercase, k=5))
        + "".join(random.choices(string.digits, k=3))
        + "@"
    )


def xsrf_headers(session: requests.Session, referer: str) -> dict:
    token = unquote(session.cookies.get("XSRF-TOKEN", ""))
    return {
        "accept": "application/json, text/plain, */*",
        "origin": BASE_URL,
        "referer": referer,
        "x-xsrf-token": token,
    }


def solve_captcha_ocr_space(img_b64: str) -> str:
    """OCR.space API kullanarak base64 captcha görselini çözer (3 karakter)."""
    url = "https://api.ocr.space/parse/image"
    data = {
        "apikey": OCR_SPACE_API_KEY,
        "base64Image": "data:image/png;base64," + img_b64,
        "language": "eng",
        "OCREngine": "2",
        "scale": "true",
    }
    resp = requests.post(url, data=data, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    parsed_results = result.get("ParsedResults", [])
    if parsed_results:
        raw_text = parsed_results[0].get("ParsedText", "")
        code = re.sub(r"[^a-zA-Z0-9]", "", raw_text).strip().lower()
        return code
    return ""


def wait_for_verify_url(local: str, timeout: int = 60, interval: int = 3, log_callback=None) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{SPAMOK_URL}/EmailBox/{local}", headers=SPAMOK_HEADERS, timeout=15)
            if resp.status_code == 200:
                mails = resp.json().get("mails", [])
                if mails:
                    mail_id = mails[0]["id"]
                    detail = requests.get(
                        f"{SPAMOK_URL}/Email/{local}/{mail_id}",
                        headers=SPAMOK_HEADERS,
                        timeout=15,
                    )
                    if detail.status_code == 200:
                        html_content = detail.json().get("messageHtml", "")
                        match = re.search(r"https://qfoto-ai\.com/verify/[A-Za-z0-9_-]+", html_content)
                        if match:
                            return match.group(0)
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError("qFoto doğrulama maili zamanında gelmedi.")


def create_qfoto_account(log_callback=None) -> tuple:
    """
    Taze bir qFoto hesabı oluşturur, e-postasını onaylar ve oturum açar.
    Dönüş: (session, token, user_info)
    """
    def _log(msg, status="registering", pct=None):
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    session = requests.Session()
    session.headers.update({
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36"
    })

    _log("qFoto oturumu başlatılıyor...", "registering", 10)
    session.get(f"{BASE_URL}/register", timeout=15).raise_for_status()

    local = generate_spamok_local()
    email = f"{local}@spamok.com"
    password = generate_password()
    name = "User " + local[:5].capitalize()

    _log(f"Geçici e-posta oluşturuldu: {email}", "registering", 15)

    # Captcha & Kayıt
    attempt = 1
    max_attempts = 15
    while attempt <= max_attempts:
        _log(f"Captcha alınıyor ve çözülüyor (Deneme #{attempt})...", "registering", 20)
        cap_resp = session.get(
            f"{BASE_URL}/captcha/api/default",
            headers=xsrf_headers(session, f"{BASE_URL}/register"),
            timeout=15,
        )
        cap_resp.raise_for_status()
        cap_data = cap_resp.json()
        img_b64 = cap_data["img"].split(",", 1)[1]

        try:
            captcha_code = solve_captcha_ocr_space(img_b64)
        except Exception:
            captcha_code = ""

        if len(captcha_code) != 3:
            time.sleep(1)
            attempt += 1
            continue

        reg_resp = session.post(
            f"{BASE_URL}/register",
            headers=xsrf_headers(session, f"{BASE_URL}/register"),
            json={
                "name": name,
                "email": email,
                "password": password,
                "password_check": password,
                "captcha": captcha_code,
                "key": cap_data["key"],
            },
            timeout=15,
        )

        if reg_resp.status_code == 200:
            _log("Kayıt başarılı, e-posta onayı bekleniyor...", "registering", 30)
            break
        else:
            time.sleep(1)
            attempt += 1

    if attempt > max_attempts:
        raise RuntimeError("qFoto kayıt captcha aşaması tamamlanamadı.")

    # Doğrulama mailini bekle
    verify_url = wait_for_verify_url(local, timeout=60, log_callback=log_callback)
    session.get(verify_url, timeout=15).raise_for_status()
    _log("E-posta başarıyla doğrulandı!", "registering", 40)

    # Giriş yap
    _log("qFoto hesabına giriş yapılıyor...", "registering", 45)
    login_resp = session.post(
        f"{BASE_URL}/login",
        headers=xsrf_headers(session, f"{BASE_URL}/login"),
        json={"email": email, "password": password},
        timeout=15,
    )
    login_resp.raise_for_status()
    login_data = login_resp.json()
    user_info = login_data.get("user", {})
    token = user_info.get("token")
    if not token:
        raise RuntimeError("qFoto oturum açma token'ı alınamadı.")

    _log(f"Oturum açıldı (Başlangıç Puanı: {user_info.get('point', 60)})", "registering", 50)
    return session, token, user_info


def prepare_image_data_uri(image_source: Union[str, bytes], content_type: Optional[str] = None) -> str:
    """Görsel kaynağını (yerel yol, URL veya bytes) data URI formatına çevirir."""
    if isinstance(image_source, bytes):
        mime = content_type or "image/jpeg"
        b64 = base64.b64encode(image_source).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    if isinstance(image_source, str):
        if image_source.startswith("http://") or image_source.startswith("https://"):
            resp = requests.get(image_source, timeout=30)
            resp.raise_for_status()
            img_bytes = resp.content
            ct = resp.headers.get("Content-Type", "")
            if "image/" in ct:
                mime = ct.split(";")[0].strip()
            else:
                mime, _ = mimetypes.guess_type(image_source)
                mime = mime or "image/jpeg"
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return f"data:{mime};base64,{b64}"
        else:
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"Görsel dosyası bulunamadı: {image_source}")
            mime, _ = mimetypes.guess_type(image_source)
            mime = mime or "image/jpeg"
            with open(image_source, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{b64}"

    raise ValueError("Desteklenmeyen görsel formatı.")


def run_video(
    prompt: str = "hello",
    image_path: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    images: Optional[List[Any]] = None,
    duration: Union[int, str] = 5,
    enable_prompt_expansion: bool = True,
    negative_prompt: str = "",
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    output_dir: Optional[str] = None,
    is_active: Optional[Callable[[], bool]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    qFoto AI üzerinde sıfırdan video üretimi gerçekleştirir.
    Her çağrı için taze bir hesap açılır (tam eşzamanlı / thread-safe).

    Parametreler:
        prompt: Video promptu
        image_path: Yerel dosya yolu veya web URL'si
        image_bytes: Bellekteki görsel bayt verisi
        images: Görsel listesi (ilk eleman kullanılır)
        duration: Süre (5, 10 veya 15 saniye)
        enable_prompt_expansion: True -> enhance_level: 5 (Audio Motion - Genişletme Açık)
                                 False -> enhance_level: 6 (Audio Motion - Genişletme Kapalı)
        negative_prompt: Negatif prompt
        log_callback: Log durum bildirimi fonksiyonu (msg, status, percent)
        output_dir: Videonun kaydedileceği klasör (None ise varsayılan outputs/)
    """
    def _log(msg, status="info", pct=None):
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 1. Görsel kaynağını belirle
    img_source = None
    content_type = None
    if image_bytes:
        img_source = image_bytes
    elif image_path:
        img_source = image_path
    elif images and len(images) > 0:
        first = images[0]
        if isinstance(first, dict):
            img_source = first.get("content") or first.get("path")
            content_type = first.get("content_type")
        else:
            img_source = first

    if not img_source:
        # Fallback test görseli kontrolü
        test_jpg = os.path.join(CURRENT_DIR, "test.jpg")
        if os.path.exists(test_jpg):
            img_source = test_jpg
        else:
            raise ValueError("Video üretimi için geçerli bir görsel (image_path veya image_bytes) sağlanmalıdır.")

    # 2. Yeni qFoto hesabı oluştur
    _log("qFoto servisi için yeni hesap oluşturuluyor...", "registering", 10)
    session, token, user_info = create_qfoto_account(log_callback=log_callback)

    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 3. Görseli yükle
    _log("Referans görsel sunucuya yükleniyor...", "uploading", 55)
    data_uri = prepare_image_data_uri(img_source, content_type=content_type)

    auth_headers = xsrf_headers(session, f"{BASE_URL}/creation-video/img2video")
    auth_headers["authorization"] = f"Bearer {token}"
    auth_headers["content-type"] = "application/json;charset=UTF-8"

    upload_resp = session.post(
        f"{BASE_URL}/api/user-input-face",
        headers=auth_headers,
        json={"face_image": data_uri},
        timeout=30,
    )
    upload_resp.raise_for_status()
    face_data = upload_resp.json()
    face_image_id = face_data["user_input_face_image"]["id"]

    if is_active and not is_active():
        return {"error": "İşlem iptal edildi."}

    # 4. Süre ve Enhance Model seviyesini ayarla
    try:
        dur_val = int(duration)
        if dur_val not in [5, 10, 15]:
            dur_val = 5
    except Exception:
        dur_val = 5

    # Kullanıcı isteği: Prompt Genişletme (Prompt Expansion)
    # Açık ise -> enhance_level: 5 (Audio Motion Model With Prompt Expansion)
    # Kapalı ise -> enhance_level: 6 (Audio Motion Model No Prompt Expansion)
    enhance_lvl = 5 if enable_prompt_expansion else 6

    _log(
        f"Video üretimi başlatılıyor (Süre: {dur_val}s, Prompt Genişletme: {'Açık' if enable_prompt_expansion else 'Kapalı'})...",
        "generating",
        65,
    )

    ghost_id = str(uuid.uuid4())
    create_payload = {
        "salon_item_group_id": 49,
        "user_input_face_image_id": face_image_id,
        "image_prompt_ids": [],
        "ghost_id": ghost_id,
        "custom_prompt": prompt or "hello",
        "custom_negative_prompt": negative_prompt or "",
        "duration": dur_val,
        "is_enhanced": True,
        "enhance_level": enhance_lvl,
    }

    create_resp = session.post(
        f"{BASE_URL}/api/user-output-salon-image",
        headers=auth_headers,
        json=create_payload,
        timeout=30,
    )
    create_resp.raise_for_status()
    output_ids = create_resp.json().get("output_salon_image_ids", [])
    if not output_ids:
        raise RuntimeError("qFoto video üretim ID'si alınamadı.")
    output_id = output_ids[0]

    # 5. Video tamamlanana kadar sorgula
    _log("Video işleniyor, lütfen bekleyin...", "generating", 70)
    start_time = time.time()
    timeout = 900
    video_filename = None

    while time.time() - start_time < timeout:
        if is_active and not is_active():
            return {"error": "İşlem iptal edildi."}

        poll_resp = session.get(
            f"{BASE_URL}/api/user-output-salon-image?limit=15",
            headers=auth_headers,
            timeout=15,
        )
        if poll_resp.status_code == 200:
            creations = poll_resp.json()
            for c in creations:
                if c.get("id") == output_id or c.get("ghost_id") == ghost_id:
                    status = c.get("status")
                    if status == "finish":
                        video_filename = c.get("image_path")
                        break
                    elif status == "failed":
                        raise RuntimeError("qFoto sunucu tarafında video üretimi başarısız oldu.")
            if video_filename:
                break

        elapsed = int(time.time() - start_time)
        # 70% ile 95% arası dinamik ilerleme
        prog = min(95, 70 + int((elapsed / 60) * 15))
        _log(f"Video hazırlanıyor... ({elapsed} sn geçti)", "generating", prog)
        time.sleep(4)

    if not video_filename:
        raise TimeoutError("qFoto video üretimi zaman aşımına uğradı.")

    elapsed_total = int(time.time() - start_time)
    _log(f"Video başarıyla hazırlandı! ({elapsed_total} sn)", "completed", 100)

    # Web ön yüzü için canlı akış rotası döndür (Sıfır Disk Depolaması)
    web_url = f"/api/qfoto/stream/{video_filename}?t={token}"

    return {
        "output": web_url,
        "filename": video_filename,
        "token": token,
        "task_id": output_id,
        "duration": dur_val,
        "status": "completed",
    }


def run_once(
    prompt: str = "hello",
    image_path: Optional[str] = None,
    duration: Union[int, str] = 5,
    enable_prompt_expansion: bool = True,
    negative_prompt: str = "",
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Diğer AI modülleriyle standart uyumluluk için run_once takma adı."""
    return run_video(
        prompt=prompt,
        image_path=image_path,
        duration=duration,
        enable_prompt_expansion=enable_prompt_expansion,
        negative_prompt=negative_prompt,
        log_callback=log_callback,
        **kwargs
    )


if __name__ == "__main__":
    print("qFoto AI modülü doğrudan test ediliyor...")
    test_img = "test.jpeg" if os.path.exists("test.jpeg") else "test.jpg"
    res = run_video(prompt="a laughing smiling character", image_path=test_img, duration=5)
    print("Sonuç:", res)
