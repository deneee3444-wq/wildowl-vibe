"""
================================================================================
🎬 TOPVID.AI - WAN 2.6 VIDEO MOTORU & OTOMATİK HESAP HAVUZU (ACCOUNT POOL) 🎬
================================================================================
Bu modül PopVid ve VibeVideo gibi dışarıdan aktarılabilir (run_once) bir yapıya sahiptir.
Özellikler:
1. Sadece Wan 2.6 T2V & I2V Modeli (130 / 131)
2. Boyut (Aspect Ratio), Çözünürlük (Resolution), Süre (Duration) ve Prompt parametreleri
3. Endframe içermez (Sadece başlangıç karesi)
4. Görseldeki varsayılan ayarlar kod içinde sabittir:
   - Sansür Filtresi (Safety Checker): KAPALI (Sansürsüz)
   - Prompt Expansion: KAPALI
   - Multi-Shots: KAPALI
   - Sabit Kamera: KAPALI
   - Sonsuz Döngü: KAPALI
   - Auto Fix: AÇIK
   - Hareket Şiddeti: Auto
   - AI Ses Üretimi: AÇIK
5. Arka planda varsayılan 5 hesaplık otomatik havuz açar.
6. Eğer mevcut hesabın bakiyesi yetersizse otomatik olarak havuzdaki sonraki hesaba geçer!
================================================================================
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
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ==============================================================================
# 1. ŞİFRELEME / ŞİFRE ÇÖZME & PARMAK İZİ MOTORU
# ==============================================================================
class TopVidCrypto:
    def __init__(self, host: str = "api.topvid.ai"):
        self.host = host
        self.key = self._derive_key(host)
        self.iv = bytes(16)

    @staticmethod
    def _derive_key(host_str: str) -> bytes:
        sub = host_str[3:8]
        cleaned = re.sub(r'[^A-Za-z0-9]', '', sub)
        if len(cleaned) > 5:
            cleaned = cleaned[:5]
        key = bytearray(16)
        for i, ch in enumerate(cleaned):
            key[3 + i] = ord(ch)
        return bytes(key)

    def encrypt(self, data: Any) -> str:
        if isinstance(data, (dict, list, int, float, bool)) or data is None:
            data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        else:
            data_str = str(data)
        cipher = AES.new(self.key, AES.MODE_CBC, iv=self.iv)
        padded = pad(data_str.encode('utf-8'), AES.block_size)
        return base64.b64encode(cipher.encrypt(padded)).decode('utf-8')

    def decrypt(self, encrypted_b64: str) -> Any:
        cipher = AES.new(self.key, AES.MODE_CBC, iv=self.iv)
        raw = cipher.decrypt(base64.b64decode(encrypted_b64))
        decrypted_str = unpad(raw, AES.block_size).decode('utf-8')
        try:
            return json.loads(decrypted_str)
        except Exception:
            return decrypted_str

    @staticmethod
    def generate_fingerprint(user_agent: str = None) -> Tuple[str, str]:
        screens = ["1920x1080", "2560x1440", "1366x768", "1536x864", "1440x900", "1680x1050", "3840x2160"]
        platforms = ["Win32", "MacIntel", "Linux x86_64"]
        cores = [4, 8, 12, 16, 24, 32]
        memories = [4, 8, 16, 32]
        timezones = ["Europe/Istanbul", "America/New_York", "Europe/London", "Asia/Tokyo", "Europe/Berlin"]

        screen = random.choice(screens)
        platform = random.choice(platforms)
        core = str(random.choice(cores))
        mem = str(random.choice(memories))
        tz = random.choice(timezones)
        rand_noise = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

        if not user_agent:
            chrome_ver = f"{random.randint(120, 134)}.0.{random.randint(4000, 6999)}.{random.randint(10, 199)}"
            user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_ver} Safari/537.36"

        components = [user_agent, screen, platform, core, mem, tz, rand_noise]
        raw_fp = "|".join(components)
        fp_hash = hex(abs(hash(raw_fp)) ^ 0x5F3759DF)[2:].zfill(16)
        return fp_hash, user_agent


# ==============================================================================
# 2. SPAMOK GEÇİCİ E-POSTA & OTP YÖNETİCİSİ
# ==============================================================================
class SpamokMail:
    def __init__(self, username: Optional[str] = None):
        if not username:
            self.username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        else:
            self.username = username.replace('@spamok.com', '')
        self.email = f"{self.username}@spamok.com"

    def get_verification_code(self, timeout: int = 40, poll_interval: int = 2) -> Optional[str]:
        start_time = time.time()
        headers = {
            "accept": "*/*",
            "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "origin": "https://spamok.com",
            "referer": "https://spamok.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        while time.time() - start_time < timeout:
            try:
                res = requests.get(f"https://api.spamok.com/v2/EmailBox/{self.username}", headers=headers, timeout=8)
                if res.status_code == 200:
                    data = res.json()
                    mails = data.get("mails", [])
                    for mail in mails:
                        subject = mail.get("subject", "")
                        preview = mail.get("messagePreview", "")
                        mail_id = mail.get("id")

                        if "topvid" in subject.lower() or "verification" in subject.lower() or "topvid" in str(mail.get("fromDomain", "")).lower():
                            code_match = re.search(r'\b(\d{6})\b', preview)
                            if code_match:
                                return code_match.group(1)

                            detail_res = requests.get(f"https://api.spamok.com/v2/Email/{self.username}/{mail_id}", headers=headers, timeout=8)
                            if detail_res.status_code == 200:
                                plain_text = detail_res.json().get("messagePlain", "")
                                code_match = re.search(r'\b(\d{6})\b', plain_text)
                                if code_match:
                                    return code_match.group(1)
            except Exception:
                pass

            time.sleep(poll_interval)

        return None


# ==============================================================================
# 3. TOPVID.AI REST CLIENT
# ==============================================================================
class TopVidClient:
    def __init__(self, token: str = None, host: str = "api.topvid.ai"):
        self.host = host
        self.base_url = f"https://{host}"
        self.crypto = TopVidCrypto(host=host)
        self.token = token
        self.session = requests.Session()
        self.fingerprint, self.user_agent = self.crypto.generate_fingerprint()

    def _get_headers(self, is_encrypted: bool = True) -> Dict[str, str]:
        h = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "origin": "https://www.topvid.ai",
            "referer": "https://www.topvid.ai/",
            "user-agent": self.user_agent,
            "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "fingerprint": self.fingerprint,
        }
        if is_encrypted:
            h["is-encrypted"] = "1"
        if self.token:
            h["token"] = self.token
            h["authorization"] = f"Bearer {self.token}"
        return h

    def _post(self, endpoint: str, payload: Any, use_encryption: bool = True) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(is_encrypted=use_encryption)

        if use_encryption:
            enc_data = self.crypto.encrypt(payload)
            req_body = json.dumps({"data": enc_data})
        else:
            req_body = json.dumps(payload)

        resp = self.session.post(url, data=req_body, headers=headers, timeout=30)
        resp.raise_for_status()
        res_json = resp.json()

        if isinstance(res_json, dict) and "data" in res_json and isinstance(res_json["data"], str):
            try:
                decrypted = self.crypto.decrypt(res_json["data"])
                if isinstance(decrypted, dict):
                    return decrypted
                res_json["data"] = decrypted
            except Exception:
                pass

        return res_json

    def validate_email(self, email: str) -> dict:
        return self._post("/api/validate_email", {"email": email})

    def login(self, email: str, code: str, invite_code: str = None, auto_claim_sign_in: bool = True) -> dict:
        payload = {
            "platform": 0,
            "email": email,
            "code": code,
            "referrer": "https://topvid.ai/home",
            "browser": self.user_agent,
            "lang": "en",
            "d_id": self.fingerprint,
            "fingerprint": self.fingerprint
        }
        if invite_code:
            payload["invite_code"] = invite_code

        res = self._post("/api/login", payload)
        if res.get("code") == 200 and "data" in res and "token" in res["data"]:
            self.token = res["data"]["token"]
            if auto_claim_sign_in:
                self.claim_daily_sign_in()
        return res

    def claim_daily_sign_in(self) -> dict:
        try:
            return self._post("/api/user/sign", {})
        except Exception:
            return {}

    def get_my_info(self) -> dict:
        return self._post("/api/user/mine", {})

    def get_invite_code(self) -> Optional[str]:
        try:
            res = self._post("/api/user/invite_code", {})
            return (res.get("data") or {}).get("code")
        except Exception:
            return None

    def upload_file(self, file_path_or_bytes: Union[str, bytes], filename: str = "image.jpg") -> str:
        url = f"{self.base_url}/api/common/upload/file"
        headers = self._get_headers(is_encrypted=False)
        del headers["content-type"]

        if isinstance(file_path_or_bytes, str):
            if os.path.exists(file_path_or_bytes):
                with open(file_path_or_bytes, "rb") as f:
                    file_bytes = f.read()
                filename = os.path.basename(file_path_or_bytes)
            else:
                raise FileNotFoundError(f"Dosya bulunamadı: {file_path_or_bytes}")
        else:
            file_bytes = file_path_or_bytes

        ext = os.path.splitext(filename)[1].lower()
        content_type = "image/jpeg"
        if ext in [".png"]: content_type = "image/png"
        elif ext in [".webp"]: content_type = "image/webp"

        files = {"file": (filename, file_bytes, content_type)}
        res = self.session.post(url, files=files, headers=headers, timeout=60)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == 200 and "data" in data and "url" in data["data"]:
            return data["data"]["url"]
        raise Exception(f"Dosya yükleme başarısız: {data}")

    @staticmethod
    def normalize_duration(model_id: int, duration: Union[str, int]) -> str:
        dur_str = str(duration).strip().lower()
        num = re.sub(r'[^0-9]', '', dur_str) or "5"
        # Wan 2.6 (130 / 131) durations: "5", "10", "15"
        return num

    def get_task_price(self, model_id: int = 130, resolution: str = "720p", duration: str = "5", task_type: int = 3) -> int:
        try:
            res = self._post("/api/task/price/get", {
                "type": task_type,
                "model_id": model_id,
                "resolution": resolution,
                "duration": self.normalize_duration(model_id, duration)
            })
            return (res.get("data") or {}).get("point", 160)
        except Exception:
            return 160

    def create_video_task(self, task_type: int, payload: dict) -> dict:
        endpoint = "/api/task/image_to_video/post" if task_type == 4 else "/api/task/text_to_video/post"
        return self._post(endpoint, payload)

    def get_task_status(self, task_id: int) -> dict:
        return self._post("/api/task/status", {"id": task_id})

    def get_task_detail(self, task_id: int) -> dict:
        return self._post("/api/task/detail", {"id": task_id})


# ==============================================================================
# 4. TEKİL & TAKVİYELİ HESAP AÇICI
# ==============================================================================
def create_boosted_account(num_refs: int = None, target_points: int = 160) -> Tuple[TopVidClient, int]:
    """Yeni ana hesap açar ve referansla bakiye takviyesi (+50 puan/ref) yapar."""
    if num_refs is None:
        num_refs = max(1, (target_points - 110 + 49) // 50)
    master_mail = SpamokMail()
    master_client = TopVidClient()
    master_client.validate_email(master_mail.email)
    m_code = master_mail.get_verification_code(timeout=40)
    if not m_code:
        raise Exception(f"Ana hesap OTP kodu alınamadı ({master_mail.email})")

    master_res = master_client.login(master_mail.email, m_code, auto_claim_sign_in=True)
    if master_res.get("code") != 200:
        raise Exception(f"Ana hesap girişi başarısız: {master_res}")

    invite_code = master_client.get_invite_code()
    info = master_client.get_my_info().get("data", {})
    pts = info.get("point", 110)

    if num_refs > 0 and invite_code:
        for i in range(num_refs):
            try:
                ref_mail = SpamokMail()
                ref_client = TopVidClient()
                ref_client.validate_email(ref_mail.email)
                r_code = ref_mail.get_verification_code(timeout=35)
                if r_code:
                    ref_client.login(ref_mail.email, r_code, invite_code=invite_code, auto_claim_sign_in=True)
            except Exception:
                pass
            time.sleep(1)

        info = master_client.get_my_info().get("data", {})
        pts = info.get("point", pts)

    return master_client, pts


# ==============================================================================
# 5. İHTİYAÇ ANINDA ÇALIŞAN HESAP YÖNETİCİSİ (ON-DEMAND POOL)
# ==============================================================================
GLOBAL_TOPVID_CLIENT: Optional[TopVidClient] = None
GLOBAL_TOPVID_POINTS: int = 0
CLIENT_LOCK = threading.Lock()


def get_account_for_task(needed_points: int = 160, log_callback=None) -> TopVidClient:
    """
    PopVid mimarisine benzer şekilde çalışır.
    Mevcut oturum varsa ve puanı yetiyorsa onu kullanır.
    Bakiye yetersizse veya oturum yoksa tam o anda takviyeli yeni hesap açar.
    Arka planda sunucuyu yoran döngü çalıştırmaz.
    """
    global GLOBAL_TOPVID_CLIENT, GLOBAL_TOPVID_POINTS
    with CLIENT_LOCK:
        if GLOBAL_TOPVID_CLIENT is not None and GLOBAL_TOPVID_CLIENT.token:
            try:
                info = GLOBAL_TOPVID_CLIENT.get_my_info().get("data", {})
                GLOBAL_TOPVID_POINTS = info.get("point", GLOBAL_TOPVID_POINTS)
                if GLOBAL_TOPVID_POINTS >= needed_points:
                    if log_callback:
                        log_callback(f"Mevcut TopVid hesabı kullanılıyor (Bakiye: {GLOBAL_TOPVID_POINTS} Puan)...", "login", 15)
                    return GLOBAL_TOPVID_CLIENT
                else:
                    if log_callback:
                        log_callback(f"Mevcut hesabın bakiyesi tükendi ({GLOBAL_TOPVID_POINTS} < {needed_points} Puan). Yeni hesap açılıyor...", "registering", 12)
            except Exception:
                pass

        if log_callback:
            log_callback(f"Yeni TopVid hesabı hazırlanıyor (+{needed_points} Puan)...", "registering", 15)
        client, pts = create_boosted_account(target_points=needed_points)
        GLOBAL_TOPVID_CLIENT = client
        GLOBAL_TOPVID_POINTS = pts
        if log_callback:
            log_callback(f"Hesap hazırlandı! Bakiye: {pts} Puan", "login", 20)
        return client


# ==============================================================================
# 6. DIŞ DOSYADAN ÇAĞRILABİLİR RUN_ONCE FONKSİYONU
# ==============================================================================
def run_once(
    prompt: str,
    image_path: str = None,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    resolution: str = "720p",
    log_callback=None
) -> dict:
    """
    Wan 2.6 video üretim fonksiyonu.
    Görsel varsa Image-to-Video (tek kare, endframe yok), yoksa Text-to-Video çalışır.
    Resimdeki tüm varsayılan ayarlar kod içinde sabitlenmiştir.
    """
    def _log(msg, status="info", pct=None):
        print(f"[TopVid Wan 2.6] {msg}")
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    _log("TopVid Wan 2.6 işlemi başlatılıyor...", "registering", 5)

    is_i2v = bool(image_path and os.path.exists(image_path))
    task_type = 4 if is_i2v else 3
    model_id = 131 if is_i2v else 130  # 130: Wan 2.6 T2V, 131: Wan 2.6 I2V

    norm_dur = re.sub(r'[^0-9]', '', str(duration)) or "5"
    norm_res = resolution if resolution in ["720p", "1080p"] else "720p"
    norm_ar = aspect_ratio if aspect_ratio in ["16:9", "9:16", "1:1", "4:3", "3:4"] else "16:9"

    # Tahmini maliyet (720p 5s: 160, 10s: 320, 1080p 5s: 240)
    needed_pts = 160
    if norm_dur == "10":
        needed_pts = 320
    elif norm_res == "1080p":
        needed_pts = 240

    # Havuzdan bakiye yeten hesabı al (yetersizse otomatik sonrakine geçer)
    client = get_account_for_task(needed_points=needed_pts, log_callback=_log)

    _log("Video parametreleri hazırlanıyor...", "uploading", 25)

    # RESİMDEKİ AYARLARIN TAMAMI VARSAYILAN KOD İÇİNDE SABİTLENDİ:
    payload = {
        "model_id": model_id,
        "prompt": prompt,
        "aspect_ratio": norm_ar,
        "duration": norm_dur,
        "resolution": norm_res,
        "seed": random.randint(1000, 999999),
        "is_public": 1,
        # 1. Sansür Filtresi (Safety Checker): KAPALI (Sansürsüz)
        "enable_safety_checker": False,
        # 2. Prompt Expansion: KAPALI
        "enable_prompt_expansion": False,
        # 3. Multi-Shots: KAPALI
        "multi_shots": False,
        # 4. Sabit Kamera (Camera Fixed): KAPALI
        "camerafixed": False,
        # 5. Sonsuz Döngü (Seamless Loop): KAPALI
        "loop": False,
        # 6. Auto Fix: AÇIK (Titreme & Renk Düzeltme)
        "auto_fix": True,
        # 7. Hareket Şiddeti: Auto (Otomatik)
        "movement_amplitude": "auto",
        # 8. AI Ses Üretimi: AÇIK (Ortam Sesi / SFX)
        "generate_audio": True
    }

    # Image-to-Video ise görseli yükle (ENDFRAME YOK!)
    if is_i2v:
        _log("Referans başlangıç görseli sunucuya yükleniyor...", "uploading", 35)
        img_url = client.upload_file(image_path)
        payload["image_url"] = img_url
        payload["start_image_url"] = img_url
        payload["first_image_url"] = img_url
        # "endframe de olmasın" kuralı gereği end_image_url kesinlikle eklenmez!

    _log(f"Wan 2.6 görev isteği iletiliyor (Mod: {'I2V' if is_i2v else 'T2V'}, Çözünürlük: {norm_res}, Süre: {norm_dur}s)...", "generating", 45)

    task_res = client.create_video_task(task_type=task_type, payload=payload)
    if task_res.get("code") != 200 or not task_res.get("data") or not task_res["data"].get("task"):
        # Bakiye hatası veya benzeri olursa havuzdaki diğer hesabı dene
        err_msg = task_res.get("msg") or str(task_res)
        if "point" in err_msg.lower() or "balance" in err_msg.lower() or "credit" in err_msg.lower():
            _log("Bakiye uyarısı alındı, sıradaki yedek hesaba geçilip tekrar deneniyor...", "registering", 20)
            client = get_account_for_task(needed_points=needed_pts, log_callback=_log)
            task_res = client.create_video_task(task_type=task_type, payload=payload)

    if task_res.get("code") != 200 or not task_res.get("data") or not task_res["data"].get("task"):
        raise RuntimeError(f"TopVid Wan 2.6 görevi başlatılamadı: {task_res.get('msg') or task_res}")

    task_id = task_res["data"]["task"]["id"]
    _log(f"Görev oluşturuldu! (Task ID: {task_id}) Video işleniyor...", "generating", 50)

    # Durum takibi (Polling)
    start_time = time.time()
    poll_interval = 4
    timeout = 420

    while time.time() - start_time < timeout:
        status_res = client.get_task_status(task_id)
        task_data = status_res.get("data") or {}
        status = task_data.get("status", 0)
        elapsed = int(time.time() - start_time)

        if status == 2:
            _log("Video üretimi tamamlandı! URL alınıyor...", "generating", 95)
            detail_res = client.get_task_detail(task_id)
            d_data = detail_res.get("data") or {}
            video_url = d_data.get("cover_image_url") or d_data.get("url") or ""

            if not video_url:
                try:
                    assets = client._post("/api/my/asset/list", {"page": 1, "size": 3}).get("data", [])
                    if assets:
                        video_url = assets[0].get("url") or assets[0].get("watermark_url") or ""
                except Exception:
                    pass

            if not video_url:
                raise RuntimeError("Video tamamlandı ancak URL alınamadı.")

            _log(f"Wan 2.6 videosu hazır! ({video_url})", "completed", 100)
            return {
                "output": video_url,
                "task_id": task_id,
                "model": "Wan 2.6",
                "aspect_ratio": norm_ar,
                "duration": norm_dur,
                "resolution": norm_res
            }

        elif status == -1:
            raise RuntimeError(f"Wan 2.6 üretimi başarısız oldu! Sebep: {task_data.get('status_msg')}")

        st_name = "Sırada / İşleniyor" if status == 0 else "Dönüştürülüyor"
        pct = min(92, 50 + int((elapsed / 90) * 42))
        _log(f"Video üretiliyor ({st_name})... {elapsed}s geçti", "generating", pct)
        time.sleep(poll_interval)

    raise TimeoutError("TopVid Wan 2.6 görevi zaman aşımına uğradı.")
