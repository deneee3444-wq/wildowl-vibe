#!/usr/bin/env python3
"""
PixelBunny AI - Çoklu Model ve Görsel Destekli Chat Modülü
Otomatik Hesap Açıcı, Oturum Yönetimi, Görsel Yükleme ve Kesintisiz Geçmiş Taşıma (History Carrying)
"""

import base64
import json
import os
import random
import re
import string
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from flask import request, has_request_context
except ImportError:
    has_request_context = lambda: False
    request = None

# ===================== SABİTLER =====================
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzbmRocGFzb3hyd3p4cHpqbGZnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNDgxNjgsImV4cCI6MjA4NzkyNDE2OH0.cStXgyUmRDoaIctjoH4aNL2DUjjcnZLn_7VFNyEbdzE"
BASE_URL = "https://esndhpasoxrwzxpzjlfg.supabase.co"
DEFAULT_PASSWORD = "SifreniYaz123!"

# Göndermek istediğin resim yollarını buraya ekle (CLI modu için).
ATTACHMENT_PATHS = []

# pixelBunny-ornek.py dosyasındaki model listesi
AVAILABLE_MODELS = [
    "claude-opus-4.7",
    "claude-sonnet-4.6",
    "deepseek-v3.2",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "glm-5.1",
    "gpt-5.2",
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.5",
    "grok-4.3",
    "grok-4.20",
    "kimi-k2",
    "kimi-k2.6",
    "minimax-m2.5-pro",
    "qwen3-vl-235b",
    "qwen3.5-35b-a3b",
    "qwen3.6-plus",
    "hermes-3-405b", 
    "hermes-4-405b", 
    "wizardlm-2-8x22b", 
    "euryale-70b", 
    "rocinante-12b",
]

# Varsayılan model (Hermes 4 405B)
DEFAULT_MODEL = "hermes-4-405b"

# Arka planda tanımlı varsayılan sistem promptu (test değeri):
DEFAULT_SYSTEM_PROMPT = "Sen yardımsever, zeki, esprili ve samimi bir yapay zeka asistanısın. Kullanıcıya her zaman Türkçe olarak son derece detaylı, net, yaratıcı ve bilgilendirici cevaplar ver."


# ===================== ÖZEL HATA SINIFLARI =====================
class InsufficientCreditsException(Exception):
    """Kredi bittiğinde (402 veya INSUFFICIENT_CREDITS) fırlatılan istisna"""
    pass


# ===================== TEMP EMAIL =====================
class eTemp:
    def random_email(self, length=15):
        return ''.join(
            random.SystemRandom().choice(string.ascii_lowercase + string.digits)
            for _ in range(length)
        ) + '@spamok.com'

    def getConfirmLink(self, mail, timeout=35):
        address = mail.replace('@spamok.com', '')
        for _ in range(timeout):
            try:
                r = requests.get(f'https://api.spamok.com/v2/EmailBox/{address}', timeout=8)
                if r.status_code == 200:
                    for m in r.json().get('mails', []):
                        if 'Confirm' in m.get('subject', '') or 'Pixel Bunny' in m.get('fromDisplay', ''):
                            email_r = requests.get(f'https://api.spamok.com/v2/Email/{address}/{m["id"]}', timeout=8)
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


# ===================== HESAP İŞLEMLERİ =====================
def register(password=DEFAULT_PASSWORD) -> Tuple[Optional[str], Optional[str]]:
    temp = eTemp()
    email = temp.random_email()

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

    try:
        r = requests.post(
            f"{BASE_URL}/auth/v1/signup?redirect_to=https://pixelbunny.ai",
            headers=headers, json=payload, timeout=15
        )
        if r.status_code not in [200, 201]:
            return None, None

        link = temp.getConfirmLink(email)
        if not link:
            return None, None

        confirm_r = requests.get(link, allow_redirects=True, timeout=15)
        if confirm_r.status_code in [200, 302, 303]:
            return email, password
    except Exception as e:
        print(f"[PixelBunny] Kayıt hatası: {e}")

    return None, None


def login(email, password) -> Tuple[Optional[str], Optional[str]]:
    try:
        r = requests.post(
            f"{BASE_URL}/auth/v1/token?grant_type=password",
            headers={
                "apikey": API_KEY,
                "content-type": "application/json;charset=UTF-8",
            },
            json={"email": email, "password": password},
            timeout=15
        )
        if r.status_code != 200:
            return None, None

        data = r.json()
        token = data.get("access_token")
        user_id = data.get("user", {}).get("id")
        return token, user_id
    except Exception as e:
        print(f"[PixelBunny] Giriş hatası: {e}")
        return None, None


