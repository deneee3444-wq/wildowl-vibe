import os
import re
import time
import base64
import random
import string
import uuid
import threading
import requests

API_KEY = "AIzaSyDx4ZG_1NQCjh_s6j6QF4XLcTg3u6SWto8"

# Oturum havuzu & Kredi yönetimi
GLOBAL_CLIENT = None
CLIENT_LOCK = threading.Lock()
LAST_MEMES = {}  # meme_id <-> url haritası


class SpamOK:
    """SpamOK e-posta servis yönetimi."""

    @staticmethod
    def generate_email(length=15):
        username = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=length)
        )
        return f"{username}@spamok.com", username

    @staticmethod
    def get_verify_link(username, max_attempts=30, log_callback=None):
        if log_callback:
            log_callback("SpamOK gelen kutusu taranıyor...", "registering", 25)
        for i in range(max_attempts):
            try:
                r = requests.get(
                    f"https://api.spamok.com/v2/EmailBox/{username}",
                    timeout=10
                )
                if r.status_code == 200:
                    mails = r.json().get("mails", [])
                    if mails:
                        mail_id = mails[0]["id"]
                        msg_res = requests.get(
                            f"https://api.spamok.com/v2/Email/{username}/{mail_id}",
                            timeout=10
                        )
                        if msg_res.status_code == 200:
                            html_content = msg_res.json().get("messageHtml", "")
                            match = re.search(
                                r'href=[\'"](https://popvid\.ai/email-action[^\'"]+)[\'"]',
                                html_content,
                            )
                            if match:
                                return match.group(1)
            except Exception as e:
                print(f"[!] e-Posta kontrol hatası: {e}")
            if log_callback and (i + 1) % 5 == 0:
                log_callback(f"Doğrulama maili bekleniyor... ({(i + 1) * 2}s)", "registering", 25 + min(15, i))
            time.sleep(2)
        return None


