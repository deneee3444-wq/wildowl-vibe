#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import threading
from typing import Optional, Dict, Any, Callable
from cloakbrowser import launch_persistent_context

DEFAULT_PROXY = os.environ.get("PROXY", "http://tghpxuwn:dxrsnpsyz3df@45.38.107.97:6014")
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "browser_profile")

_BROWSER_LOCK = threading.RLock()


def _clean_stale_locks(profile_dir: str) -> None:
    """
    Render.com'da olası bir container restart veya OOM kill sonrasında
    browser_profile içinde kalan SingletonLock dosyalarını temizler.
    Yoksa tarayıcı 'profile in use' hatasıyla bir daha açılamaz.
    """
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = os.path.join(profile_dir, lock_name)
        if os.path.exists(lock_path) or os.path.islink(lock_path):
            try:
                os.unlink(lock_path)
            except Exception:
                pass


def fetch_turnstile_session_and_close(
    proxy: Optional[str] = DEFAULT_PROXY,
    timeout: int = 120,
    log_callback: Optional[Callable[[str, str, int], None]] = None,
    is_cached_valid_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None
) -> Dict[str, Any]:
    """
    Cloudflare Turnstile doğrulaması için CloakBrowser'ı açar,
    doğrulamayı ve cf_clearance çerezini alır ve HEMEN KAPATIR.
    Böylece Render.com 512MB RAM ortamında arka planda tarayıcı açık kalmaz
    ve RAM tamamen serbest bırakılır.
    """
    if proxy and proxy.strip().lower() in ["none", "direct", "no", "off", ""]:
        proxy = None

    with _BROWSER_LOCK:
        # Double-check: Eğer biz kilidi beklerken başka bir işlem Turnstile'ı tazelediyse tarayıcıyı açma!
        if is_cached_valid_fn:
            try:
                cached_data = is_cached_valid_fn()
                if cached_data:
                    print("[+] Az önce başka bir işlem Turnstile oturumunu tazeledi; tarayıcı açılmadan hafızadaki çerez kullanılıyor.", flush=True)
                    if log_callback:
                        log_callback("Taze Cloudflare oturumu hafızadan alındı.", "registering", 16)
                    return cached_data
            except Exception:
                pass

        if log_callback:
            log_callback("Cloudflare Turnstile doğrulaması için CloakBrowser açılıyor...", "registering", 12)
        print(f"[*] Cloudflare Turnstile doğrulaması için CloakBrowser açılıyor... (Proxy: {'Açık' if proxy else 'Kapalı'})", flush=True)

        os.makedirs(PROFILE_DIR, exist_ok=True)
        _clean_stale_locks(PROFILE_DIR)

        context_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": True,
            "humanize": True,
            "stealth_args": True,
            "args": [
                # Temel argümanlar (1280x720 çözünürlük ile framebuffer RAM tasarrufu)
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1280,720",
                "--disable-dev-shm-usage",
                "--no-sandbox",

                # Render 512MB RAM & Disk Önbellek Optimizasyonu
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

                # Turnstile JS Çözümünü Hızlandırma (Arka plan throttling engelleme)
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        }
        if proxy:
            context_kwargs["proxy"] = proxy

        context = launch_persistent_context(**context_kwargs)
        try:
            # 1. Eski session çerezlerini temizle (temiz kayıt formu için)
            for c in context.cookies():
                if "appdeapiai" in c.get("name", "") or "session" in c.get("name", "").lower():
                    try:
                        context.clear_cookies()
                    except Exception:
                        pass
                    break

            page = context.pages[0] if context.pages else context.new_page()

            # 2. Gereksiz ağır kaynakları (font, medya ve CF dışı görseller) engelleyerek
            #    hem RAM kullanımını düşür hem de proxy trafiğini hızlandır.
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

            t0 = time.time()
            last_click_time = 0
            last_log_time = t0
            clicked_logged = False

            while time.time() - t0 < timeout:
                now = time.time()
                try:
                    title = page.title()
                except Exception:
                    title = ""

                cookies_dict = {c["name"]: c["value"] for c in context.cookies()}

                # Turnstile geçildi mi kontrol et
                bypassed = False
                if "Just a moment" not in title and "Bir dakika" not in title and ("Register" in title or "deAPI" in title or "Sign" in title or "Hesap" in title):
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

                # Önyüzün canlı kalması için her 5 saniyede bir kalp atışı logla
                if log_callback and (now - last_log_time >= 5):
                    last_log_time = now
                    elapsed_sec = int(now - t0)
                    log_callback(f"Cloudflare Turnstile doğrulanıyor ({elapsed_sec} sn)...", "registering", 14)

                # Cloudflare Turnstile iframe ve checkbox tıklama
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
                                if log_callback and not clicked_logged:
                                    log_callback("Cloudflare Turnstile kutucuğu tıklandı, çözülüyor...", "registering", 15)
                                    clicked_logged = True
                                print("[*] Cloudflare kutusu tıklandı...", flush=True)
                                break
                            except Exception:
                                try:
                                    frame.locator("body").click(timeout=1000)
                                    last_click_time = now
                                    break
                                except Exception:
                                    pass

                time.sleep(1)

            # Cookiebot engelini kaldır
            try:
                page.evaluate("() => { const el = document.getElementById('CybotCookiebotDialog'); if(el) el.remove(); }")
            except Exception:
                pass

            time.sleep(1.0)
            cookies = {c["name"]: c["value"] for c in context.cookies()}
            ua = page.evaluate("() => navigator.userAgent")
            page_html = page.content()

            if "wire:snapshot" not in page_html and "csrf-token" not in page_html:
                print("[*] Sayfa snapshot bulunamadı, bir kez reload deneniyor...", flush=True)
                page.reload(wait_until="domcontentloaded")
                time.sleep(2)
                page_html = page.content()
                cookies = {c["name"]: c["value"] for c in context.cookies()}

            return {
                "cookies": cookies,
                "user_agent": ua,
                "html": page_html,
            }

        finally:
            # Turnstile alındıktan sonra tarayıcıyı HEMEN KAPAT ve RAM'i serbest bırak
            try:
                context.close()
            except Exception:
                pass
            if log_callback:
                log_callback("Tarayıcı kapatıldı, RAM serbest bırakıldı.", "registering", 18)
            print("[+] CloakBrowser kapatıldı ve RAM tamamen serbest bırakıldı.", flush=True)