# ===================== UPLOAD =====================
def upload_attachments(token: str, items: List[Any]) -> List[Dict[str, str]]:
    """
    Verilen resimleri (dosya yolu, base64 data-uri, dict veya bytes)
    Supabase upload-input endpoint'ine yükler ve attachment listesi döner.
    Dönen format: [{'url': 'https://...', 'type': 'image/png'}]
    """
    if not items:
        return []

    uploaded = []
    headers = {
        "authorization": f"Bearer {token}",
        "origin": "https://pixelbunny.ai",
        "referer": "https://pixelbunny.ai/",
        "accept": "*/*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    for idx, item in enumerate(items):
        try:
            filename = f"image_{int(time.time())}_{idx}.jpg"
            mime_type = "image/jpeg"
            file_bytes = None

            if isinstance(item, dict):
                # Zaten yüklenmiş url varsa doğrudan kullan
                if item.get("url"):
                    uploaded.append({"url": item["url"], "type": item.get("type", "image/png")})
                    continue
                filename = item.get("name") or filename
                mime_type = item.get("type") or mime_type
                raw_data = item.get("data") or item.get("content") or ""
                if "," in raw_data:
                    header, encoded = raw_data.split(",", 1)
                    if "image/" in header:
                        try:
                            mime_type = header.split(";")[0].replace("data:", "")
                        except Exception:
                            pass
                else:
                    encoded = raw_data
                file_bytes = base64.b64decode(encoded)

            elif isinstance(item, str):
                if item.startswith("http://") or item.startswith("https://"):
                    uploaded.append({"url": item, "type": "image/png"})
                    continue
                elif item.startswith("data:image/"):
                    header, encoded = item.split(",", 1)
                    try:
                        mime_type = header.split(";")[0].replace("data:", "")
                    except Exception:
                        pass
                    file_bytes = base64.b64decode(encoded)
                elif os.path.exists(item):
                    if os.path.getsize(item) == 0:
                        continue
                    filename = os.path.basename(item)
                    with open(item, "rb") as f:
                        file_bytes = f.read()
                else:
                    try:
                        file_bytes = base64.b64decode(item)
                    except Exception:
                        continue
            elif isinstance(item, bytes):
                file_bytes = item

            if not file_bytes:
                continue

            files = {"file": (filename, file_bytes, mime_type)}
            r = requests.post(
                f"{BASE_URL}/functions/v1/upload-input",
                headers=headers,
                files=files,
                timeout=30
            )

            if r.status_code == 200:
                url = r.json().get("url")
                if url:
                    uploaded.append({"url": url, "type": "image/png"})
                    print(f"[PixelBunny] Resim yüklendi: {url}")
            else:
                print(f"[PixelBunny] Resim yükleme başarısız ({r.status_code}): {r.text}")

        except Exception as err:
            print(f"[PixelBunny] Resim yükleme hatası ({idx}): {err}")

    return uploaded


# ===================== CHAT VE CONVERSATION =====================
def create_conversation(token, user_id, model_id=DEFAULT_MODEL) -> Optional[str]:
    try:
        r = requests.post(
            f"{BASE_URL}/rest/v1/chat_conversations?select=id",
            headers={
                "apikey": API_KEY,
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "content-profile": "public",
                "prefer": "return=representation",
                "origin": "https://pixelbunny.ai",
                "referer": "https://pixelbunny.ai/",
                "x-client-info": "supabase-js-web/2.98.0",
                "accept": "application/vnd.pgrst.object+json",
            },
            json={"user_id": user_id, "default_model_id": model_id},
            timeout=15
        )
        if r.status_code == 201:
            return r.json().get("id")
    except Exception as e:
        print(f"[PixelBunny] Konuşma oluşturma hatası: {e}")
    return None


def build_carried_message(carry_history: List[Dict[str, Any]], new_user_input: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Önceki history'yi düz metin olarak mesaja gömer.
    Resimleri ayrıca attachments listesi olarak döndürür.
    """
    lines = []
    carried_attachments = []

    for turn in carry_history:
        role = turn.get("role", "user")
        content = turn.get("content", "")

        if role == "user":
            if isinstance(content, list):
                text_part = ""
                for item in content:
                    if item.get("type") == "text":
                        text_part = item.get("text", "")
                    elif item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url")
                        if url:
                            carried_attachments.append({"url": url, "type": "image/png"})
                lines.append(f"user: {text_part}")
            else:
                lines.append(f"user: {content}")
        else:
            lines.append(f"assistant: {content}")

    history_text = "\n".join(lines)
    full_message = f"[Önceki Konuşma]\n{history_text}\n\n[Yeni Mesaj]\n{new_user_input}"
    return full_message, carried_attachments


def send_completion(
    token: str,
    conv_id: str,
    message: str,
    model_id: str = DEFAULT_MODEL,
    history: List[Dict[str, Any]] = None,
    attachments: List[Dict[str, str]] = None
) -> str:
    """Supabase Edge Function chat-completion endpoint'ine mesaj gönderir ve tam cevabı döner."""
    if history is None:
        history = []
    if attachments is None:
        attachments = []

    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "accept": "*/*",
        "origin": "https://pixelbunny.ai",
        "referer": "https://pixelbunny.ai/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    payload = {
        "conversation_id": conv_id,
        "model_id": model_id,
        "message": message,
        "attachments": attachments,
        "incognito": False,
        "history": history,
    }

    full_response = ""
    with requests.post(
        f"{BASE_URL}/functions/v1/chat-completion",
        headers=headers, json=payload, stream=True, timeout=90
    ) as res:
        res.encoding = "utf-8"
        if res.status_code == 402:
            raise InsufficientCreditsException("Kredi bitti (402).")

        if res.status_code != 200:
            raise RuntimeError(f"Chat tamamlama hatası ({res.status_code}): {res.text}")

        for raw_line in res.iter_lines(decode_unicode=True, chunk_size=1):
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            if "INSUFFICIENT_CREDITS" in data_str:
                raise InsufficientCreditsException("Kredi bitti (INSUFFICIENT_CREDITS).")

            try:
                data = json.loads(data_str)
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("delta", {}).get("content", "")
                    if content:
                        full_response += content
            except json.JSONDecodeError:
                pass

    return full_response


# ===================== CHAT MOTORU =====================
class PixelBunnyChatEngine:
    """
    Kullanıcı oturumu için konuşma durumunu yönetir.
    Geçmiş taşımayı (History Carrying) otomatik olarak sağlar.
    Kredi bittiğinde görünmez şekilde yeni hesap açıp geçmişi aktarır.
    Çoklu model ve çoklu görsel desteği içerir.
    """
    def __init__(self, model_id: str = DEFAULT_MODEL):
        self.model_id = model_id
        self.email = None
        self.password = None
        self.token = None
        self.user_id = None
        self.conv_id = None
        self.history: List[Dict[str, Any]] = []
        self.carry_history: List[Dict[str, Any]] = []
        self.upload_cache: Dict[str, Dict[str, str]] = {}
        self.carry_cache: Dict[str, Dict[str, str]] = {}
        self.is_first_message = True
        self.lock = threading.Lock()

    def _init_account_and_conv(self):
        """Yeni hesap açar, giriş yapar ve conversation oluşturur."""
        email, password = register()
        if not email:
            raise RuntimeError("Yeni PixelBunny hesabı açılamadı. Spamok API yanıt vermedi.")
        token, user_id = login(email, password)
        if not token:
            raise RuntimeError("Yeni PixelBunny hesabına giriş yapılamadı.")
        conv_id = create_conversation(token, user_id, self.model_id)
        if not conv_id:
            raise RuntimeError("Konuşma oturumu (Conversation) oluşturulamadı.")

        self.email = email
        self.password = password
        self.token = token
        self.user_id = user_id
        self.conv_id = conv_id

    def reset_chat(self, model_id: Optional[str] = None):
        """Sohbeti temizler ve sıfırdan yeni sohbete geçer."""
        with self.lock:
            if model_id and model_id in AVAILABLE_MODELS:
                self.model_id = model_id
            self.history = []
            self.carry_history = []
            self.upload_cache = {}
            self.carry_cache = {}
            self.is_first_message = True
            if self.token and self.user_id:
                new_conv = create_conversation(self.token, self.user_id, self.model_id)
                if new_conv:
                    self.conv_id = new_conv

    def _process_images(self, images: List[Any]) -> List[Dict[str, str]]:
        """Görselleri sunucuya yükler ve upload_cache ile eşleştirir."""
        if not images:
            return []

        attachments = []
        to_upload = []

        for item in images:
            if isinstance(item, dict) and item.get("url"):
                attachments.append({"url": item["url"], "type": item.get("type", "image/png")})
            elif isinstance(item, str) and item in self.upload_cache:
                attachments.append(self.upload_cache[item])
            else:
                to_upload.append(item)

        if to_upload and self.token:
            new_uploaded = upload_attachments(self.token, to_upload)
            for raw_item, att in zip(to_upload, new_uploaded):
                if isinstance(raw_item, str):
                    self.upload_cache[raw_item] = att
                elif isinstance(raw_item, dict) and raw_item.get("name"):
                    self.upload_cache[raw_item["name"]] = att
                attachments.append(att)

        return attachments

    def send_message(
        self,
        user_message: str,
        model_id: Optional[str] = None,
        images: Optional[List[Any]] = None
    ) -> str:
        with self.lock:
            if model_id and model_id in AVAILABLE_MODELS:
                self.model_id = model_id
            elif not self.model_id:
                self.model_id = DEFAULT_MODEL

            if not self.token or not self.conv_id:
                self._init_account_and_conv()

            # Resimleri yükle
            attachments = []
            if images:
                attachments = self._process_images(images)

            # Yeni conv'un ilk mesajında taşınan geçmişi mesaja göm
            if self.is_first_message and self.carry_history:
                carried_msg, carried_attachments = build_carried_message(self.carry_history, user_message)
                final_message = carried_msg
                final_attachments = carried_attachments + attachments
            else:
                final_message = user_message
                final_attachments = attachments

            try:
                response = send_completion(
                    token=self.token,
                    conv_id=self.conv_id,
                    message=final_message,
                    model_id=self.model_id,
                    history=self.history,
                    attachments=final_attachments
                )

                if attachments:
                    user_content = [
                        {"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments
                    ] + [{"type": "text", "text": user_message}]
                else:
                    user_content = user_message

                self.history.append({"role": "user", "content": user_content})
                self.history.append({"role": "assistant", "content": response})
                self.is_first_message = False
                return response

            except InsufficientCreditsException:
                # Kredi bitti! Otomatik olarak geçmişi taşıyarak yeni hesap aç:
                print(f"[PixelBunny] Kredi bitti ({self.model_id}), geçmiş taşınarak yeni hesap açılıyor...")
                self.carry_history = list(self.history)
                self.history = []
                self.carry_cache = dict(self.upload_cache)
                self._init_account_and_conv()

                # Yeni hesapta taşınan geçmişle mesajı tekrar gönder
                carried_msg, carried_attachments = build_carried_message(self.carry_history, user_message)
                final_attachments = carried_attachments + attachments

                response = send_completion(
                    token=self.token,
                    conv_id=self.conv_id,
                    message=carried_msg,
                    model_id=self.model_id,
                    history=[],
                    attachments=final_attachments
                )

                if attachments:
                    user_content = [
                        {"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments
                    ] + [{"type": "text", "text": user_message}]
                else:
                    user_content = user_message

                self.history.append({"role": "user", "content": user_content})
                self.history.append({"role": "assistant", "content": response})
                self.is_first_message = False
                return response


# Global tekil nesne (Flask oturumu için):
CHAT_ENGINE = PixelBunnyChatEngine(model_id=DEFAULT_MODEL)


def chat_send(
    message: str,
    model_id: Optional[str] = None,
    images: Optional[List[Any]] = None
) -> str:
    """
    Flask app tarafından çağrılan fonksiyon.
    Flask request context'inden model ve images parametrelerini otomatik okuyabilir.
    """
    if has_request_context():
        try:
            req_data = request.get_json(silent=True) or {}
            if not model_id:
                model_id = req_data.get('model') or req_data.get('model_id')
            if images is None:
                images = req_data.get('images') or req_data.get('attachments') or []
        except Exception:
            pass

    return CHAT_ENGINE.send_message(message, model_id=model_id, images=images)


def chat_reset(model_id: Optional[str] = None):
    """Flask app tarafından sohbeti sıfırlamak için çağrılır."""
    if has_request_context():
        try:
            req_data = request.get_json(silent=True) or {}
            if not model_id:
                model_id = req_data.get('model') or req_data.get('model_id')
        except Exception:
            pass

    CHAT_ENGINE.reset_chat(model_id=model_id)


# ===================== CLI / STANDALONE TEST =====================
def select_model():
    print("\n" + "=" * 50)
    print("  PixelBunny AI - Model Seçimi")
    print("=" * 50)
    for i, model in enumerate(AVAILABLE_MODELS, 1):
        print(f"[{i:2d}] {model}")

    print("=" * 50)

    while True:
        try:
            secim = int(input(f"[?] Kullanmak istediğiniz modelin numarasını girin (1-{len(AVAILABLE_MODELS)}): "))
            if 1 <= secim <= len(AVAILABLE_MODELS):
                return AVAILABLE_MODELS[secim - 1]
            else:
                print("[-] Geçersiz numara! Lütfen listedeki numaralardan birini girin.")
        except ValueError:
            print("[-] Lütfen sadece rakam girin.")
        except (EOFError, KeyboardInterrupt):
            print("\n[*] Çıkılıyor.")
            exit(0)


def cli_chat(initial_model_id, email=None, password=None):
    current_email = email
    current_password = password
    current_model = initial_model_id
    carry_history = []
    carry_cache = {}

    while True:
        print("\n" + "=" * 50)
        print(f"  Oturum Başlatılıyor - {current_model}")
        print("=" * 50)

        if not current_email:
            print("\n[*] Yeni hesap oluşturuluyor...")
            current_email, current_password = register()
            if not current_email:
                print("[-] Hesap oluşturulamadı, çıkılıyor.")
                return

        print(f"\n[*] Giriş yapılıyor: {current_email}")
        token, user_id = login(current_email, current_password)
        if not token:
            return

        conv_id = create_conversation(token, user_id, current_model)
        if not conv_id:
            return

        history = []
        upload_cache = dict(carry_cache)
        is_first_message = len(carry_history) > 0

        print("\n[*] Sohbet hazır. Çıkmak için 'exit' veya 'quit' yaz.\n")
        print("-" * 50)

        credit_error_triggered = False

        while True:
            try:
                user_input = input("Sen: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[*] Çıkılıyor.")
                return

            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "çık"]:
                print("[*] Görüşmek üzere!")
                return

            attachments = []
            if ATTACHMENT_PATHS:
                try:
                    resim_sec = input("[?] Bu mesaja resim(ler) eklensin mi? (e/h): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\n[*] Çıkılıyor.")
                    return

                if resim_sec in ["e", "evet", "y", "yes"]:
                    for path in ATTACHMENT_PATHS:
                        if path in upload_cache:
                            attachments.append(upload_cache[path])
                        else:
                            result = upload_attachments(token, [path])
                            if result:
                                upload_cache[path] = result[0]
                                attachments.append(result[0])

            if is_first_message:
                carried_msg, carried_attachments = build_carried_message(carry_history, user_input)
                final_attachments = carried_attachments + attachments
                final_message = carried_msg
                is_first_message = False
            else:
                final_message = user_input
                final_attachments = attachments

            try:
                response = send_completion(token, conv_id, final_message, current_model, history, final_attachments)
                if response:
                    print(f"[{current_model}]\n{response}")
                    if attachments:
                        user_content = [
                            {"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments
                        ] + [{"type": "text", "text": user_input}]
                    else:
                        user_content = user_input
                    history.append({"role": "user", "content": user_content})
                    history.append({"role": "assistant", "content": response})
                print("-" * 50)

            except InsufficientCreditsException:
                print("\n\n[-] Kredi Sınırına Ulaşıldı (402: INSUFFICIENT_CREDITS)")
                secim = input("[?] Yeni bir oturuma geçilip sıfırdan başlansın mı? (e/h): ").strip().lower()

                if secim in ['e', 'evet', 'y', 'yes']:
                    print("\n[*] Program tamamen sıfırlanıyor ve baştan açılıyor...")
                    time.sleep(1)

                    try:
                        history_sec = input("[?] Önceki konuşma geçmişi yeni chate taşınsın mı? (e/h): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\n[*] Çıkılıyor.")
                        return

                    if history_sec in ['e', 'evet', 'y', 'yes']:
                        carry_history = list(history)
                        carry_cache = dict(upload_cache)
                    else:
                        carry_history = []
                        carry_cache = {}

                    current_model = select_model()
                    current_email = ""
                    current_password = DEFAULT_PASSWORD
                    credit_error_triggered = True
                    break
                else:
                    print("[*] İstek üzerine program durduruldu.")
                    return

        if credit_error_triggered:
            continue
        else:
            break


if __name__ == "__main__":
    secilen = select_model()
    cli_chat(initial_model_id=secilen)
