import os
import re
import sys
import uuid
import json
import time
import string
import random
import io
import requests
import threading
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for

from bs4 import BeautifulSoup

# ==============================================================================
# MYEDIT ONLINE ALTYAPI VE KRIPTOGRAFİK YARDIMCILAR (temp-mail.asia)
# ==============================================================================

# İSTEDİĞİN DOMAİNLERİ BURAYA GİREBİLİRSİN
# CyberLink ile stabil çalıştığı test edilen domainler listenin başındadır.
WHITELIST_DOMAINS = [
    "umail.asia",
    "cmail.asia",
    "tempmailt.com",
    "t-mail.asia",
    "okyre.com",
    "asia.banglatip.com",
    "pmail.asia",
    "1mail.edu.pl",
    "asia.1maill.com",
    "bd.1maill.com",
    "in.1maill.com",
    "bd.5secmail.com",
    "in.5secmail.com",
    "ng.5secmail.com",
    "asia.5secmail.com",
]

POLL_COMPONENTS = [
    "frontend.components.action",
    "frontend.components.token-login",
    "frontend.components.check-mail",
    "frontend.components.inbox-message",
]


def generate_random_username(length: int = 10) -> str:
    """Belirtilen uzunlukta harf ve rakamlardan oluşan rastgele bir kullanıcı adı üretir."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


# ==============================================================================
# TEMP MAIL PROXY AYARLARI (Render.com temp-mail.asia 403 Engeli İcin)
# ==============================================================================
# Render.com sunucularında temp-mail.asia IP engeline (403 Forbidden) takıldığı
# için sadece temp mail isteklerine özel bu proxy alanı tanımlanmıştır.
# Temp mail dışındaki CyberLink, resim, video vb. hiçbir istek bu proxy'yi KULLANMAZ.
#
# TEMP_MAIL_PROXY_MODE (Proxy Durumu):
#   1 -> Temp mail istekleri Webshare proxy üzerinden geçer (Render.com için 1 yapın).
#   0 -> Proxy devre dışı kalır, doğrudan sunucu IP'si üzerinden bağlanır.
TEMP_MAIL_PROXY_MODE = 1

TEMP_MAIL_PROXY_CONFIG = {
    "http": "http://nrrbciri-1:5cauzsujeluf@p.webshare.io:80",
    "https": "http://nrrbciri-1:5cauzsujeluf@p.webshare.io:80",
}


def apply_temp_mail_proxy(session: requests.Session):
    """Sadece TempMailClient oturumuna proxy uygular.
    
    İleride proxy'yi tamamen kaldırmak isterseniz bu bloğu ve TempMailClient
    içindeki apply_temp_mail_proxy(self.session) satırını silmeniz yeterlidir.
    """
    if TEMP_MAIL_PROXY_MODE == 1 and TEMP_MAIL_PROXY_CONFIG:
        session.proxies.update(TEMP_MAIL_PROXY_CONFIG)
# ==============================================================================


class TempMailClient:
    """temp-mail.asia Livewire Entegrasyonu"""

    BASE_URL = "https://temp-mail.asia"

    def __init__(self, domain: str = None):
        self.domain = domain
        self.box = None
        self.email = None
        self.session = requests.Session()
        apply_temp_mail_proxy(self.session)
        self.csrf = None
        self.components = {}
        self.lw_headers = {}
        self._seen_ids = set()

    def get_email(self, length: int = 10, domain: str = None) -> str:
        """Yeni bir geçici e-posta adresi üretir ve temp-mail.asia oturumuna bağlar."""
        if domain:
            self.domain = domain
        elif not self.domain and WHITELIST_DOMAINS:
            self.domain = WHITELIST_DOMAINS[0]

        init_headers = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "tr-TR,tr;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/437.36"
            ),
            "upgrade-insecure-requests": "1",
        }

        resp = self.session.get(f"{self.BASE_URL}/", headers=init_headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        csrf_match = re.search(r'data-csrf=["\']([^"\']+)["\']', html)
        email_match = re.search(r"const email\s*=\s*'([^']+)'", html)
        self.csrf = csrf_match.group(1) if csrf_match else None
        default_email = email_match.group(1) if email_match else None

        soup = BeautifulSoup(html, "html.parser")
        self.components = {}
        for el in soup.find_all(attrs={"wire:snapshot": True}):
            raw_snap = el.get("wire:snapshot", "")
            try:
                snap_data = json.loads(raw_snap)
                name = snap_data.get("memo", {}).get("name", "")
                if name:
                    self.components[name] = {"snapshot": raw_snap, "name": name}
            except Exception:
                pass

        self.lw_headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "tr-TR,tr;q=0.9",
            "Content-Type": "application/json",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
            "User-Agent": init_headers["User-Agent"],
            "x-livewire": "1",
            "x-csrf-token": self.csrf,
        }

        if self.domain:
            self.box = generate_random_username(length)
            target_email = f"{self.box}@{self.domain}"

            check_mail_comp = self.components.get("frontend.components.check-mail")
            if check_mail_comp and self.csrf:
                change_payload = {
                    "_token": self.csrf,
                    "components": [
                        {
                            "snapshot": check_mail_comp["snapshot"],
                            "updates": {
                                "username": self.box,
                                "domain": self.domain,
                            },
                            "calls": [
                                {
                                    "method": "checkEmailAddress",
                                    "params": [],
                                    "metadata": {},
                                }
                            ],
                        }
                    ],
                }
                try:
                    change_resp = self.session.post(
                        f"{self.BASE_URL}/livewire/update",
                        headers=self.lw_headers,
                        json=change_payload,
                        timeout=30,
                    )
                    if change_resp.ok:
                        for c in change_resp.json().get("components", []):
                            if c.get("snapshot"):
                                self.components["frontend.components.check-mail"]["snapshot"] = c["snapshot"]
                        self.email = target_email
                    else:
                        self.email = default_email or target_email
                except Exception as e:
                    print(f"[Temp Mail] checkEmailAddress uyarisi: {e}")
                    self.email = default_email or target_email
            else:
                self.email = default_email or target_email
        else:
            self.email = default_email

        print(f"[Temp Mail] Olusturuldu: {self.email}")
        return self.email

    def _build_poll_payload(self) -> dict:
        api_components = []
        for name in POLL_COMPONENTS:
            comp = self.components.get(name)
            if not comp:
                continue

            if name == "frontend.components.inbox-message":
                calls = [
                    {
                        "method": "__dispatch",
                        "params": ["syncEmail", {"email": self.email}],
                        "metadata": {},
                    },
                    {
                        "method": "__dispatch",
                        "params": ["fetchMessages", {}],
                        "metadata": {},
                    },
                ]
            else:
                calls = [
                    {
                        "method": "__dispatch",
                        "params": ["syncEmail", {"email": self.email}],
                        "metadata": {},
                    },
                ]
            api_components.append(
                {
                    "snapshot": comp["snapshot"],
                    "updates": {},
                    "calls": calls,
                }
            )
        return {"_token": self.csrf, "components": api_components}

    def _clean_url(self, url: str) -> str:
        if not url:
            return ""
        import html as _html
        u = _html.unescape(url).replace("&amp;", "&").strip()
        changed = True
        while changed:
            changed = False
            for end in ['&quot;', '&quot', '"', "'", '>', '<', ')', ']', ';']:
                if u.endswith(end):
                    u = u[:-len(end)].strip()
                    changed = True
        return u

    def _extract_activation_link(self, text: str) -> str:
        if not text:
            return None
        import html as _html
        text = _html.unescape(text)

        # 1. Supabase / WildOwl verify links
        auth_links = re.findall(
            r'https?://[^\s"\'<>]+(?:supabase\.co|wildowl\.ai)[^\s"\'<>]*(?:verify|confirm|token|signup)[^\s"\'<>]*',
            text,
            re.IGNORECASE,
        )
        for link in auth_links:
            clean = self._clean_url(link)
            if clean:
                return clean

        # 2. BeautifulSoup ile link ara
        try:
            soup = BeautifulSoup(text, "html.parser")
            for a in soup.find_all("a", href=True):
                clean = self._clean_url(a["href"])
                if any(k in clean.lower() for k in ["verify", "confirm", "activate", "signup", "supabase"]):
                    return clean
        except Exception:
            pass

        # 3. CyberLink trace links
        trace_links = re.findall(
            r'https?://membership\.cyberlink\.com/prog/event/autoedm/trace_mem\.jsp\?[^\s"\'<>]+',
            text,
        )
        for link in trace_links:
            clean = self._clean_url(link)
            if any(k in clean for k in ["account-activate", "Activate", "active-member"]):
                return clean

        # 4. Genel linkler
        general_links = re.findall(
            r'https?://[^\s"\'<>]+(?:activate|confirm|verify)[^\s"\'<>]*',
            text,
            re.IGNORECASE,
        )
        for link in general_links:
            clean = self._clean_url(link)
            if clean:
                return clean

        # 5. Fallback
        all_urls = re.findall(r'https?://[^\s"\'<>]+', text)
        for u in all_urls:
            clean = self._clean_url(u)
            if any(k in clean.lower() for k in ["verify", "confirm", "activate", "signup", "token"]):
                return clean

        if trace_links:
            return self._clean_url(trace_links[0])

        return None

    def _extract_code(self, text: str) -> str:
        codes = re.findall(r"\b\d{4,8}\b", text)
        return codes[0] if codes else None

    def _fetch_message_content(self, msg_id, inbox_snapshot) -> str:
        view_payload = {
            "_token": self.csrf,
            "components": [
                {
                    "snapshot": inbox_snapshot,
                    "updates": {},
                    "calls": [{"method": "updateView", "params": [msg_id], "metadata": {}}],
                }
            ],
        }
        view_resp = self.session.post(
            f"{self.BASE_URL}/livewire/update",
            headers=self.lw_headers,
            json=view_payload,
            timeout=30,
        )
        if not view_resp.ok:
            return ""

        all_text = []
        for comp_resp in view_resp.json().get("components", []):
            effects_html = comp_resp.get("effects", {}).get("html", "")
            if effects_html:
                all_text.append(effects_html)
            snap_str = comp_resp.get("snapshot", "")
            if snap_str:
                try:
                    snap = json.loads(snap_str)
                    msgs = snap.get("data", {}).get("messages", [])
                    if msgs and isinstance(msgs[0], list):
                        for group in msgs[0]:
                            if isinstance(group, list):
                                for m in group:
                                    if isinstance(m, dict) and "content" in m:
                                        all_text.append(m["content"])
                except Exception:
                    pass
        return "\n".join(all_text)

    def wait_for_activation_link(self, timeout: int = 60) -> str:
        print(f"[Temp Mail] Gelen kutusu sorgulaniyor ({self.email})...")
        deadline = time.time() + timeout
        inbox_snapshot = None

        while time.time() < deadline:
            inbox_keys = []
            try:
                payload = self._build_poll_payload()
                resp = self.session.post(
                    f"{self.BASE_URL}/livewire/update",
                    headers=self.lw_headers,
                    json=payload,
                    timeout=20,
                )
                if resp.ok:
                    data = resp.json()
                    resp_comps = data.get("components", [])
                    active_names = [n for n in POLL_COMPONENTS if n in self.components]

                    for i, rc in enumerate(resp_comps):
                        new_snap = rc.get("snapshot", "")
                        if not new_snap or i >= len(active_names):
                            continue
                        target_name = active_names[i]
                        self.components[target_name]["snapshot"] = new_snap

                        if target_name == "frontend.components.inbox-message":
                            try:
                                snap = json.loads(new_snap)
                                inbox_msgs = snap.get("data", {}).get("inbox_messages", [])
                                if isinstance(inbox_msgs, list):
                                    for item in inbox_msgs:
                                        if isinstance(item, dict) and "keys" in item:
                                            inbox_keys = item["keys"]
                                            inbox_snapshot = new_snap
                            except Exception:
                                pass
            except Exception as e:
                print(f"[Temp Mail] Poll uyarisi: {e}")

            unseen_keys = [k for k in inbox_keys if k not in self._seen_ids]
            if unseen_keys:
                for msg_id in unseen_keys:
                    self._seen_ids.add(msg_id)
                    print(f"[+] Yeni mail alindi! ID: {msg_id}")
                    content = self._fetch_message_content(msg_id, inbox_snapshot)
                    link = self._extract_activation_link(content)
                    if link:
                        print(f"  -> Aktivasyon linki bulundu: {link[:80]}...")
                        return link

            time.sleep(3)

        raise TimeoutError("Aktivasyon maili gelmedi!")

    def wait_for_code(self, timeout: int = 60) -> str:
        print(f"[Temp Mail] Kod bekleniyor ({self.email})...")
        deadline = time.time() + timeout
        inbox_snapshot = None

        while time.time() < deadline:
            inbox_keys = []
            try:
                payload = self._build_poll_payload()
                resp = self.session.post(
                    f"{self.BASE_URL}/livewire/update",
                    headers=self.lw_headers,
                    json=payload,
                    timeout=20,
                )
                if resp.ok:
                    data = resp.json()
                    resp_comps = data.get("components", [])
                    active_names = [n for n in POLL_COMPONENTS if n in self.components]

                    for i, rc in enumerate(resp_comps):
                        new_snap = rc.get("snapshot", "")
                        if not new_snap or i >= len(active_names):
                            continue
                        target_name = active_names[i]
                        self.components[target_name]["snapshot"] = new_snap

                        if target_name == "frontend.components.inbox-message":
                            try:
                                snap = json.loads(new_snap)
                                inbox_msgs = snap.get("data", {}).get("inbox_messages", [])
                                if isinstance(inbox_msgs, list):
                                    for item in inbox_msgs:
                                        if isinstance(item, dict) and "keys" in item:
                                            inbox_keys = item["keys"]
                                            inbox_snapshot = new_snap
                            except Exception:
                                pass
            except Exception as e:
                print(f"[Temp Mail] Poll uyarisi: {e}")

            unseen_keys = [k for k in inbox_keys if k not in self._seen_ids]
            if unseen_keys:
                for msg_id in unseen_keys:
                    self._seen_ids.add(msg_id)
                    print(f"[+] Yeni mail alindi! ID: {msg_id}")
                    content = self._fetch_message_content(msg_id, inbox_snapshot)
                    code = self._extract_code(content)
                    if code:
                        print(f"[+] Dogrulama kodu bulundu: {code}")
                        return code

            time.sleep(3)

        raise TimeoutError("Dogrulama kodu gelmedi!")




# Ensure parent root directory is in sys.path to import vibeVideo
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import vibeVideo
except ImportError:
    vibeVideo = None

try:
    import popVidAI
except ImportError:
    popVidAI = None

try:
    import topVidAI
except ImportError:
    topVidAI = None

try:
    import pixelBunnyAI
except ImportError:
    pixelBunnyAI = None

try:
    import morphStudioAI
except ImportError:
    morphStudioAI = None

try:
    import agnesAI
except ImportError:
    agnesAI = None

try:
    import deApiAI
except ImportError:
    deApiAI = None

# Try to import config and helpers from wildOwlAI.py
try:
    from wildOwlAI import SupabaseSignup as _WO
    eTemp = _WO
except ImportError:
    # Fallback config if import fails
    MODELS_CONFIG = {
        "MiniMax H3 Video": {
            "model_id": "MiniMaxH3_33B_Turbo_INT8",
            "model_slug": "MiniMaxH3_33B_Turbo_INT8",
            "type": "video",
            "provider": "deapi",
            "tiers": ["5", "10"],
            "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
            "resolutions": ["768p", "720p"],
            "resolution": "768p",
            "extra_settings": {
                "fps": 24,
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        },
        "LTX 2.5 Video": {
            "model_id": "Ltx2_5_22B_Dist_INT8",
            "model_slug": "Ltx2_5_22B_Dist_INT8",
            "type": "video",
            "provider": "deapi",
            "tiers": ["5", "10"],
            "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
            "resolutions": ["768p", "720p"],
            "resolution": "768p",
            "extra_settings": {
                "fps": 24,
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        },
        "Vibe Video": {
            "model_id": "vibe-video",
            "type": "video",
            "tiers": ["standard"],
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "resolution": "720p"
        },
        "Pop Vid": {
            "model_id": "pop-vid",
            "type": "video",
            "tiers": ["standard"],
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "resolution": "720p"
        },
        "Wan 2.6 Video": {
            "model_id": "wan-2.6-video",
            "type": "video",
            "tiers": ["5", "10", "15"],
            "tier_labels": {"5": "5 Saniye", "10": "10 Saniye", "15": "15 Saniye"},
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
            "resolutions": ["720p", "1080p"],
            "resolution": "720p",
            "extra_settings": {
                "enable_safety_checker": False,
                "enable_prompt_expansion": False,
                "multi_shots": False,
                "camerafixed": False,
                "loop": False,
                "auto_fix": False,
                "generate_audio": True,
                "audio_url": "",
                "negative_prompt": "",
                "movement_amplitude": "auto",
                "movement_amplitudes": ["auto", "small", "medium", "large"],
                "movement_amplitude_labels": {
                    "auto": "Otomatik",
                    "small": "Düşük",
                    "medium": "Orta",
                    "large": "Yüksek"
                }
            }
        },
        "Agnes Video 2.0": {
            "model_id": "agnes-video-v2.0",
            "type": "video",
            "provider": "agnes",
            "tiers": ["3", "5", "8", "10", "15", "20", "30", "40"],
            "tier_labels": {
                "3": "3 Saniye",
                "5": "5 Saniye",
                "8": "8 Saniye",
                "10": "10 Saniye",
                "15": "15 Saniye",
                "20": "20 Saniye",
                "30": "30 Saniye",
                "40": "40 Saniye"
            },
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "resolutions": ["480p", "720p", "1080p"],
            "resolution": "720p",
            "extra_settings": {
                "fps": 24,
                "fps_options": [24, 30, 60],
                "fps_labels": {
                    "24": "24 FPS (Sinema)",
                    "30": "30 FPS (Akıcı)",
                    "60": "60 FPS (Ultra)"
                },
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        },
        "Seedance 1.0 Pro Fast": {
            "model_id": "seedance_v1_pro_fast",
            "type": "video",
            "provider": "morph",
            "tiers": ["5", "10"],
            "tier_labels": {"5": "5 Saniye", "10": "10 Saniye"},
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "resolutions": ["480p", "720p", "1080p"],
            "resolution": "480p"
        },
        "Nano Banana 2.1": {
            "model_id": "google/nano-banana-2.1",
            "type": "image",
            "provider": "morph",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1"],
            "resolutions": ["1k", "2k", "4k"],
            "resolution": "1k"
        },
        "GPT Image 2.5 (Sunburst)": {
            "model_id": "openai/gpt-image-2.5",
            "type": "image",
            "provider": "morph",
            "mode": "sunburst",
            "tiers": ["low", "medium", "high", "xhigh"],
            "tier_labels": {"low": "Low Kalite", "medium": "Medium Kalite", "high": "High Kalite", "xhigh": "Xhigh Kalite"},
            "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "2:1", "1:2", "3:1", "1:3"],
            "resolutions": ["1k", "2k", "4k"],
            "resolution": "2k"
        },
        "GPT Image 2.5 (Flare)": {
            "model_id": "openai/gpt-image-2.5",
            "type": "image",
            "provider": "morph",
            "mode": "flare",
            "tiers": ["low", "medium", "high", "xhigh"],
            "tier_labels": {"low": "Low Kalite", "medium": "Medium Kalite", "high": "High Kalite", "xhigh": "Xhigh Kalite"},
            "aspect_ratios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "2:1", "1:2", "3:1", "1:3"],
            "resolutions": ["1k", "2k", "4k"],
            "resolution": "2k"
        },
        "MiniMax H3 Image": {
            "model_id": "minimax-h3-image",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolutions": ["1K", "2K"],
            "resolution": "1K"
        },
        "Wan 2.7": {
            "model_id": "wan-2.7-image",
            "tiers": ["standard", "pro"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "resolution": "1K"
        },
        "Seedream 5 Pro": {
            "model_id": "seedream-5-pro",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolution": "1K"
        },
        "Seedream 5 Lite": {
            "model_id": "seedream-5-lite",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "resolution": "3K"
        },
        "Grok Imagine": {
            "model_id": "grok-image",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "2:1", "20:9", "19.5:9", "4:3", "3:2", "2:3", "3:4", "9:19.5", "9:20", "1:2"],
            "resolution": "HD"
        },
        "Flux 2": {
            "model_id": "flux-2",
            "tiers": ["low", "medium", "high"],
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
            "resolution": "1K"
        },
        "GPT Image 2": {
            "model_id": "gpt-image-2",
            "tiers": ["low", "medium", "high"],
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
            "resolution": "1K"
        },
        "GPT Image 1.5": {
            "model_id": "gpt-image-1.5",
            "tiers": ["low", "medium", "high"],
            "aspect_ratios": ["1:1", "3:2", "2:3"],
            "resolution": "1K"
        },
         "Qwen 2.1": {
            "model_id": "qwen-2.1",
            "tiers": ["standard", "pro", "turbo"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
            "resolutions": ["1K", "2K"],
            "resolution": "1K"
        },
        "Qwen Image 2": {
            "model_id": "qwen-image-2",
            "tiers": ["standard", "pro"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "resolution": "HD"
        },
        "Qwen Image 3": {
            "model_id": "qwen-image-3",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
            "resolution": "1K"
        },
        "Wan 2.6": {
            "model_id": "wan-2.6-image",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "resolution": "1K"
        },
        "Z-Image Turbo": {
            "model_id": "z-image-turbo",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "resolution": "HD"
        },
        "Agnes Image 2.5 Flash": {
            "model_id": "agnes-image-2.5-flash",
            "type": "image",
            "provider": "agnes",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolutions": ["1K", "2K", "3K", "4K"],
            "resolution": "2K",
            "extra_settings": {
                "strength": "0.75",
                "strength_options": ["0.3", "0.5", "0.75", "0.9", "1.0"],
                "strength_labels": {
                    "0.3": "%30 (Hafif)",
                    "0.5": "%50 (Orta)",
                    "0.75": "%75 (Standart)",
                    "0.9": "%90 (Güçlü)",
                    "1.0": "%100 (Baskın)"
                },
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        },
        "Agnes Image 2.1 Flash": {
            "model_id": "agnes-image-2.1-flash",
            "type": "image",
            "provider": "agnes",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolutions": ["1K", "2K", "3K", "4K"],
            "resolution": "2K",
            "extra_settings": {
                "strength": "0.75",
                "strength_options": ["0.3", "0.5", "0.75", "0.9", "1.0"],
                "strength_labels": {
                    "0.3": "%30 (Hafif)",
                    "0.5": "%50 (Orta)",
                    "0.75": "%75 (Standart)",
                    "0.9": "%90 (Güçlü)",
                    "1.0": "%100 (Baskın)"
                },
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        },
        "Agnes Image 2.0 Flash": {
            "model_id": "agnes-image-2.0-flash",
            "type": "image",
            "provider": "agnes",
            "tiers": ["standard"],
            "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
            "resolutions": ["1K", "2K", "3K", "4K"],
            "resolution": "2K",
            "extra_settings": {
                "strength": "0.75",
                "strength_options": ["0.3", "0.5", "0.75", "0.9", "1.0"],
                "strength_labels": {
                    "0.3": "%30 (Hafif)",
                    "0.5": "%50 (Orta)",
                    "0.75": "%75 (Standart)",
                    "0.9": "%90 (Güçlü)",
                    "1.0": "%100 (Baskın)"
                },
                "enable_prompt_expansion": False,
                "negative_prompt": "",
                "seed": ""
            }
        }
    }
    
    class eTemp:
        def __init__(self):
            self.client = TempMailClient()

        def get_email(self):
            return self.client.get_email()

        def getEmail(self):
            return self.get_email()

        def get_signup_url_from_inbox(self, mail=None, max_retries=30, timeout=60, **kwargs):
            try:
                return self.client.wait_for_activation_link(timeout=timeout or (max_retries * 2))
            except Exception as e:
                print(f"[✗] Onay maili alinamadi: {e}")
                return None

        def getConfirmLink(self, mail, timeout=30):
            return self.get_signup_url_from_inbox(mail=mail, timeout=timeout)

app = Flask(__name__)
app.secret_key = "wild_owl_ai_studio_super_secret_key"
app.config['JSON_SORT_KEYS'] = False
if hasattr(app, 'json'):
    app.json.sort_keys = False

# In-memory stores (RAM)
GENERATION_HISTORY = []
CUSTOM_PROMPTS = []
CHAT_HISTORY = []
ACTIVE_JOBS = {}

APP_PASSWORD = "123"

def is_logged_in():
    return session.get('logged_in') == True

@app.route('/')
def index():
    return render_template('index.html', logged_in=is_logged_in())

@app.route('/login', methods=['POST'])
def login():
    password = request.form.get('password')
    if password == APP_PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Hatalı şifre!'}), 401

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/api/models')
def get_models():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(MODELS_CONFIG)

# GALLERY APIS
@app.route('/api/history')
def get_history():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(GENERATION_HISTORY)

@app.route('/api/history/delete', methods=['POST'])
def delete_history_item():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    item_id = request.json.get('id')
    global GENERATION_HISTORY
    GENERATION_HISTORY = [item for item in GENERATION_HISTORY if item.get('id') != item_id]
    return jsonify({'success': True})

@app.route('/api/history/clear-all', methods=['POST'])
def clear_history():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    global GENERATION_HISTORY
    GENERATION_HISTORY = []
    return jsonify({'success': True})

# PROMPTS APIS
@app.route('/api/prompts')
def get_prompts():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(CUSTOM_PROMPTS)

@app.route('/api/prompts/add', methods=['POST'])
def add_prompt():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    prompt_text = request.json.get('prompt', '').strip()
    tag = request.json.get('tag', 'General').strip()
    if not prompt_text:
        return jsonify({'error': 'Prompt boş olamaz!'}), 400
    
    new_prompt = {
        'id': uuid.uuid4().hex,
        'prompt': prompt_text,
        'tag': tag
    }
    CUSTOM_PROMPTS.insert(0, new_prompt)
    return jsonify({'success': True, 'prompt': new_prompt})

@app.route('/api/prompts/edit', methods=['POST'])
def edit_prompt():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    prompt_id = request.json.get('id')
    prompt_text = request.json.get('prompt', '').strip()
    tag = request.json.get('tag', 'General').strip()
    if not prompt_text:
        return jsonify({'error': 'Prompt boş olamaz!'}), 400
    
    for p in CUSTOM_PROMPTS:
        if p['id'] == prompt_id:
            p['prompt'] = prompt_text
            p['tag'] = tag
            return jsonify({'success': True, 'prompt': p})
            
    return jsonify({'error': 'Prompt bulunamadı!'}), 404

@app.route('/api/prompts/delete', methods=['POST'])
def delete_prompt():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    prompt_id = request.json.get('id')
    global CUSTOM_PROMPTS
    CUSTOM_PROMPTS = [p for p in CUSTOM_PROMPTS if p['id'] != prompt_id]
    return jsonify({'success': True})

@app.route('/api/prompts/clear-all', methods=['POST'])
def clear_prompts():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    global CUSTOM_PROMPTS
    CUSTOM_PROMPTS = []
    return jsonify({'success': True})

# AI CHAT APIS (PixelBunny Hermes-4-405B)
@app.route('/api/chat/history')
def get_chat_history():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(CHAT_HISTORY)

@app.route('/api/chat/system-prompt', methods=['GET', 'POST'])
def chat_system_prompt():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        new_prompt = data.get('system_prompt', '').strip()
        if new_prompt and pixelBunnyAI:
            pixelBunnyAI.DEFAULT_SYSTEM_PROMPT = new_prompt
        return jsonify({'success': True, 'system_prompt': pixelBunnyAI.DEFAULT_SYSTEM_PROMPT if pixelBunnyAI else ""})
    
    sys_prompt = pixelBunnyAI.DEFAULT_SYSTEM_PROMPT if pixelBunnyAI else "Sen yardımsever, zeki, esprili ve samimi bir yapay zeka asistanısın. Kullanıcıya her zaman Türkçe olarak son derece detaylı, net, yaratıcı ve bilgilendirici cevaplar ver."
    return jsonify({'system_prompt': sys_prompt})

@app.route('/api/chat/send', methods=['POST'])
def chat_send_message():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    if not pixelBunnyAI:
        return jsonify({'error': 'pixelBunnyAI modülü bulunamadı!'}), 500
    
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    is_system = data.get('is_system', False)
    if not message:
        return jsonify({'error': 'Mesaj boş olamaz!'}), 400
    
    try:
        reply = pixelBunnyAI.chat_send(message)
        now_str = time.strftime('%H:%M')
        
        if is_system:
            # Sistem promptunun kendisi önyüzde görünmez ve listeye eklenmez.
            # Yalnızca AI'ın bu ilk adıma verdiği asistan cevabı kaydedilir:
            assistant_item = {
                'id': uuid.uuid4().hex,
                'role': 'assistant',
                'text': reply,
                'created_at': now_str
            }
            CHAT_HISTORY.append(assistant_item)
            return jsonify({'success': True, 'reply': reply, 'item': assistant_item})
        else:
            user_item = {
                'id': uuid.uuid4().hex,
                'role': 'user',
                'text': message,
                'created_at': now_str
            }
            assistant_item = {
                'id': uuid.uuid4().hex,
                'role': 'assistant',
                'text': reply,
                'created_at': now_str
            }
            CHAT_HISTORY.append(user_item)
            CHAT_HISTORY.append(assistant_item)
            return jsonify({'success': True, 'reply': reply, 'user_item': user_item, 'assistant_item': assistant_item})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/delete', methods=['POST'])
def delete_chat_message():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    item_id = request.json.get('id')
    global CHAT_HISTORY
    CHAT_HISTORY = [m for m in CHAT_HISTORY if m.get('id') != item_id]
    return jsonify({'success': True})

@app.route('/api/chat/reset', methods=['POST'])
def chat_reset_session():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    global CHAT_HISTORY
    CHAT_HISTORY = []
    if pixelBunnyAI:
        pixelBunnyAI.chat_reset()
    return jsonify({'success': True})

# DIRECT PROXY DOWNLOAD
@app.route('/api/download')
def proxy_download():
    if not is_logged_in():
        return "Unauthorized", 401
    url = request.args.get('url')
    if not url:
        return "Missing url parameter", 400
    try:
        res = requests.get(url, stream=True, timeout=60)
        if res.status_code != 200:
            return "Failed to fetch media", 500
        
        content_type = res.headers.get('Content-Type', '')
        if 'video' in content_type.lower() or '.mp4' in url.lower():
            filename = f"wildowl_video_{int(time.time())}.mp4"
            if not content_type or 'octet-stream' in content_type:
                content_type = 'video/mp4'
        else:
            filename = f"wildowl_{int(time.time())}.jpg"
            if 'png' in content_type:
                filename = f"wildowl_{int(time.time())}.png"
            if not content_type:
                content_type = 'image/jpeg'
            
        headers = {
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': content_type
        }
        return Response(res.iter_content(chunk_size=8192), headers=headers)
    except Exception as e:
        return f"Error downloading: {str(e)}", 500

# START GENERATION JOB
@app.route('/api/generate/start', methods=['POST'])
def start_generation():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    prompt = request.form.get('prompt', '').strip()
    model = request.form.get('model', '').strip()
    aspect_ratio = request.form.get('aspect_ratio', '').strip()
    tier = request.form.get('tier', '').strip()
    resolution = request.form.get('resolution', '').strip()
    num_images = int(request.form.get('num_images', 1))
    
    if not prompt:
        return jsonify({'error': 'Prompt girmelisiniz!'}), 400
    if model not in MODELS_CONFIG:
        return jsonify({'error': 'Geçersiz model seçimi!'}), 400
        
    # Clean up jobs older than 1 hour to prevent memory leak
    now = time.time()
    for jid in list(ACTIVE_JOBS.keys()):
        if now - ACTIVE_JOBS[jid]['created_at'] > 3600:
            ACTIVE_JOBS.pop(jid, None)
    
    job_id = uuid.uuid4().hex
    
    # Store image file contents in memory (RAM) instead of disk
    memory_images = []
    file_keys = ['image_1', 'image_2', 'image_3', 'image_4', 'image_5', 'image_6']
    for idx, key in enumerate(file_keys):
        if key in request.files:
            file = request.files[key]
            if file and file.filename != '':
                file_bytes = file.read()
                if len(file_bytes) > 0:
                    memory_images.append({
                        'filename': file.filename,
                        'content': file_bytes,
                        'content_type': file.content_type or 'image/jpeg'
                    })
                
    # Audio file upload for Wan 2.6
    wan_audio_path = None
    if 'wan_audio_file' in request.files:
        audio_file = request.files['wan_audio_file']
        if audio_file and audio_file.filename:
            temp_dir = os.path.join(ROOT_DIR, "scratch")
            os.makedirs(temp_dir, exist_ok=True)
            ext = os.path.splitext(audio_file.filename)[1] or ".mp3"
            wan_audio_path = os.path.join(temp_dir, f"wan_audio_{job_id}{ext}")
            audio_file.save(wan_audio_path)

    # WAN 2.6 Extra parameters from request or model config defaults
    extra_cfg = MODELS_CONFIG.get(model, {}).get("extra_settings", {})
    wan_params = {
        'enable_safety_checker': request.form.get('enable_safety_checker', str(extra_cfg.get('enable_safety_checker', False))).lower() == 'true',
        'enable_prompt_expansion': request.form.get('enable_prompt_expansion', str(extra_cfg.get('enable_prompt_expansion', False))).lower() == 'true',
        'multi_shots': request.form.get('multi_shots', str(extra_cfg.get('multi_shots', False))).lower() == 'true',
        'camerafixed': request.form.get('camerafixed', str(extra_cfg.get('camerafixed', False))).lower() == 'true',
        'loop': request.form.get('loop', str(extra_cfg.get('loop', False))).lower() == 'true',
        'auto_fix': request.form.get('auto_fix', str(extra_cfg.get('auto_fix', False))).lower() == 'true',
        'generate_audio': request.form.get('generate_audio', str(extra_cfg.get('generate_audio', True))).lower() == 'true',
        'negative_prompt': request.form.get('wan_negative', extra_cfg.get('negative_prompt', '')).strip(),
        'audio_url': request.form.get('wan_audio_url', extra_cfg.get('audio_url', '')).strip(),
        'audio_path': wan_audio_path,
        'movement_amplitude': request.form.get('movement_amplitude', extra_cfg.get('movement_amplitude', 'auto')),
        'seed': request.form.get('seed')
    }

    # Agnes Extra parameters from request or model config defaults
    agnes_extra_cfg = MODELS_CONFIG.get(model, {}).get("extra_settings", {})
    agnes_params = {
        'fps': int(request.form.get('agnes_fps', agnes_extra_cfg.get('fps', 24))),
        'enable_prompt_expansion': request.form.get('agnes_expand', str(agnes_extra_cfg.get('enable_prompt_expansion', False))).lower() == 'true',
        'negative_prompt': request.form.get('agnes_negative', agnes_extra_cfg.get('negative_prompt', '')),
        'seed': request.form.get('agnes_seed', request.form.get('seed')),
        'strength': float(request.form.get('agnes_strength', agnes_extra_cfg.get('strength', 0.75)))
    }

    # deAPI Extra parameters from request or model config defaults
    deapi_extra_cfg = MODELS_CONFIG.get(model, {}).get("extra_settings", {})
    deapi_audio_file = request.files.get('deapi_audio_file')
    deapi_audio_path = None
    if deapi_audio_file and deapi_audio_file.filename:
        temp_dir = os.path.join(ROOT_DIR, "scratch")
        os.makedirs(temp_dir, exist_ok=True)
        ext = os.path.splitext(deapi_audio_file.filename)[1] or ".mp3"
        deapi_audio_path = os.path.join(temp_dir, f"deapi_audio_{job_id}{ext}")
        deapi_audio_file.save(deapi_audio_path)

    deapi_video_file = request.files.get('deapi_video_file')
    deapi_video_path = None
    if deapi_video_file and deapi_video_file.filename:
        temp_dir = os.path.join(ROOT_DIR, "scratch")
        os.makedirs(temp_dir, exist_ok=True)
        ext = os.path.splitext(deapi_video_file.filename)[1] or ".mp4"
        deapi_video_path = os.path.join(temp_dir, f"deapi_video_{job_id}{ext}")
        deapi_video_file.save(deapi_video_path)

    deapi_fps = 24  # deAPI modellerinde 24 FPS zorunludur

    deapi_params = {
        'fps': deapi_fps,
        'enable_prompt_expansion': request.form.get('deapi_expand', str(deapi_extra_cfg.get('enable_prompt_expansion', False))).lower() == 'true',
        'negative_prompt': request.form.get('deapi_negative', deapi_extra_cfg.get('negative_prompt', '')),
        'seed': request.form.get('deapi_seed', request.form.get('seed')),
        'audio_url': request.form.get('deapi_audio_url', '').strip(),
        'audio_path': deapi_audio_path,
        'video_url': request.form.get('deapi_video_url', '').strip(),
        'video_path': deapi_video_path,
        'ref_mode': 'frames' if model == "LTX 2.5 Video" else request.form.get('ref_mode', 'gallery')
    }

    if model == "LTX 2.5 Video":
        deapi_params['audio_url'] = ''
        deapi_params['audio_path'] = None
        deapi_params['video_url'] = ''
        deapi_params['video_path'] = None

    # Store parameters & files directly in RAM dict
    ACTIVE_JOBS[job_id] = {
        'prompt': prompt,
        'model': model,
        'aspect_ratio': aspect_ratio,
        'tier': tier,
        'resolution': resolution,
        'num_images': num_images,
        'images': memory_images,
        'wan_params': wan_params,
        'agnes_params': agnes_params,
        'deapi_params': deapi_params,
        'created_at': time.time(),
        'status': 'registering',
        'pct': 0,
        'logs': [],
        'outputs': [],
        'error': None
    }
    
    t = threading.Thread(target=run_job_in_background, args=(job_id,))
    t.daemon = True
    t.start()
    
    return jsonify({'job_id': job_id})

# POP VID EXTEND JOB
@app.route('/api/popvid/extend', methods=['POST'])
def start_popvid_extend():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json() or {}
    meme_id = data.get('meme_id', '').strip()
    prompt = data.get('prompt', '').strip()
    video_url = data.get('video_url', '').strip()
    user_id = data.get('user_id')
    id_token = data.get('id_token')
    
    # Otomatik meme_id kurtarma / fallback
    if not meme_id:
        if video_url:
            for item in GENERATION_HISTORY:
                if item.get('url') == video_url and item.get('meme_id'):
                    meme_id = item.get('meme_id')
                    user_id = user_id or item.get('user_id')
                    id_token = id_token or item.get('id_token')
                    break
        if not meme_id:
            for item in GENERATION_HISTORY:
                if item.get('model') == 'Pop Vid' and item.get('meme_id'):
                    meme_id = item.get('meme_id')
                    user_id = user_id or item.get('user_id')
                    id_token = id_token or item.get('id_token')
                    break
        if not meme_id and popVidAI and hasattr(popVidAI, 'get_last_meme_id'):
            meme_id = popVidAI.get_last_meme_id()
            
    if not meme_id:
        return jsonify({'error': 'Uzatılacak video referans bilgisi (Meme ID) bulunamadı!'}), 400
    if not prompt:
        return jsonify({'error': 'Uzatma promptu boş olamaz!'}), 400
        
    now = time.time()
    for jid in list(ACTIVE_JOBS.keys()):
        if now - ACTIVE_JOBS[jid]['created_at'] > 3600:
            ACTIVE_JOBS.pop(jid, None)
            
    job_id = uuid.uuid4().hex
    ACTIVE_JOBS[job_id] = {
        'prompt': prompt,
        'model': 'Pop Vid',
        'aspect_ratio': '16:9',
        'tier': 'standard',
        'resolution': '720p',
        'num_images': 1,
        'images': [],
        'is_extend': True,
        'meme_id': meme_id,
        'extend_meme_id': meme_id,
        'extend_user_id': user_id,
        'extend_id_token': id_token,
        'created_at': time.time(),
        'status': 'registering',
        'pct': 0,
        'logs': [],
        'outputs': [],
        'error': None
    }
    
    t = threading.Thread(target=run_job_in_background, args=(job_id,))
    t.daemon = True
    t.start()
    
    return jsonify({'job_id': job_id})

def run_job_in_background(job_id):
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        return
        
    def add_log(msg, status="info", pct=None):
        if job_id not in ACTIVE_JOBS:
            return
        if pct is not None:
            job['pct'] = pct
        if status in ["generating", "queued", "registering", "processing", "completed", "failed"]:
            job['status'] = status
        now = time.time()
        lt = time.localtime(now)
        time_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
        job['logs'].append({
            'message': msg,
            'status': status,
            'pct': job['pct'],
            'time': time_str
        })
        
    prompt = job['prompt']
    model_name = job['model']
    aspect_ratio = job['aspect_ratio']
    tier = job['tier']
    num_images = job['num_images']
    resolution = job.get('resolution', '')
    images = job['images']
    
    try:
        add_log("İşlem başlatıldı...", "info", 5)
        
        if job_id not in ACTIVE_JOBS: return

        # VIBE VIDEO HANDLER
        if model_name == "Vibe Video":
            if not vibeVideo:
                add_log("Vibe Video modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'Vibe Video modülü bulunamadı.'
                return

            add_log("Vibe Video motoru hazırlanıyor...", "registering", 5)
            temp_img_path = None
            if images and len(images) > 0:
                img_data = images[0]
                ext = ".jpg"
                if "png" in img_data.get("content_type", "").lower():
                    ext = ".png"
                temp_dir = os.path.join(ROOT_DIR, "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                temp_img_path = os.path.join(temp_dir, f"vibe_input_{job_id}{ext}")
                with open(temp_img_path, "wb") as f:
                    f.write(img_data['content'])
            else:
                test_jpg = os.path.join(ROOT_DIR, "test.jpg")
                if os.path.exists(test_jpg):
                    temp_img_path = test_jpg
                else:
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_img_path = os.path.join(temp_dir, f"fallback_{job_id}.jpg")
                    with open(temp_img_path, "wb") as f:
                        f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9')

            try:
                res = vibeVideo.run_once(
                    image_path=temp_img_path,
                    prompt=prompt,
                    model="basic",
                    log_callback=add_log
                )
                output_url = res.get("output")
                if output_url:
                    item = {
                        'id': uuid.uuid4().hex,
                        'url': output_url,
                        'prompt': prompt,
                        'model': model_name,
                        'aspect_ratio': aspect_ratio or "16:9",
                        'tier': tier or "standard",
                        'type': "video",
                        'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                    }
                    GENERATION_HISTORY.insert(0, item)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                        ACTIVE_JOBS[job_id]['status'] = 'completed'
                else:
                    raise RuntimeError("Vibe Video üretimi URL üretmedi.")
            except Exception as vibe_err:
                add_log(f"Vibe Video Hatası: {str(vibe_err)}", "error", 90)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = str(vibe_err)
            finally:
                if temp_img_path and "vibe_input_" in temp_img_path and os.path.exists(temp_img_path):
                    try:
                        os.remove(temp_img_path)
                    except Exception:
                        pass
            return

        # POP VID HANDLER
        if model_name == "Pop Vid":
            if not popVidAI:
                add_log("Pop Vid modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'Pop Vid modülü bulunamadı.'
                return

            # Extend (Uzatma) isteği mi?
            if job.get('is_extend'):
                add_log("Pop Vid video uzatma işlemi hazırlanıyor...", "registering", 5)
                try:
                    res = popVidAI.run_extend(
                        meme_id=job.get('extend_meme_id'),
                        prompt=prompt,
                        character_type="human",
                        user_id=job.get('extend_user_id'),
                        id_token=job.get('extend_id_token'),
                        log_callback=add_log
                    )
                    output_url = res.get("output")
                    if output_url:
                        item = {
                            'id': uuid.uuid4().hex,
                            'url': output_url,
                            'prompt': prompt,
                            'model': model_name,
                            'aspect_ratio': aspect_ratio or "16:9",
                            'tier': tier or "standard",
                            'type': "video",
                            'meme_id': res.get('meme_id'),
                            'user_id': res.get('user_id'),
                            'id_token': res.get('id_token'),
                            'is_extend': True,
                            'source_meme_id': job.get('extend_meme_id'),
                            'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                        }
                        GENERATION_HISTORY.insert(0, item)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                            ACTIVE_JOBS[job_id]['meme_id'] = res.get('meme_id')
                            ACTIVE_JOBS[job_id]['user_id'] = res.get('user_id')
                            ACTIVE_JOBS[job_id]['id_token'] = res.get('id_token')
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                    else:
                        raise RuntimeError("Pop Vid video uzatma URL üretmedi.")
                except Exception as pop_err:
                    add_log(f"Pop Vid Uzatma Hatası: {str(pop_err)}", "error", 90)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['status'] = 'failed'
                        ACTIVE_JOBS[job_id]['error'] = str(pop_err)
                return

            # Sıfırdan Pop Vid üretimi
            add_log("Pop Vid motoru hazırlanıyor...", "registering", 5)
            temp_img_path = None
            if images and len(images) > 0:
                img_data = images[0]
                ext = ".jpg"
                if "png" in img_data.get("content_type", "").lower():
                    ext = ".png"
                temp_dir = os.path.join(ROOT_DIR, "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                temp_img_path = os.path.join(temp_dir, f"popvid_input_{job_id}{ext}")
                with open(temp_img_path, "wb") as f:
                    f.write(img_data['content'])
            else:
                test_jpg = os.path.join(ROOT_DIR, "test.jpg")
                if os.path.exists(test_jpg):
                    temp_img_path = test_jpg
                else:
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_img_path = os.path.join(temp_dir, f"fallback_{job_id}.jpg")
                    with open(temp_img_path, "wb") as f:
                        f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9')

            try:
                res = popVidAI.run_once(
                    image_path=temp_img_path,
                    prompt=prompt,
                    character_type="human",
                    log_callback=add_log
                )
                output_url = res.get("output")
                if output_url:
                    item = {
                        'id': uuid.uuid4().hex,
                        'url': output_url,
                        'prompt': prompt,
                        'model': model_name,
                        'aspect_ratio': aspect_ratio or "16:9",
                        'tier': tier or "standard",
                        'type': "video",
                        'meme_id': res.get('meme_id'),
                        'user_id': res.get('user_id'),
                        'id_token': res.get('id_token'),
                        'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                    }
                    GENERATION_HISTORY.insert(0, item)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                        ACTIVE_JOBS[job_id]['meme_id'] = res.get('meme_id')
                        ACTIVE_JOBS[job_id]['user_id'] = res.get('user_id')
                        ACTIVE_JOBS[job_id]['id_token'] = res.get('id_token')
                        ACTIVE_JOBS[job_id]['status'] = 'completed'
                else:
                    raise RuntimeError("Pop Vid video üretimi URL üretmedi.")
            except Exception as pop_err:
                add_log(f"Pop Vid Hatası: {str(pop_err)}", "error", 90)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = str(pop_err)
            finally:
                if temp_img_path and "popvid_input_" in temp_img_path and os.path.exists(temp_img_path):
                    try:
                        os.remove(temp_img_path)
                    except Exception:
                        pass
            return

        # TOPVID WAN 2.6 HANDLER
        if model_name in ["Wan 2.6 Video", "Wan 2.6 (Video)"]:
            if not topVidAI:
                add_log("TopVid Wan 2.6 modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'TopVid Wan 2.6 modülü bulunamadı.'
                return

            add_log("TopVid Wan 2.6 motoru hazırlanıyor...", "registering", 5)
            temp_img_path = None
            if images and len(images) > 0:
                img_data = images[0]
                ext = ".jpg"
                if "png" in img_data.get("content_type", "").lower():
                    ext = ".png"
                temp_dir = os.path.join(ROOT_DIR, "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                temp_img_path = os.path.join(temp_dir, f"topvid_input_{job_id}{ext}")
                with open(temp_img_path, "wb") as f:
                    f.write(img_data['content'])

            try:
                # tier maps to duration ("5", "10", "15")
                duration = tier if tier in ["5", "10", "15"] else "5"
                # resolution ("720p", "1080p")
                res_choice = resolution if resolution in ["720p", "1080p"] else "720p"
                # aspect_ratio ("16:9", "9:16", "1:1", "4:3", "3:4")
                ar_choice = aspect_ratio or "16:9"

                wan_p = job.get('wan_params') or {}
                res = topVidAI.run_once(
                    prompt=prompt,
                    image_path=temp_img_path,
                    aspect_ratio=ar_choice,
                    duration=duration,
                    resolution=res_choice,
                    log_callback=add_log,
                    enable_safety_checker=wan_p.get('enable_safety_checker', False),
                    enable_prompt_expansion=wan_p.get('enable_prompt_expansion', False),
                    multi_shots=wan_p.get('multi_shots', False),
                    camerafixed=wan_p.get('camerafixed', False),
                    loop=wan_p.get('loop', False),
                    auto_fix=wan_p.get('auto_fix', False),
                    movement_amplitude=wan_p.get('movement_amplitude', 'auto'),
                    generate_audio=wan_p.get('generate_audio', True),
                    negative_prompt=wan_p.get('negative_prompt', ''),
                    audio_path=wan_p.get('audio_path'),
                    audio_url=wan_p.get('audio_url', ''),
                    seed=wan_p.get('seed')
                )
                output_url = res.get("output")
                if output_url:
                    item = {
                        'id': uuid.uuid4().hex,
                        'url': output_url,
                        'prompt': prompt,
                        'model': model_name,
                        'aspect_ratio': ar_choice,
                        'tier': duration,
                        'resolution': res_choice,
                        'type': "video",
                        'task_id': res.get('task_id'),
                        'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                    }
                    GENERATION_HISTORY.insert(0, item)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                        ACTIVE_JOBS[job_id]['status'] = 'completed'
                else:
                    raise RuntimeError("Wan 2.6 video üretimi URL üretmedi.")
            except Exception as tv_err:
                add_log(f"Wan 2.6 Hatası: {str(tv_err)}", "error", 90)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = str(tv_err)
            finally:
                if temp_img_path and "topvid_input_" in temp_img_path and os.path.exists(temp_img_path):
                    try:
                        os.remove(temp_img_path)
                    except Exception:
                        pass
                if wan_p.get('audio_path') and os.path.exists(wan_p['audio_path']):
                    try:
                        os.remove(wan_p['audio_path'])
                    except Exception:
                        pass
            return

        # MORPH STUDIO HANDLER (Seedance 1.0 Pro Fast, GPT Image 2.5 & Nano Banana 2.1)
        if model_name in ["Seedance 1.0 Pro Fast", "Seedance Pro Fast", "Nano Banana 2.1", "GPT Image 2.5 (Sunburst)", "GPT Image 2.5 (Flare)"] or (MODELS_CONFIG.get(model_name, {}).get("provider") == "morph"):
            if not morphStudioAI:
                add_log("Morph Studio modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'Morph Studio modülü bulunamadı.'
                return

            model_cfg = MODELS_CONFIG.get(model_name, {})
            is_video = model_cfg.get("type") == "video"

            if is_video:
                add_log(f"Morph Studio ({model_name}) video motoru hazırlanıyor...", "registering", 5)
                temp_img_path = None
                if images and len(images) > 0:
                    img_data = images[0]
                    ext = ".jpg"
                    if "png" in img_data.get("content_type", "").lower():
                        ext = ".png"
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_img_path = os.path.join(temp_dir, f"morph_vid_input_{job_id}{ext}")
                    with open(temp_img_path, "wb") as f:
                        f.write(img_data['content'])

                try:
                    duration = int(tier) if tier in ["5", "10"] else 5
                    res_choice = resolution if resolution in ["480p", "720p", "1080p"] else "480p"
                    model_id = model_cfg.get("model_id", "seedance_v1_pro_fast")

                    res = morphStudioAI.run_video(
                        prompt=prompt,
                        image_path=temp_img_path,
                        model_id=model_id,
                        duration=duration,
                        resolution=res_choice,
                        log_callback=add_log
                    )
                    output_url = res.get("output")
                    if output_url:
                        item = {
                            'id': uuid.uuid4().hex,
                            'url': output_url,
                            'prompt': prompt,
                            'model': model_name,
                            'aspect_ratio': aspect_ratio or "16:9",
                            'tier': str(duration),
                            'resolution': res_choice,
                            'type': "video",
                            'node_id': res.get('node_id'),
                            'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                        }
                        GENERATION_HISTORY.insert(0, item)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                    else:
                        raise RuntimeError("Morph Studio video üretimi URL üretmedi.")
                except Exception as m_err:
                    add_log(f"Morph Studio Video Hatası: {str(m_err)}", "error", 90)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['status'] = 'failed'
                        ACTIVE_JOBS[job_id]['error'] = str(m_err)
                finally:
                    if temp_img_path and "morph_vid_input_" in temp_img_path and os.path.exists(temp_img_path):
                        try:
                            os.remove(temp_img_path)
                        except Exception:
                            pass
                return

            else:
                # Image handler: GPT Image 2.5 (Sunburst / Flare)
                add_log(f"Morph Studio ({model_name}) görsel motoru hazırlanıyor...", "registering", 5)
                temp_img_paths = []
                if images and len(images) > 0:
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    for idx, img_data in enumerate(images):
                        ext = ".jpg"
                        if "png" in img_data.get("content_type", "").lower():
                            ext = ".png"
                        p = os.path.join(temp_dir, f"morph_img_input_{job_id}_{idx}{ext}")
                        with open(p, "wb") as f:
                            f.write(img_data['content'])
                        temp_img_paths.append(p)

                try:
                    model_id = model_cfg.get("model_id", "openai/gpt-image-2.5")
                    mode = model_cfg.get("mode", "sunburst")
                    ar_choice = aspect_ratio or "1:1"
                    quality_choice = tier if tier in ["low", "medium", "high", "xhigh"] else "medium"
                    res_choice = resolution if resolution in ["1k", "2k", "4k"] else "2k"

                    res = morphStudioAI.run_image(
                        prompt=prompt,
                        image_paths=temp_img_paths if temp_img_paths else None,
                        model_id=model_id,
                        mode=mode,
                        aspect_ratio=ar_choice,
                        quality=quality_choice,
                        resolution=res_choice,
                        log_callback=add_log
                    )
                    outputs = res.get("outputs", [])
                    if outputs:
                        for url in outputs:
                            item = {
                                'id': uuid.uuid4().hex,
                                'url': url,
                                'prompt': prompt,
                                'model': model_name,
                                'aspect_ratio': ar_choice,
                                'tier': quality_choice,
                                'resolution': res_choice,
                                'type': "image",
                                'node_id': res.get('node_id'),
                                'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                            }
                            GENERATION_HISTORY.insert(0, item)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = outputs
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                    else:
                        raise RuntimeError("Morph Studio görsel üretimi URL üretmedi.")
                except Exception as m_err:
                    add_log(f"Morph Studio Görsel Hatası: {str(m_err)}", "error", 90)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['status'] = 'failed'
                        ACTIVE_JOBS[job_id]['error'] = str(m_err)
                finally:
                    for p in temp_img_paths:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                return

        # AGNES AI HANDLER (Agnes Video 2.0 & Agnes Image Modelleri)
        if model_name.startswith("Agnes") or (MODELS_CONFIG.get(model_name, {}).get("provider") == "agnes"):
            if not agnesAI:
                add_log("Agnes AI modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'Agnes AI modülü bulunamadı.'
                return

            model_cfg = MODELS_CONFIG.get(model_name, {})
            is_video = model_cfg.get("type") == "video"

            if is_video:
                add_log(f"Agnes AI ({model_name}) video motoru hazırlanıyor...", "registering", 5)
                temp_img_paths = []
                for idx, img_data in enumerate(images[:2]):
                    ext = ".jpg"
                    if "png" in img_data.get("content_type", "").lower():
                        ext = ".png"
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    t_path = os.path.join(temp_dir, f"agnes_vid_ref_{job_id}_{idx}{ext}")
                    with open(t_path, "wb") as f:
                        f.write(img_data['content'])
                    temp_img_paths.append(t_path)

                try:
                    duration_choice = tier if tier in ["3", "5", "8", "10", "15", "20", "30", "40"] else "5"
                    res_choice = resolution if resolution in ["480p", "720p", "1080p"] else "720p"
                    ar_choice = aspect_ratio or "16:9"

                    agnes_p = job.get('agnes_params') or {}
                    res = agnesAI.run_video(
                        prompt=prompt,
                        images=temp_img_paths,
                        aspect_ratio=ar_choice,
                        duration=duration_choice,
                        resolution=res_choice,
                        fps=int(agnes_p.get('fps', 24)),
                        enable_prompt_expansion=bool(agnes_p.get('enable_prompt_expansion', False)),
                        negative_prompt=agnes_p.get('negative_prompt', ""),
                        seed=agnes_p.get('seed'),
                        log_callback=add_log
                    )
                    output_url = res.get("output")
                    if output_url:
                        item = {
                            'id': uuid.uuid4().hex,
                            'url': output_url,
                            'prompt': prompt,
                            'model': model_name,
                            'aspect_ratio': ar_choice,
                            'tier': duration_choice,
                            'resolution': res_choice,
                            'type': "video",
                            'task_id': res.get('task_id'),
                            'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                        }
                        GENERATION_HISTORY.insert(0, item)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                    else:
                        raise RuntimeError("Agnes Video üretimi URL üretmedi.")
                except Exception as a_err:
                    add_log(f"Agnes Video Hatası: {str(a_err)}", "error", 90)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['status'] = 'failed'
                        ACTIVE_JOBS[job_id]['error'] = str(a_err)
                finally:
                    for p in temp_img_paths:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                return
            else:
                # Agnes Image Modelleri
                add_log(f"Agnes AI ({model_name}) görsel motoru hazırlanıyor...", "registering", 5)
                temp_img_paths = []
                for idx, img_data in enumerate(images[:6]):
                    ext = ".jpg"
                    if "png" in img_data.get("content_type", "").lower():
                        ext = ".png"
                    temp_dir = os.path.join(ROOT_DIR, "scratch")
                    os.makedirs(temp_dir, exist_ok=True)
                    t_path = os.path.join(temp_dir, f"agnes_img_ref_{job_id}_{idx}{ext}")
                    with open(t_path, "wb") as f:
                        f.write(img_data['content'])
                    temp_img_paths.append(t_path)

                try:
                    res_choice = resolution if resolution in ["1K", "2K", "3K", "4K"] else "2K"
                    ar_choice = aspect_ratio or "1:1"
                    model_id = model_cfg.get("model_id", "agnes-image-2.5-flash")

                    agnes_p = job.get('agnes_params') or {}
                    res = agnesAI.run_image(
                        prompt=prompt,
                        model=model_id,
                        aspect_ratio=ar_choice,
                        resolution=res_choice,
                        negative_prompt=agnes_p.get('negative_prompt', ""),
                        seed=agnes_p.get('seed'),
                        images=temp_img_paths,
                        strength=float(agnes_p.get('strength', 0.75)),
                        enable_prompt_expansion=bool(agnes_p.get('enable_prompt_expansion', False)),
                        log_callback=add_log
                    )
                    output_url = res.get("output")
                    if output_url:
                        item = {
                            'id': uuid.uuid4().hex,
                            'url': output_url,
                            'prompt': prompt,
                            'model': model_name,
                            'aspect_ratio': ar_choice,
                            'tier': tier or "standard",
                            'resolution': res_choice,
                            'type': "image",
                            'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                        }
                        GENERATION_HISTORY.insert(0, item)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                    else:
                        raise RuntimeError("Agnes Görsel üretimi URL üretmedi.")
                except Exception as a_err:
                    add_log(f"Agnes Görsel Hatası: {str(a_err)}", "error", 90)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['status'] = 'failed'
                        ACTIVE_JOBS[job_id]['error'] = str(a_err)
                finally:
                    for p in temp_img_paths:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                return

        # DEAPI VIDEO HANDLER (MiniMax H3 Video & LTX 2.5 Video)
        if model_name in ["MiniMax H3 Video", "LTX 2.5 Video"] or (MODELS_CONFIG.get(model_name, {}).get("provider") == "deapi"):
            if not deApiAI:
                add_log("deAPI AI modülü yüklenemedi!", "error", 5)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'deAPI AI modülü bulunamadı.'
                return

            model_cfg = MODELS_CONFIG.get(model_name, {})
            model_slug = model_cfg.get("model_slug") or model_cfg.get("model_id", "MiniMaxH3_33B_Turbo_INT8")
            add_log(f"deAPI ({model_name}) video motoru hazırlanıyor...", "registering", 5)

            temp_img_paths = []
            for idx, img_data in enumerate(images[:3]):
                ext = ".jpg"
                if "png" in img_data.get("content_type", "").lower():
                    ext = ".png"
                temp_dir = os.path.join(ROOT_DIR, "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                t_path = os.path.join(temp_dir, f"deapi_vid_ref_{job_id}_{idx}{ext}")
                with open(t_path, "wb") as f:
                    f.write(img_data['content'])
                temp_img_paths.append(t_path)

            try:
                duration_choice = tier if tier in ["5", "10"] else "5"
                res_choice = resolution if resolution in ["768p", "720p"] else "768p"
                ar_choice = aspect_ratio or "16:9"

                deapi_p = job.get('deapi_params') or {}
                is_ltx_model = "ltx" in model_slug.lower() or model_name == "LTX 2.5 Video"
                res = deApiAI.run_video(
                    prompt=prompt,
                    images=temp_img_paths,
                    aspect_ratio=ar_choice,
                    duration=duration_choice,
                    resolution=res_choice,
                    model=model_slug,
                    negative_prompt=deapi_p.get('negative_prompt', ""),
                    enhance_prompt=bool(deapi_p.get('enable_prompt_expansion', False)),
                    seed=deapi_p.get('seed'),
                    fps=deapi_p.get('fps'),
                    audio_path=None if is_ltx_model else deapi_p.get('audio_path'),
                    audio_url="" if is_ltx_model else deapi_p.get('audio_url'),
                    video_path=None if is_ltx_model else deapi_p.get('video_path'),
                    video_url="" if is_ltx_model else deapi_p.get('video_url'),
                    ref_mode="frames" if is_ltx_model else deapi_p.get('ref_mode', 'gallery'),
                    log_callback=add_log,
                    job_id=job_id,
                    is_active=lambda: job_id in ACTIVE_JOBS
                )
                output_url = res.get("output")
                if output_url:
                    item = {
                        'id': uuid.uuid4().hex,
                        'url': output_url,
                        'prompt': prompt,
                        'model': model_name,
                        'aspect_ratio': ar_choice,
                        'tier': duration_choice,
                        'resolution': res_choice,
                        'type': "video",
                        'request_id': res.get('request_id'),
                        'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                    }
                    GENERATION_HISTORY.insert(0, item)
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]['outputs'] = [output_url]
                        ACTIVE_JOBS[job_id]['status'] = 'completed'
                else:
                    raise RuntimeError("deAPI Video üretimi URL üretmedi.")
            except Exception as d_err:
                add_log(f"deAPI Video Hatası: {str(d_err)}", "error", 90)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = str(d_err)
            finally:
                for p in temp_img_paths:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                a_path = (job.get('deapi_params') or {}).get('audio_path')
                if a_path and os.path.exists(a_path):
                    try:
                        os.remove(a_path)
                    except Exception:
                        pass
                v_path = (job.get('deapi_params') or {}).get('video_path')
                if v_path and os.path.exists(v_path):
                    try:
                        os.remove(v_path)
                    except Exception:
                        pass
            return
        
        # Step 1: E-posta oluşturma ve kayıt
        add_log("Temp mail & proxy üzerinden geçici e-posta alınıyor...", "registering", 10)
        temp = eTemp()
        email = temp.get_email()
        add_log(f"Geçici e-posta oluşturuldu: {email}", "registering", 15)
        
        if job_id not in ACTIVE_JOBS: return
        
        add_log("Wild Owl (Supabase Auth) kayıt isteği gönderiliyor...", "registering", 20)
        signup_url = "https://vskypkjrqdawuecizqph.supabase.co/auth/v1/signup"
        params = {"redirect_to": "https://wildowl.ai"}
        headers = {
            "apikey": "sb_publishable_JMp6RT7orAG20nHNDt5F5A_ep6l_Cx7",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://wildowl.ai",
            "referer": "https://wildowl.ai/",
            "x-client-info": "supabase-js-web/2.98.0",
            "x-supabase-api-version": "2024-01-01",
        }
        password = "SifreniYaz123!"
        payload = {
            "email": email,
            "password": password,
            "data": {},
            "gotrue_meta_security": {},
            "code_challenge": None,
            "code_challenge_method": None,
        }
        
        res = requests.post(signup_url, params=params, headers=headers, json=payload, timeout=10)
        if res.status_code not in [200, 201]:
            add_log(f"Kayıt hatası: {res.text}", "error", 20)
            if job_id in ACTIVE_JOBS:
                ACTIVE_JOBS[job_id]['status'] = 'failed'
                ACTIVE_JOBS[job_id]['error'] = 'Wild Owl Supabase kayıt başarısız.'
            return
        
        if job_id not in ACTIVE_JOBS: return
        
        add_log("Doğrulama e-postası bekleniyor (Temp mail kutusu taranıyor)...", "registering", 25)
        confirm_link = temp.get_signup_url_from_inbox(email, max_retries=30)
        if confirm_link:
            import html as _html
            confirm_link = _html.unescape(confirm_link).replace("&amp;", "&").strip()
            while any(confirm_link.endswith(s) for s in ['&quot;', '&quot', '"', "'", '>', ';']):
                for s in ['&quot;', '&quot', '"', "'", '>', ';']:
                    if confirm_link.endswith(s):
                        confirm_link = confirm_link[:-len(s)].strip()
        
        if job_id not in ACTIVE_JOBS: return
        
        if not confirm_link:
            add_log("Doğrulama e-postası zaman aşımına uğradı.", "error", 25)
            if job_id in ACTIVE_JOBS:
                ACTIVE_JOBS[job_id]['status'] = 'failed'
                ACTIVE_JOBS[job_id]['error'] = 'E-posta doğrulama linki bulunamadı.'
            return
            
        add_log(f"Onay linki yakalandı: {confirm_link}", "registering", 35)
        headers_ver = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
            "origin": "https://wildowl.ai",
            "referer": "https://wildowl.ai/",
        }
        confirm_res = requests.get(confirm_link, headers=headers_ver, allow_redirects=True, timeout=15)
        add_log(f"E-posta başarıyla onaylandı (Sunucu yanıtı: {confirm_res.status_code})", "registering", 40)
        
        if job_id not in ACTIVE_JOBS: return
        
        # Step 2: Supabase Login
        add_log("Wild Owl hesabına giriş yapılıyor...", "login", 45)
        API_KEY = "sb_publishable_JMp6RT7orAG20nHNDt5F5A_ep6l_Cx7"
        login_url = "https://vskypkjrqdawuecizqph.supabase.co/auth/v1/token?grant_type=password"
        login_headers = {
            "apikey": API_KEY,
            "content-type": "application/json;charset=UTF-8",
        }
        login_payload = {"email": email, "password": password}
        login_res = requests.post(login_url, headers=login_headers, json=login_payload, timeout=10)
        
        if job_id not in ACTIVE_JOBS: return
        
        if login_res.status_code != 200:
            add_log(f"Giriş hatası: {login_res.text}", "error", 45)
            if job_id in ACTIVE_JOBS:
                ACTIVE_JOBS[job_id]['status'] = 'failed'
                ACTIVE_JOBS[job_id]['error'] = 'Giriş işlemi başarısız.'
            return
            
        login_data = login_res.json()
        access_token = login_data.get("access_token")
        user_id = login_data.get("user", {}).get("id")
        add_log(f"Giriş yapıldı! User ID: {user_id}", "login", 50)
        
        if job_id not in ACTIVE_JOBS: return
        
        # Step 3: Görselleri yükle
        uploaded_image_urls = []
        if images:
            add_log(f"{len(images)} adet referans görsel Supabase Storage'a yükleniyor...", "uploading", 55)
            upload_url = "https://vskypkjrqdawuecizqph.supabase.co/functions/v1/upload-input"
            upload_headers = {
                "authorization": f"Bearer {access_token}",
                "origin": "https://wildowl.ai",
                "referer": "https://wildowl.ai/",
                "accept": "*/*",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            for idx, img in enumerate(images):
                if job_id not in ACTIVE_JOBS: return
                add_log(f"Referans görsel {idx+1} yükleniyor: {img['filename']}...", "uploading", 60 + idx * 5)
                files = {"file": (img['filename'], io.BytesIO(img['content']), img['content_type'])}
                up_res = requests.post(upload_url, headers=upload_headers, files=files, timeout=20)
                
                if up_res.status_code == 200:
                    img_url = up_res.json().get("url")
                    uploaded_image_urls.append(img_url)
                    add_log(f"Görsel {idx+1} başarıyla yüklendi: {img_url}", "uploading", 65 + idx * 5)
                else:
                    add_log(f"Görsel {idx+1} yüklenirken hata oluştu! Kodu: {up_res.status_code}", "warning", 65 + idx * 5)
        
        if job_id not in ACTIVE_JOBS: return
        job['images'] = []
        
        # Step 4: Üretimi tetikle
        add_log(f"Görsel üretimi tetikleniyor (Model: {model_name})...", "generating", 75)
        config = MODELS_CONFIG[model_name]
        gen_url = "https://vskypkjrqdawuecizqph.supabase.co/functions/v1/generate"
        gen_headers = {
            "authorization": f"Bearer {access_token}",
            "apikey": API_KEY,
            "content-type": "application/json",
            "origin": "https://wildowl.ai",
            "referer": "https://wildowl.ai/",
            "x-client-info": "supabase-js-web/2.98.0"
        }
        
        gen_payload = {
            "generation_type": "image",
            "prompt": prompt,
            "num_images": num_images,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution if resolution else config["resolution"],
            "tier": tier,
            "model_id": config["model_id"]
        }
        
        if uploaded_image_urls:
            gen_payload["image_urls"] = uploaded_image_urls
            
        gen_res = requests.post(gen_url, headers=gen_headers, json=gen_payload, timeout=15)
        if gen_res.status_code != 200:
            add_log(f"Tetikleme hatası: {gen_res.text}", "error", 75)
            if job_id in ACTIVE_JOBS:
                ACTIVE_JOBS[job_id]['status'] = 'failed'
                ACTIVE_JOBS[job_id]['error'] = 'Üretim tetikleme başarısız oldu.'
            return
            
        add_log("Üretim kuyruğa alındı. Sonuçlar bekleniyor...", "generating", 80)
        
        # Step 5: Durum Sorgulama
        check_url = "https://vskypkjrqdawuecizqph.supabase.co/rest/v1/generations"
        check_params = {
            "select": "id,output_urls,thumbnail_url,prompt,metadata,generation_type,status,created_at,is_published,publish_status,error_message,model_id,credits_charged,user_id,publisher_nickname,local_only",
            "user_id": f"eq.{user_id}",
            "deleted_at": "is.null",
            "order": "created_at.desc",
            "offset": "0",
            "limit": "24"
        }
        check_headers = {
            "authorization": f"Bearer {access_token}",
            "apikey": API_KEY,
        }
        
        start_time = time.time()
        max_duration = 300
        
        while True:
            if job_id not in ACTIVE_JOBS:
                break
                
            if time.time() - start_time > max_duration:
                add_log("Üretim zaman aşımına uğradı (5 dakika limit doldu).", "error", 85)
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]['status'] = 'failed'
                    ACTIVE_JOBS[job_id]['error'] = 'Üretim zaman aşımı.'
                break
                
            check_res = requests.get(check_url, headers=check_headers, params=check_params, timeout=10)
            if check_res.status_code == 200:
                data = check_res.json()
                if len(data) > 0:
                    latest = data[0]
                    status = latest.get("status")
                    
                    if status == "completed":
                        outputs = latest.get("output_urls", [])
                        add_log("Üretim başarıyla tamamlandı!", "completed", 100)
                        
                        for url in outputs:
                            item = {
                                'id': uuid.uuid4().hex,
                                'url': url,
                                'prompt': prompt,
                                'model': model_name,
                                'aspect_ratio': aspect_ratio,
                                'tier': tier,
                                'created_at': time.strftime('%d.%m.%Y %H:%M:%S')
                            }
                            GENERATION_HISTORY.insert(0, item)
                        
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['outputs'] = outputs
                            ACTIVE_JOBS[job_id]['status'] = 'completed'
                        break
                    elif status == "failed":
                        err = latest.get("error_message") or "Bilinmeyen sunucu hatası"
                        add_log(f"Üretim sunucu tarafında başarısız oldu: {err}", "error", 90)
                        if job_id in ACTIVE_JOBS:
                            ACTIVE_JOBS[job_id]['status'] = 'failed'
                            ACTIVE_JOBS[job_id]['error'] = err
                        break
                    else:
                        # Map internal generation statuses
                        user_friendly_status = "generating"
                        if status == "registering":
                            user_friendly_status = "registering"
                        elif status == "login":
                            user_friendly_status = "login"
                        elif status == "uploading":
                            user_friendly_status = "uploading"
                        add_log(f"Üretim durumu: '{status}'. Bekleniyor...", user_friendly_status, 85)
                else:
                    add_log("Üretim durumu sorgulanıyor (Kuyruk başlatılıyor)...", "generating", 82)
            else:
                add_log(f"Kuyruk sorgulama hatası (Kodu: {check_res.status_code}). Yeniden deneniyor...", "warning", 83)
                
            time.sleep(3)
            
    except Exception as e:
        add_log(f"Hata meydana geldi: {str(e)}", "error", 90)
        if job_id in ACTIVE_JOBS:
            ACTIVE_JOBS[job_id]['status'] = 'failed'
            ACTIVE_JOBS[job_id]['error'] = str(e)

# STREAM EVENT STREAM (SSE)
@app.route('/api/generate/stream/<job_id>')
def stream_job(job_id):
    if not is_logged_in():
        return Response("data: {\"type\": \"error\", \"message\": \"Unauthorized\"}\n\n", mimetype='text/event-stream')
    
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        return Response(f"data: {json.dumps({'type': 'error', 'message': 'İşlem bulunamadı'})}\n\n", mimetype='text/event-stream')
    
    def generate():
        last_sent_idx = 0
        while True:
            current_job = ACTIVE_JOBS.get(job_id)
            if not current_job:
                yield f"data: {json.dumps({'type': 'failed', 'error': 'İşlem iptal edildi.'})}\n\n"
                break
                
            logs = current_job.get('logs', [])
            while last_sent_idx < len(logs):
                log_entry = logs[last_sent_idx]
                yield f"data: {json.dumps({'type': 'log', 'message': log_entry['message'], 'status': log_entry['status'], 'pct': log_entry['pct']})}\n\n"
                last_sent_idx += 1
                
            if current_job['status'] == 'completed':
                yield f"data: {json.dumps({'type': 'completed', 'outputs': current_job['outputs'], 'meme_id': current_job.get('meme_id'), 'user_id': current_job.get('user_id'), 'id_token': current_job.get('id_token')})}\n\n"
                break
            elif current_job['status'] == 'failed':
                yield f"data: {json.dumps({'type': 'failed', 'error': current_job['error']})}\n\n"
                break
                
            time.sleep(1)
            
    return Response(generate(), mimetype='text/event-stream', headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})

# POLLING PROGRESS ENDPOINT (HTTP Request-based, works seamlessly even when tab is closed/reloaded)
@app.route('/api/generate/poll/<job_id>')
def poll_job(job_id):
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        # Check history if already completed and archived
        for h in GENERATION_HISTORY:
            if h.get('task_id') == job_id or h.get('id') == job_id or h.get('job_id') == job_id:
                return jsonify({
                    'job_id': job_id,
                    'status': 'completed',
                    'pct': 100,
                    'new_logs': [],
                    'last_idx': 0,
                    'outputs': [h.get('url')],
                    'meme_id': h.get('meme_id'),
                    'user_id': h.get('user_id'),
                    'id_token': h.get('id_token'),
                    'error': None
                })
        return jsonify({'status': 'not_found', 'error': 'İşlem bulunamadı'}), 404
    
    try:
        last_idx = int(request.args.get('last_idx', 0))
    except (ValueError, TypeError):
        last_idx = 0
        
    all_logs = job.get('logs', [])
    new_logs = all_logs[last_idx:] if last_idx < len(all_logs) else []
    
    return jsonify({
        'job_id': job_id,
        'status': job.get('status', 'running'),
        'pct': job.get('pct', 0),
        'new_logs': new_logs,
        'last_idx': len(all_logs),
        'outputs': job.get('outputs', []),
        'meme_id': job.get('meme_id'),
        'user_id': job.get('user_id'),
        'id_token': job.get('id_token'),
        'error': job.get('error')
    })

@app.route('/api/generate/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    if job_id in ACTIVE_JOBS:
        ACTIVE_JOBS.pop(job_id, None)
        return jsonify({'success': True})
    return jsonify({'error': 'İşlem bulunamadı'}), 404

@app.route('/api/generate/active')
def get_active_jobs():
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    active_list = {}
    for jid, job in ACTIVE_JOBS.items():
        active_list[jid] = {
            'prompt': job['prompt'],
            'model': job['model'],
            'aspect_ratio': job['aspect_ratio'],
            'tier': job['tier'],
            'resolution': job.get('resolution', ''),
            'num_images': job['num_images'],
            'status': job['status'],
            'pct': job['pct'],
            'logs': job['logs'],
            'outputs': job.get('outputs', []),
            'meme_id': job.get('meme_id'),
            'user_id': job.get('user_id'),
            'id_token': job.get('id_token'),
            'is_extend': job.get('is_extend', False),
            'created_at': job.get('created_at', 0),
            'error': job.get('error')
        }
    return jsonify(active_list)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    if deApiAI and hasattr(deApiAI, "warmup_cf_session"):
        print("[*] [Boot] deAPI Cloudflare Turnstile ön ısıtması yapılıyor, lütfen bekleyin...", flush=True)
        try:
            deApiAI.warmup_cf_session()
        except Exception as w_err:
            print(f"[!] [Boot] Warmup hatası: {w_err}", flush=True)
        print("[+] [Boot] Turnstile hazırlandı, tarayıcı kapandı. Web sunucusu başlatılıyor...", flush=True)

    print(f"[*] Studio Web Server başlatıldı: http://0.0.0.0:{port}", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
