import time
import shutil
import threading
import re
from pathlib import Path
from cloakbrowser import launch_persistent_context

PROFILE_DIR = str(Path(__file__).parent / "browser_profile")


class BrowserManager:
    """
    On-demand CloakBrowser: sadece refresh() çağrıldığında açılır,
    cf_clearance + turnstile token alır ve hemen kapanır.
    RAM: işlem sırasında ~250MB, sonrasında 0MB (512MB Render'a sığar).
    """

    def __init__(self, proxy_url: str = None):
        self._lock = threading.Lock()
        self._proxy_url = proxy_url  # http://user:pass@host:port

    def _parse_proxy(self) -> dict | None:
        """proxy_url'yi CloakBrowser'ın beklediği dict formatına çevir."""
        if not self._proxy_url:
            return None
        from urllib.parse import urlparse
        p = urlparse(self._proxy_url)
        if not p.hostname:
            return None
        result = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            result["username"] = p.username
        if p.password:
            result["password"] = p.password
        return result

    def _clean_locks(self):
        """Stale Chromium lock dosyalarını temizle (crash sonrası kalabilir)."""
        profile_path = Path(PROFILE_DIR)
        if profile_path.exists():
            for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                lock_file = profile_path / lock_name
                if lock_file.exists() or lock_file.is_symlink():
                    try:
                        lock_file.unlink()
                        print(f"[BrowserManager] Stale lock silindi: {lock_name}")
                    except Exception:
                        pass

    def _nuke_profile(self):
        """Bozuk profil dizinini tamamen sil — sıfırdan oluşturulacak."""
        profile_path = Path(PROFILE_DIR)
        if profile_path.exists():
            try:
                shutil.rmtree(profile_path, ignore_errors=True)
                print("[BrowserManager] Bozuk profil dizini silindi, sıfırdan oluşturulacak.")
            except Exception as e:
                print(f"[BrowserManager] Profil silme hatası: {e}")

    def refresh(self) -> dict:
        """
        Browser'ı aç -> register sayfasına git -> Turnstile çöz ->
        cookie + token + HTML al -> browser'ı kapat -> sonucu döndür.
        Başarısız olursa profili sıfırlayıp 1 kez daha dener.
        """
        with self._lock:
            for attempt in range(2):
                try:
                    return self._do_refresh()
                except Exception as e:
                    print(f"[BrowserManager] Deneme {attempt + 1} başarısız: {e}")
                    if attempt == 0:
                        print("[BrowserManager] Profil sıfırlanıyor ve tekrar deneniyor...")
                        self._nuke_profile()
                        time.sleep(2)
                    else:
                        raise

    def _do_refresh(self) -> dict:
        """Tek bir refresh denemesi."""
        self._clean_locks()
        print("[BrowserManager] CloakBrowser açılıyor (on-demand, optimize mod)...")

        proxy = self._parse_proxy()
        if proxy:
            print(f"[BrowserManager] Proxy kullanılıyor: {proxy['server']} (user: {proxy.get('username', 'yok')[:20]}...)")
        else:
            print("[BrowserManager] UYARI: Proxy tanımlı değil, doğrudan bağlantı!")

        context_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "humanize": True,
            "stealth_args": True,
            "args": [
                # Temel argümanlar ve optimize edilmiş pencere boyutu
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1280,720",
                "--disable-dev-shm-usage",
                "--no-sandbox",

                # Bellek (RAM) ve Önbellek Sınırlandırmaları (512MB Render ortamı için)
                "--disk-cache-size=1",
                "--media-cache-size=1",
                "--aggressive-cache-discard",
                "--js-flags=--max-old-space-size=256",
                "--renderer-process-limit=2",

                # Gereksiz Arka Plan Servislerini Kapatma
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-pings",
                "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,CalculateNativeWinOcclusion",

                # Turnstile JS Çözümünü Hızlandırma (Arka plan yavaşlatmalarını engeller)
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        }
        if proxy:
            context_kwargs["proxy"] = proxy

        context = launch_persistent_context(**context_kwargs)
        try:
            # 1. Eski session cookie'lerini temizle (cf_clearance hariç)
            #    Persistent profilde önceki hesaptan kalan session varsa
            #    /register yerine dashboard'a redirect olur!
            for c in context.cookies():
                if "appdeapiai" in c.get("name", "") or "session" in c.get("name", "").lower():
                    try:
                        context.clear_cookies()
                        print("[BrowserManager] Eski session cookie'leri temizlendi.")
                    except Exception:
                        pass
                    break

            page = context.pages[0] if context.pages else context.new_page()

            # 2. Proxy kotası ve RAM tasarrufu için gereksiz ağır kaynakları engelle
            #    Cloudflare ve Turnstile bağlantıları korunur.
            def _block_heavy_resources(route):
                try:
                    req_type = route.request.resource_type
                    req_url = route.request.url.lower()
                    if req_type in ("media", "font"):
                        route.abort()
                    elif req_type == "image" and "cloudflare" not in req_url and "challenges" not in req_url:
                        route.abort()
                    else:
                        route.continue_()
                except Exception:
                    pass

            page.route("**/*", _block_heavy_resources)

            page.goto("https://app.deapi.ai/register", wait_until="domcontentloaded")

            # 3. Turnstile / CF challenge çözülmesini bekle (max 60s)
            turnstile_token = None
            print("[BrowserManager] Turnstile çözülmesi bekleniyor...")
            for i in range(30):
                time.sleep(2)
                try:
                    title = page.title()
                except Exception:
                    continue

                # Hala CF challenge sayfasındayız
                if "just a moment" in title.lower() or "attention required" in title.lower():
                    if i % 5 == 0:
                        print(f"[BrowserManager] CF challenge devam ediyor... ({(i+1)*2}s)")
                    continue

                # Sayfa yüklendi — Turnstile response input'unu kontrol et
                try:
                    token = page.evaluate("""
                        () => {
                            const inp = document.querySelector('input[name="cf-turnstile-response"]');
                            return inp ? inp.value : null;
                        }
                    """)
                    if token and len(token) > 10:
                        turnstile_token = token
                        print(f"[BrowserManager] Turnstile çözüldü! ({(i+1)*2}s, token: {token[:25]}...)")
                        break
                except Exception:
                    pass

                # Turnstile widget'ı varsa ama henüz çözülmediyse, tıklamayı dene
                if i == 5:
                    try:
                        iframe = page.query_selector("iframe[src*='challenges.cloudflare.com']")
                        if iframe:
                            box = iframe.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                print("[BrowserManager] Turnstile checkbox'a tıklandı.")
                    except Exception:
                        pass

            if not turnstile_token:
                print("[BrowserManager] UYARI: Turnstile 60s içinde çözülemedi, mevcut durumla devam ediliyor.")

            # 4. Cookie'leri al
            raw_cookies = context.cookies()
            cookies = {}
            for c in raw_cookies:
                if "deapi.ai" in c.get("domain", ""):
                    cookies[c["name"]] = c["value"]

            # 5. User-Agent al
            user_agent = page.evaluate("() => navigator.userAgent")

            # 6. Sayfa HTML'ini al (Livewire snapshot'ları için)
            html = page.content()

            print(
                f"[BrowserManager] Tamamlandı — "
                f"cf_clearance={'VAR' if 'cf_clearance' in cookies else 'YOK'}, "
                f"turnstile={'VAR' if turnstile_token else 'YOK'}, "
                f"toplam cookie={len(cookies)}"
            )

            return {
                "cookies": cookies,
                "user_agent": user_agent,
                "turnstile_token": turnstile_token,
                "register_html": html,
            }
        finally:
            try:
                context.close()
                print("[BrowserManager] Browser kapatıldı (RAM serbest).")
            except Exception as e:
                print(f"[BrowserManager] Kapatma hatası (önemsiz): {e}")


if __name__ == "__main__":
    import os
    proxy = os.environ.get("RESIDENTIAL_PROXY", "http://j255f577569206246_c_US_s_dev1:9839526ba9b5c6caba1bfbe2084b59f4@gate.anyip.io:1080")
    bm = BrowserManager(proxy_url=proxy)
    data = bm.refresh()
    print("\n--- SONUÇ ---")
    print("User-Agent:", data["user_agent"])
    print("Cookies:", list(data["cookies"].keys()))
    print("Turnstile:", (data["turnstile_token"] or "YOK")[:40])
    print("HTML uzunluk:", len(data["register_html"]))
