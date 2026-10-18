#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kalıcı CloakBrowser Yöneticisi (Render 512MB Free Optimizasyonlu)
------------------------------------------------------------------
Tarayıcıyı TEK BİR arka plan thread'inde sürekli açık tutar.
Tüm Cloudflare Turnstile işleri bir kuyruk üzerinden bu thread'e
sırayla yaptırılır. Böylece:
  - Aç-kapat RAM spike'ı (OOM -> Render restart) ortadan kalkar.
  - Playwright sync API her zaman tek thread'den çağrılır (thread-safe).
  - Profil dizini SingletonLock çakışması yaşanmaz.
"""

import os
import time
import queue
import threading
from cloakbrowser import launch_persistent_context

DEFAULT_PROXY = os.environ.get("PROXY", "http://tghpxuwn:dxrsnpsyz3df@45.38.107.97:6014")
PROXY_MODE = int(os.environ.get("PROXY_MODE", "1"))
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "browser_profile_deapi")


class BrowserManager:
    """
    Playwright / CloakBrowser için Thread-Safe Kalıcı Yönetici.
    İlk ihtiyaç anında (lazy) tek bir daemon thread'de başlar,
    tarayıcıyı açık tutar ve tüm istekleri kuyrukla karşılar.
    """
    def __init__(self, proxy=DEFAULT_PROXY, timeout=300):
        if PROXY_MODE != 1 or not proxy or proxy.strip().lower() in ["none", "direct", "no", "off", ""]:
            self.proxy = None
        else:
            self.proxy = proxy.strip()
        self.timeout = timeout  # Render free için 5 dakika Cloudflare toleransı
        self.task_queue = queue.Queue()
        self.ready_event = threading.Event()
        self.start_lock = threading.Lock()
        self.thread = None

    def _ensure_started(self):
        """Worker thread'i yalnızca ilk ihtiyaçta başlat (boot'u yavaşlatmaz)."""
        if self.thread is not None:
            return
        with self.start_lock:
            if self.thread is None:
                self.thread = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name="CloakBrowserWorker"
                )
                self.thread.start()
        # İlk açılışın hazır olmasını bekle (maksimum 90s)
        self.ready_event.wait(timeout=90)

    def _worker_loop(self):
        print(f"[*] Browser Worker başlatılıyor... Proxy: {'Açık' if self.proxy else 'Kapalı'}", flush=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        # Olası stale SingletonLock kalıntılarını temizle (önceki crash/restart'tan kalan)
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                lock_path = os.path.join(PROFILE_DIR, lock_name)
                if os.path.lexists(lock_path):
                    os.remove(lock_path)
            except Exception:
                pass

        context_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "humanize": True,
            "stealth_args": True,
            "args": [
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=800,600",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--mute-audio",
                "--no-zygote",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=128",
            ],
        }
        if self.proxy:
            context_kwargs["proxy"] = self.proxy

        context = launch_persistent_context(**context_kwargs)

        page = context.pages[0] if context.pages else context.new_page()
        print("[+] CloakBrowser arka planda açıldı ve hazır bekliyor (RAM sabit, aç-kapat yok).", flush=True)
        self.ready_event.set()

        while True:
            try:
                task = self.task_queue.get()
                if task is None:
                    break

                action = task.get("action")
                reply_event = task.get("reply_event")
                reply_data = task.get("reply_data")

                if action == "get_fresh_session":
                    try:
                        # 1. Eski session çerezlerini temizle (temiz kayıt formu için)
                        for c in context.cookies():
                            if "appdeapiai" in c["name"]:
                                try:
                                    context.clear_cookies()
                                except Exception:
                                    pass
                                break

                        print("[*] Kayıt sayfasına gidiliyor ve Turnstile çözülüyor...", flush=True)
                        page.goto("https://app.deapi.ai/register", wait_until="domcontentloaded")

                        t0 = time.time()
                        last_click_time = 0

                        # Render.com için toleranslı döngü
                        while time.time() - t0 < self.timeout:
                            try:
                                title = page.title()
                            except Exception:
                                title = ""

                            cookies_dict = {c["name"]: c["value"] for c in context.cookies()}

                            bypassed = False
                            if "Just a moment" not in title and "Bir dakika" not in title and (
                                "Register" in title or "deAPI" in title or "Sign" in title or "Hesap" in title
                            ):
                                bypassed = True
                            elif "cf_clearance" in cookies_dict:
                                bypassed = True

                            if bypassed:
                                try:
                                    content = page.content()
                                    if "wire:snapshot" in content or "csrf-token" in content:
                                        print(f"[+] Turnstile başarıyla geçildi! Başlık: '{title}'", flush=True)
                                        break
                                except Exception:
                                    if bypassed:
                                        break

                            # Cloudflare iframe'ini bul ve tıkla
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

                        time.sleep(1.5)
                        cookies = {c["name"]: c["value"] for c in context.cookies()}
                        ua = page.evaluate("() => navigator.userAgent")
                        page_html = page.content()

                        if "wire:snapshot" not in page_html and "csrf-token" not in page_html:
                            print("[*] Sayfa snapshot bulunamadı, bir kez reload deneniyor...", flush=True)
                            page.reload(wait_until="domcontentloaded")
                            time.sleep(2)
                            page_html = page.content()
                            cookies = {c["name"]: c["value"] for c in context.cookies()}

                        reply_data["result"] = {
                            "cookies": cookies,
                            "user_agent": ua,
                            "html": page_html,
                        }
                    except Exception as e:
                        reply_data["error"] = str(e)
                    finally:
                        reply_event.set()

            except Exception as loop_err:
                print(f"[!] Worker döngü hatası: {loop_err}", flush=True)
                # Sayfa çökmüşse yeni sayfa aç, tarayıcıyı ayakta tut
                try:
                    if page.is_closed():
                        page = context.pages[0] if context.pages else context.new_page()
                except Exception:
                    pass

    def get_fresh_session(self):
        """
        Tarayıcıya sıralı görev atar ve (cookies, user_agent, html) döndürür.
        Aynı anda kaç thread çağırırsa çağırsın, hepsi kuyrukta serileşir.
        """
        self._ensure_started()
        reply_event = threading.Event()
        reply_data = {}
        self.task_queue.put({
            "action": "get_fresh_session",
            "reply_event": reply_event,
            "reply_data": reply_data
        })
        if not reply_event.wait(timeout=self.timeout + 30):
            raise TimeoutError("Tarayıcıdan oturum bilgisi alma zaman aşımına uğradı.")

        if "error" in reply_data:
            raise RuntimeError(reply_data["error"])

        return reply_data.get("result")


# Global tekil örnek: Tüm Flask thread'leri bunu paylaşır.
BROWSER_MANAGER = BrowserManager()