class PopVidClient:
    """PopVid.ai API işlemleri."""

    def __init__(self, id_token=None, user_id=None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                "origin": "https://popvid.ai",
                "referer": "https://popvid.ai/",
            }
        )
        self.id_token = id_token
        self.user_id = user_id
        self.remaining_credits = 0
        self.email = None
        self.last_meme_id = None
        self.meme_ids = []
        if self.id_token:
            self.session.headers.update(
                {"api-authorization": f"Bearer {self.id_token}"}
            )

    def signup_and_verify(self, log_callback=None):
        def _log(msg, status="info", pct=None):
            print(f"[PopVid] {msg}")
            if log_callback:
                log_callback(msg, status, pct)

        email, username = SpamOK.generate_email()
        self.email = email
        _log(f"Yeni geçici e-posta oluşturuldu: {email}", "registering", 15)

        signup_url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={API_KEY}"
        payload = {
            "requestType": "EMAIL_SIGNIN",
            "email": email,
            "clientType": "CLIENT_TYPE_WEB",
            "continueUrl": "https://popvid.ai/email-action?mode=signIn",
            "canHandleCodeInApp": True,
        }
        res = self.session.post(signup_url, json=payload, timeout=15)
        if res.status_code != 200:
            _log(f"Kayıt isteği başarısız: {res.text}", "error", 20)
            return False

        _log("Doğrulama e-postası gönderildi. SpamOK linki bekleniyor...", "registering", 25)
        verify_link = SpamOK.get_verify_link(username, log_callback=log_callback)

        if not verify_link:
            _log("Doğrulama linki zamanında alınamadı!", "error", 30)
            return False

        _log(f"Doğrulama linki yakalandı: {verify_link}", "registering", 45)

        oob_code = re.search(r"oobCode=([^&]+)", verify_link)
        if oob_code:
            code = oob_code.group(1)
            login_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink?key={API_KEY}"
            login_res = self.session.post(
                login_url, json={"email": email, "oobCode": code}, timeout=15
            )
            if login_res.status_code == 200:
                data = login_res.json()
                self.id_token = data.get("idToken")
                self.user_id = data.get("localId")
                self.session.headers.update(
                    {"api-authorization": f"Bearer {self.id_token}"}
                )
                _log(f"PopVid girişi başarılı! User ID: {self.user_id}", "login", 55)

                stable_id = str(uuid.uuid4())
                user_info_url = f"https://popvid.ai/api/v3/users/{self.user_id}?stableId={stable_id}"
                init_res = self.session.get(user_info_url, timeout=15)

                if init_res.status_code == 200:
                    credits = init_res.json().get("remainingTotalCredits", 0)
                    self.remaining_credits = int(credits)
                    _log(f"Kredi profili tanımlandı. Bakiye: {self.remaining_credits} Kredi", "login", 60)

                self.session.post(
                    "https://popvid.ai/api/v3/locale", json={"locale": "en"}, timeout=10
                )
                time.sleep(1)
                return True

        self.session.get(verify_link, timeout=15)
        _log("Oturum doğrulandı.", "login", 60)
        return True

    def upload_image(self, file_path, log_callback=None):
        if not os.path.exists(file_path):
            if log_callback:
                log_callback(f"Dosya bulunamadı: {file_path}", "error", 65)
            return None, None

        if log_callback:
            log_callback(f"Görsel PopVid sunucusuna yükleniyor...", "uploading", 68)

        url = "https://popvid.ai/api/imagecheck"
        with open(file_path, "rb") as f:
            files = {"image": (os.path.basename(file_path), f, "image/jpeg")}
            data = {"useCase": ""}
            res = self.session.post(url, files=files, data=data, timeout=30)

        if res.status_code == 200 and res.json().get("success"):
            result = res.json()["result"]
            if log_callback:
                log_callback(f"Görsel yüklendi. Image ID: {result['finalImageId']}", "uploading", 75)
            return result["finalImageId"], result["imageUrl"]
        else:
            if log_callback:
                log_callback(f"Görsel yükleme hatası: {res.text}", "error", 70)
            return None, None

    def generate_video(
        self, image_id, prompt, character_type="human", is_recreate=False, recreate_img_url=None, recreate_meme_id=None, log_callback=None
    ):
        url = "https://popvid.ai/api/v3/create_a"
        prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("utf-8")

        data = {
            "imageId": image_id if not is_recreate else recreate_meme_id,
            "createMemeImageType": "existingImage",
            "prompt": prompt_b64,
            "highRes": "true",
            "silentSoundtrack": "false",
            "noLogo": "false",
            "proAnimation": "false",
            "character_type": character_type,
            "characterType": character_type,
            "enableInteractive": "true",
            "isRecreate": "true" if is_recreate else "false",
        }

        if is_recreate:
            data["recreateImageUrl"] = recreate_img_url
            data["recreateMemeId"] = recreate_meme_id
            data["sourceExtendMemeId"] = ""

        if log_callback:
            log_callback(f"Video üretim isteği gönderiliyor (Otomatik Karakter: {character_type})...", "generating", 80)

        res = self.session.post(url, data=data, timeout=30)
        if res.status_code == 200:
            res_data = res.json()
            meme_id = res_data.get("memeId")
            credits = res_data.get("remainingTotalCredits")
            if credits is not None:
                self.remaining_credits = int(credits)
            self.last_meme_id = meme_id
            if meme_id and meme_id not in self.meme_ids:
                self.meme_ids.append(meme_id)
            if log_callback:
                log_callback(f"Video işlemi başlatıldı! Meme ID: {meme_id} | Kalan Kredi: {self.remaining_credits}", "generating", 85)
            return meme_id
        else:
            if log_callback:
                log_callback(f"Video üretim hatası: {res.text}", "error", 80)
            return None

    def extend_video(self, meme_id, prompt, character_type="human", log_callback=None):
        url = "https://popvid.ai/api/v3/extend"
        prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("utf-8")

        data = {
            "memeId": meme_id,
            "prompt": prompt_b64,
            "highRes": "true",
            "silentSoundtrack": "false",
            "noLogo": "false",
            "proAnimation": "false",
            "character_type": character_type,
            "characterType": character_type,
            "enableInteractive": "true",
            "isRecreate": "false",
        }

        if log_callback:
            log_callback(f"Video uzatma (Extend) isteği gönderiliyor (Meme ID: {meme_id})...", "generating", 80)

        res = self.session.post(url, data=data, timeout=30)
        if res.status_code == 200:
            res_data = res.json()
            new_meme_id = res_data.get("memeId")
            credits = res_data.get("remainingTotalCredits")
            if credits is not None:
                self.remaining_credits = int(credits)
            self.last_meme_id = new_meme_id
            if new_meme_id and new_meme_id not in self.meme_ids:
                self.meme_ids.append(new_meme_id)
            if log_callback:
                log_callback(f"Uzatma işlemi başlatıldı! Yeni Meme ID: {new_meme_id} | Kalan Kredi: {self.remaining_credits}", "generating", 85)
            return new_meme_id
        else:
            if log_callback:
                log_callback(f"Video uzatma hatası: {res.text}", "error", 80)
            return None

    def poll_status(self, meme_id, req_type="text_prompt", timeout=600, log_callback=None):
        url = f"https://popvid.ai/api/v3/users/{self.user_id}/batch-status"
        payload = {"requests": [{"memeId": meme_id, "type": req_type}]}

        if log_callback:
            log_callback("Video işleme durumu takip ediliyor (Polling)...", "generating", 88)

        start_time = time.time()
        last_pct = 0
        while time.time() - start_time < timeout:
            try:
                res = self.session.post(
                    url,
                    json=payload,
                    headers={"content-type": "text/plain;charset=UTF-8"},
                    timeout=15,
                )
                if res.status_code == 200:
                    statuses = res.json().get("statuses", {})
                    item = statuses.get(meme_id, {})

                    msg = item.get("statusMessage", "İşleniyor...")
                    progress = item.get("progressUpperbound", 0)
                    completed = item.get("completed", False)
                    error = item.get("error", False)

                    calc_pct = 85 + int(progress * 0.14)
                    if calc_pct > last_pct:
                        last_pct = calc_pct
                        if log_callback:
                            log_callback(f"Video işleniyor: %{progress} - {msg}", "generating", calc_pct)

                    if error:
                        if log_callback:
                            log_callback(f"PopVid işleme hatası: {msg}", "error", 90)
                        return False

                    if completed or progress == 100:
                        if log_callback:
                            log_callback("Video işleme tamamlandı!", "generating", 99)
                        return True
            except Exception as e:
                print(f"[!] Polling hatası: {e}")

            time.sleep(2)
        if log_callback:
            log_callback("Video üretimi zaman aşımına uğradı.", "error", 90)
        return False

    def get_preview_url(self, meme_id, log_callback=None):
        url = f"https://popvid.ai/api/v3/meme/{meme_id}"
        res = self.session.get(url, timeout=15)
        if res.status_code == 200:
            preview_url = res.json().get("previewMp4Url")
            if log_callback:
                log_callback(f"Video önizleme linki alındı: {preview_url}", "completed", 100)
            return preview_url
        else:
            if log_callback:
                log_callback(f"Önizleme linki alınamadı: {res.text}", "error", 95)
            return None


