import os
import re
import time
import base64
import random
import uuid
import mimetypes
import html as html_mod
from pathlib import Path
import requests
from http.cookies import SimpleCookie
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ---------- AYARLAR ----------
BASE_LOCAL = "stevecraftstory"
DOMAIN = "gmail.com"
PASSWORD = "Wincike500@"
NAME = "Deneyici"
BASE_URL = "https://vibevideo.org"

SIGNUP_URL = f"{BASE_URL}/api/auth/sign-up/email"
CLAIM_URL = f"{BASE_URL}/api/wyh/claim-anonymous-credits"
UPLOAD_URL_ENDPOINT = f"{BASE_URL}/api/wyh/get-upload-url"
GENERATE_URL = f"{BASE_URL}/api/wyh/generate-video-from-image"

SUPABASE_URL = "https://ltsoefkhjryrfkyuiiqf.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx0c29lZmtoanJ5cmZreXVpaXFmIiwicm9sZSI6ImFub24i"
    "LCJpYXQiOjE3NTcyNjQ5MTUsImV4cCI6MjA3Mjg0MDkxNX0."
    "oLzjBaJVty3FNFpEPYgnsJuJ8wK2P2c5O6Z3mCi9N04"
)

IMAGE_PATH = "test.jpg"
DEFAULT_PROMPT = "hello"
DEFAULT_MODEL = "basic"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SENDER_MATCH = "VibeVideo"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


# ---------- 1) RANDOM DOTTED EMAIL ----------
def random_dotted_email(local: str, domain: str) -> str:
    """Gmail nokta-yoksayma özelliğiyle rastgele varyant üretir."""
    out = [local[0]]
    for ch in local[1:]:
        if random.random() < 0.45 and out[-1] != ".":
            out.append(".")
        out.append(ch)
    return f"{''.join(out)}@{domain}"


# ---------- 2) HTTP HELPERS ----------
def warmup(session: requests.Session):
    """Anonim session cookie'lerini oluşturmak için ana sayfayı gez."""
    common = {
        "accept": "text/html,application/xhtml+xml",
        "accept-encoding": "identity",
        "user-agent": UA,
    }
    session.get(f"{BASE_URL}/", headers=common, timeout=30)
    session.get(
        f"{BASE_URL}/auth/signup",
        headers={**common, "referer": f"{BASE_URL}/"},
        timeout=30,
    )


def set_fingerprint(session: requests.Session) -> str:
    """Frontend JS'in yaptığı gibi userFingerprint cookie'sini elle set et."""
    fp = uuid.uuid4().hex  # 32 hex char
    session.cookies.set("userFingerprint", fp, domain="vibevideo.org", path="/")
    return fp


def _merge_set_cookie(session: requests.Session, resp: requests.Response):
    """Bazı Set-Cookie'ler jar'a düşmezse manuel ekle."""
    raw = resp.headers.get("set-cookie")
    if not raw:
        return
    sc = SimpleCookie()
    sc.load(raw)
    for k, morsel in sc.items():
        session.cookies.set(k, morsel.value, domain="vibevideo.org", path="/")