def get_last_meme_id():
    """Son kullanılan/üretilen meme_id bilgisini döndürür."""
    global GLOBAL_CLIENT
    if GLOBAL_CLIENT and GLOBAL_CLIENT.last_meme_id:
        return GLOBAL_CLIENT.last_meme_id
    if LAST_MEMES:
        return list(LAST_MEMES.keys())[-1]
    return None


def get_or_create_client(log_callback=None):
    """Mevcut hesapta kredi varsa onu kullanır, yoksa yeni hesap açar."""
    global GLOBAL_CLIENT
    with CLIENT_LOCK:
        if GLOBAL_CLIENT is not None and GLOBAL_CLIENT.id_token and GLOBAL_CLIENT.remaining_credits > 0:
            if log_callback:
                log_callback(f"Mevcut PopVid hesabı kullanılıyor ({GLOBAL_CLIENT.email} | Kalan Kredi: {GLOBAL_CLIENT.remaining_credits})...", "login", 20)
            return GLOBAL_CLIENT

        if log_callback:
            if GLOBAL_CLIENT and GLOBAL_CLIENT.remaining_credits <= 0:
                log_callback("Mevcut hesabın kredisi tükendi. Yeni PopVid hesabı oluşturuluyor...", "registering", 10)
            else:
                log_callback("PopVid oturumu oluşturuluyor...", "registering", 10)

        new_client = PopVidClient()
        if not new_client.signup_and_verify(log_callback=log_callback):
            raise RuntimeError("PopVid hesabı oluşturulamadı veya doğrulanamadı.")
        GLOBAL_CLIENT = new_client
        return GLOBAL_CLIENT


def create_new_client(log_callback=None):
    """Zorla yeni bir PopVid hesabı açar ve global oturumu günceller."""
    global GLOBAL_CLIENT
    with CLIENT_LOCK:
        if log_callback:
            log_callback("Yeni PopVid hesabı oluşturuluyor...", "registering", 10)
        new_client = PopVidClient()
        if not new_client.signup_and_verify(log_callback=log_callback):
            raise RuntimeError("PopVid hesabı oluşturulamadı.")
        GLOBAL_CLIENT = new_client
        return GLOBAL_CLIENT