def sign_up(session: requests.Session, email: str) -> dict:
    headers = {
        "accept": "*/*",
        "accept-encoding": "identity",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/auth/signup",
        "user-agent": UA,
    }
    payload = {
        "email": email,
        "password": PASSWORD,
        "name": NAME,
        "callbackURL": "/",
    }
    r = session.post(SIGNUP_URL, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    _merge_set_cookie(session, r)
    return r.json()


def claim_credits(session: requests.Session) -> dict:
    headers = {
        "accept": "*/*",
        "accept-encoding": "identity",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "user-agent": UA,
    }
    r = session.post(CLAIM_URL, headers=headers, timeout=30)
    if r.status_code == 401:
        print("❌ Claim 401 body:", r.text)
    r.raise_for_status()
    return r.json()


# ---------- 3) GMAIL ----------
def gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        need_new = True
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                need_new = False
            except Exception as e:
                print(f"⚠ Token refresh başarısız ({e}), yeniden auth.")
                try:
                    os.remove("token.json")
                except FileNotFoundError:
                    pass
                creds = None

        if need_new and not (creds and creds.valid):
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore")


def _extract_html(payload: dict) -> str:
    """Message payload'ından HTML (yoksa plain) gövdeyi çıkar."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/html" and body.get("data"):
        return _decode_part(body["data"])
    for part in payload.get("parts", []) or []:
        html = _extract_html(part)
        if html:
            return html
    if mime == "text/plain" and body.get("data"):
        return _decode_part(body["data"])
    return ""


def wait_for_verify_link(service, after_ts: int, timeout: int = 180, poll: int = 5, log_callback=None) -> str:
    """VibeVideo'dan gelen en yeni maildeki İLK <a href="..."> linkini döndür."""
    query = f'from:{SENDER_MATCH} after:{after_ts}'
    waited = 0
    msg_str = f"⏳ Mail bekleniyor (query: {query})"
    print(msg_str)
    if log_callback: log_callback(msg_str, "registering", 38)
    while waited < timeout:
        res = service.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()
        msgs = res.get("messages", [])
        if msgs:
            latest_id = msgs[0]["id"]  # list en yeniden eskiye sıralı
            msg = service.users().messages().get(
                userId="me", id=latest_id, format="full"
            ).execute()
            html = _extract_html(msg["payload"])
            m = re.search(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
            if m:
                return html_mod.unescape(m.group(1))  # &amp; → &
            print("⚠ Mail bulundu ama href çıkarılamadı, tekrar denenecek.")
        time.sleep(poll)
        waited += poll
        if log_callback and waited % 15 == 0:
            log_callback(f"Mail bekleniyor... ({waited}s)", "registering", 38 + min(10, waited // 15))
        print(f"  … {waited}s")
    raise TimeoutError("Doğrulama maili zamanında gelmedi.")


# ---------- 4) UPLOAD ----------
def _guess_filetype(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/jpeg"


def _random_filename(original_path: str) -> str:
    """Frontend'in yaptığı gibi random isim üret (uzantıyı koru)."""
    ext = Path(original_path).suffix or ".png"
    part1 = uuid.uuid4().hex          # 32 hex
    part2 = uuid.uuid4().hex[:8]      # 8 hex
    return f"{part1}-0-{part2}{ext}"


def get_upload_url(session: requests.Session, filename: str, filetype: str, filesize: int) -> dict:
    headers = {
        "accept": "*/*",
        "accept-encoding": "identity",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "user-agent": UA,
    }
    payload = {"filename": filename, "filetype": filetype, "fileSize": filesize}
    r = session.post(UPLOAD_URL_ENDPOINT, json=payload, headers=headers, timeout=30)
    if not r.ok:
        print("❌ get-upload-url:", r.status_code, r.text)
    r.raise_for_status()
    return r.json()


def upload_to_r2(upload_url: str, file_path: str, filetype: str) -> None:
    """Presigned URL'e PUT ile dosyayı yükle."""
    with open(file_path, "rb") as f:
        data = f.read()
    headers = {
        "content-type": filetype,
        "user-agent": UA,
    }
    r = requests.put(upload_url, data=data, headers=headers, timeout=120)
    if not r.ok:
        print("❌ R2 PUT:", r.status_code, r.text)
    r.raise_for_status()


def upload_image(session: requests.Session, file_path: str = IMAGE_PATH) -> dict:
    """Dosyayı VibeVideo storage'ına yükler. Dönüş: {uploadUrl, publicUrl, key}"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    filesize = os.path.getsize(file_path)
    filetype = _guess_filetype(file_path)
    filename = _random_filename(file_path)

    print(f"📤 Upload: {file_path} ({filesize} bytes, {filetype}) → {filename}")

    info = get_upload_url(session, filename, filetype, filesize)
    print(f"   uploadUrl alındı, R2'ye PUT atılıyor…")

    upload_to_r2(info["uploadUrl"], file_path, filetype)
    print(f"✅ Upload tamam: {info['publicUrl']}")
    return info


# ---------- 5) GENERATE + POLL ----------
def generate_video(session: requests.Session, image_url: str,
                   prompt: str = DEFAULT_PROMPT, model: str = DEFAULT_MODEL) -> dict:
    headers = {
        "accept": "*/*",
        "accept-encoding": "identity",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "user-agent": UA,
    }
    payload = {"prompt": prompt, "imageUrl": image_url, "model": model}
    r = session.post(GENERATE_URL, json=payload, headers=headers, timeout=30)
    if not r.ok:
        print("❌ generate:", r.status_code, r.text)
    r.raise_for_status()
    return r.json()


def poll_task(task_id: str, timeout: int = 900, poll: int = 5, log_callback=None) -> dict:
    """Supabase REST üzerinden status pollingi."""
    url = f"{SUPABASE_URL}/rest/v1/ai_generated"
    params = {"select": "status,outputContent", "id": f"eq.{task_id}"}
    headers = {
        "accept": "application/vnd.pgrst.object+json",
        "accept-encoding": "identity",
        "accept-profile": "public",
        "apikey": SUPABASE_ANON_KEY,
        "authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "user-agent": UA,
        "x-client-info": "supabase-js-web/2.89.0",
    }
    waited = 0
    last_status = None
    msg_str = f"⏳ Task pollingi başlıyor: {task_id}"
    print(msg_str)
    if log_callback: log_callback(msg_str, "generating", 90)
    while waited < timeout:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if not r.ok:
            print(f"⚠ poll {r.status_code}: {r.text[:200]}")
        else:
            data = r.json()
            status = data.get("status")
            output = data.get("outputContent") or ""
            if status != last_status:
                print(f"  status: {status}")
                if log_callback: log_callback(f"Video işleme durumu: {status}", "generating", 92)
                last_status = status
            if status in ("completed", "success", "succeeded", "done") and output:
                return data
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Task {status}: {data}")
        time.sleep(poll)
        waited += poll
    raise TimeoutError(f"Task {task_id} {timeout}s içinde bitmedi.")


# ---------- ANA AKIŞ ----------
def run_once(image_path: str = IMAGE_PATH, prompt: str = DEFAULT_PROMPT, model: str = DEFAULT_MODEL, log_callback=None):
    def _log(msg, status="info", pct=None):
        print(msg)
        if log_callback:
            try:
                log_callback(msg, status, pct)
            except Exception:
                pass

    email = random_dotted_email(BASE_LOCAL, DOMAIN)
    _log(f"▶ Kullanılan e-posta: {email}", "registering", 10)

    session = requests.Session()

    # 0) Anonim ziyaret + fingerprint
    _log("Anonim oturum ve fingerprint hazırlanıyor...", "registering", 15)
    warmup(session)
    fp = set_fingerprint(session)
    _log(f"🆔 Fingerprint: {fp}", "registering", 20)

    # Fingerprint set edildikten sonra tekrar bir sayfa ziyareti
    session.get(
        f"{BASE_URL}/",
        headers={
            "accept": "text/html,application/xhtml+xml",
            "accept-encoding": "identity",
            "user-agent": UA,
        },
        timeout=30,
    )

    # 1) sign-up
    _log("Vibe Video kayıt isteği gönderiliyor...", "registering", 25)
    signup_ts = int(time.time())
    signup_res = sign_up(session, email)
    _log(f"✅ Sign-up: user id = {signup_res['user']['id']}", "registering", 30)

    # 2) Gmail'den doğrulama linkini bekle
    _log("Gmail üzerinden doğrulama linki bekleniyor...", "registering", 35)
    service = gmail_service()
    link = wait_for_verify_link(service, after_ts=signup_ts, log_callback=_log)
    _log(f"🔗 Doğrulama linki alındı: {link}", "registering", 50)

    # 3) Verify linkine GET → session cookie güncellenir
    _log("Doğrulama linki aktif ediliyor...", "registering", 55)
    r = session.get(
        link,
        headers={
            "accept": "text/html,application/xhtml+xml",
            "accept-encoding": "identity",
            "user-agent": UA,
        },
        timeout=30,
        allow_redirects=True,
    )
    _merge_set_cookie(session, r)
    _log(f"✅ Verify GET → {r.status_code}", "registering", 60)

    # 4) Claim credits
    _log("Kredi talebi yapılıyor (claim credits)...", "registering", 65)
    claim_res = claim_credits(session)
    _log(f"✅ Claim: {claim_res.get('message')}, finalCredits = {claim_res.get('finalCredits')}", "registering", 70)

    # 5) Resmi yükle
    _log(f"Görsel yükleniyor: {image_path}", "uploading", 75)
    upload_info = upload_image(session, image_path)
    _log(f"🖼  publicUrl: {upload_info['publicUrl']}", "uploading", 80)

    # 6) Video üret
    _log(f"Video üretimi başlatılıyor... (Prompt: '{prompt}', Model: '{model}')", "generating", 85)
    gen = generate_video(session, upload_info["publicUrl"], prompt=prompt, model=model)
    task_id = gen["taskId"]
    _log(f"🎬 Generate: taskId={task_id}, phase={gen.get('phase')}, jobsAhead={gen.get('jobsAhead')}", "generating", 88)

    # 7) Polling
    _log("Video işleniyor, tamamlanması bekleniyor (polling)...", "generating", 90)
    result = poll_task(task_id, log_callback=_log)
    _log(f"✅ Video hazır!", "completed", 100)
    _log(f"   outputContent: {result['outputContent']}", "completed", 100)

    return {
        "email": email,
        "user_id": signup_res["user"]["id"],
        "credits": claim_res.get("finalCredits"),
        "upload": upload_info,
        "task_id": task_id,
        "output": result["outputContent"],
    }


if __name__ == "__main__":
    result = run_once()
    print("\n" + "=" * 60)
    print("SONUÇ:")
    print(f"  email       : {result['email']}")
    print(f"  user_id     : {result['user_id']}")
    print(f"  credits     : {result['credits']}")
    print(f"  publicUrl   : {result['upload']['publicUrl']}")
    print(f"  task_id     : {result['task_id']}")
    print(f"  video output: {result['output']}")
    print("=" * 60)