def run_once(image_path: str, prompt: str, character_type: str = "human", log_callback=None):
    """PopVid sıfırdan video üretimi fonksiyonu (Kredi bitene kadar aynı hesabı kullanır)."""
    def _log(msg, status="info", pct=None):
        print(f"[run_once] {msg}")
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    _log("PopVid motoru hazırlanıyor...", "registering", 10)
    client = get_or_create_client(log_callback=_log)

    _log(f"Görsel işleniyor: {image_path}", "uploading", 65)
    image_id, image_url = client.upload_image(image_path, log_callback=_log)
    
    # Oturum hatası olduysa yeni hesapla tekrar dene
    if not image_id:
        _log("Görsel yüklenemedi, yeni oturum ile tekrar deneniyor...", "registering", 20)
        client = create_new_client(log_callback=_log)
        image_id, image_url = client.upload_image(image_path, log_callback=_log)
        if not image_id:
            raise RuntimeError("PopVid görsel yükleme başarısız.")

    _log(f"Video üretimi başlatılıyor (Otomatik Karakter: '{character_type}', Prompt: '{prompt}')...", "generating", 78)
    meme_id = client.generate_video(
        image_id=image_id,
        prompt=prompt,
        character_type=character_type,
        log_callback=_log
    )
    
    # Kredi bittiyse veya hata olduysa yeni hesapla tekrar dene
    if not meme_id:
        _log("Kredi yetersiz veya oturum süresi dolmuş olabilir. Yeni hesap açılıp deneniyor...", "registering", 20)
        client = create_new_client(log_callback=_log)
        image_id, image_url = client.upload_image(image_path, log_callback=_log)
        meme_id = client.generate_video(
            image_id=image_id,
            prompt=prompt,
            character_type=character_type,
            log_callback=_log
        )
        if not meme_id:
            raise RuntimeError("PopVid video üretim isteği reddedildi.")

    success = client.poll_status(meme_id, req_type="text_prompt", log_callback=_log)
    if not success:
        raise RuntimeError("PopVid video işleme başarısız veya zaman aşımı.")

    preview_url = client.get_preview_url(meme_id, log_callback=_log)
    if not preview_url:
        raise RuntimeError("PopVid video tamamlandı ancak URL alınamadı.")

    # Cache
    LAST_MEMES[meme_id] = preview_url
    LAST_MEMES[preview_url] = meme_id

    return {
        "meme_id": meme_id,
        "image_id": image_id,
        "image_url": image_url,
        "output": preview_url,
        "user_id": client.user_id,
        "id_token": client.id_token,
        "remaining_credits": client.remaining_credits,
        "character_type": character_type
    }


def run_extend(meme_id: str, prompt: str, character_type: str = "human", user_id: str = None, id_token: str = None, log_callback=None):
    """PopVid mevcut videoyu uzatma (Extend) fonksiyonu (Kredi bitene kadar aynı hesabı kullanır)."""
    def _log(msg, status="info", pct=None):
        print(f"[run_extend] {msg}")
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    if not meme_id:
        meme_id = get_last_meme_id()
    if not meme_id:
        raise RuntimeError("Uzatılacak video referans bilgisi (Meme ID) bulunamadı.")

    _log(f"PopVid video uzatma işlemi başlatılıyor (Meme ID: {meme_id})...", "registering", 10)
    
    client = get_or_create_client(log_callback=_log)

    _log(f"Videonun devamı üretiliyor (Otomatik Karakter: '{character_type}', Prompt: '{prompt}')...", "generating", 75)
    new_meme_id = client.extend_video(
        meme_id=meme_id,
        prompt=prompt,
        character_type=character_type,
        log_callback=_log
    )
    
    # Kredi bittiyse veya hata olduysa yeni hesapla tekrar dene
    if not new_meme_id:
        _log("Mevcut hesabın kredisi yetersiz olabilir. Yeni hesap açılıp uzatma tekrar deneniyor...", "registering", 20)
        client = create_new_client(log_callback=_log)
        new_meme_id = client.extend_video(
            meme_id=meme_id,
            prompt=prompt,
            character_type=character_type,
            log_callback=_log
        )

    if not new_meme_id:
        raise RuntimeError("PopVid video uzatma isteği reddedildi.")

    success = client.poll_status(new_meme_id, req_type="extend", log_callback=_log)
    if not success:
        raise RuntimeError("PopVid video uzatma işlemi başarısız veya zaman aşımı.")

    preview_url = client.get_preview_url(new_meme_id, log_callback=_log)
    if not preview_url:
        raise RuntimeError("PopVid uzatılan video tamamlandı ancak URL alınamadı.")

    LAST_MEMES[new_meme_id] = preview_url
    LAST_MEMES[preview_url] = new_meme_id

    return {
        "meme_id": new_meme_id,
        "source_meme_id": meme_id,
        "output": preview_url,
        "user_id": client.user_id,
        "id_token": client.id_token,
        "remaining_credits": client.remaining_credits,
        "character_type": character_type
    }
