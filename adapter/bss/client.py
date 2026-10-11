"""REST client Discord — HTTP-only, stateless.

Sengaja TIDAK memakai gateway/WebSocket. Seluruh operasi yang dibutuhkan
skill ini (baca struktur, buat, ubah, hapus) tersedia lewat REST biasa.

Keputusan desain yang penting:
  * Rate limit ditangani otomatis (Discord ~5 req/detik per route).
  * Semua request membawa X-Audit-Log-Reason supaya ada jejak di Audit Log.
  * Discord kadang membalas 200 tapi MENYIMPAN NILAI BERBEDA dari yang kita
    kirim (terbukti pada PATCH rules_channel_id). Karena itu verify tidak boleh
    pernah mempercayai isi response PATCH — selalu GET ulang.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from .metrics import Metrics, normalize_route

API = "https://discord.com/api/v10"
AUDIT_REASON = "builder-server-skill"

#: Jeda antar request. Discord membatasi ~5 req/detik per route.
REQUEST_INTERVAL = 0.3

#: Batas waktu tunggu satu request sebelum dianggap timeout.
REQUEST_TIMEOUT = 30.0

#: Retry maksimum untuk kegagalan yang dianggap sementara
#: (429 rate limit, 5xx server error, timeout, koneksi putus).
MAX_RETRIES = 4

#: Backoff eksponensial dasar, dalam detik. 0.5 → 0.5, 1, 2, 4.
BACKOFF_BASE = 0.5

#: Jangan pernah tidur lebih lama dari ini walau `retry_after` meminta.
#: Mencegah satu header aneh menghentikan seluruh build.
MAX_BACKOFF = 30.0

#: Tipe channel yang valid untuk DIBUAT lewat API.
#:
#: Angka pastinya bergantung pada feature guild. Kalau API menolak, pesan
#: errornya memuat daftar BASE_TYPE_CHOICES yang berlaku — baca pesan itu,
#: jangan menebak. Daftar di bawah adalah yang terverifikasi.
CHANNEL_TYPES = {
    "text": 0,
    "voice": 2,
    "category": 4,
    "announcement": 5,   # butuh feature NEWS
    "stage": 6,
    "forum": 15,
    "media": 16,
}


class DiscordError(RuntimeError):
    """Kegagalan request Discord yang sudah memuat konteks untuk diagnosis."""

    def __init__(self, method: str, url: str, status: int, body: Any):
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} -> {status}: {body}")


class DiscordClient:
    def __init__(self, token: Optional[str] = None, *, session: Optional[requests.Session] = None):
        token = token or os.environ.get("DISCORD_TOKEN")
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN tidak ada. Atur lewat environment variable, "
                "jangan tulis ke berkas konfigurasi."
            )

        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "X-Audit-Log-Reason": AUDIT_REASON,
        })
        self._last_request = 0.0

        #: Metrik request. Di-reset manual lewat `reset_metrics()` antar-run.
        self.metrics = Metrics()

    def reset_metrics(self) -> None:
        """Kosongkan hitungan — dipakai sebelum tiap run benchmark."""
        self.metrics = Metrics()

    # ── lapisan rendah ──────────────────────────────────────────────────────
    def _throttle(self) -> None:
        wait = self._last_request + REQUEST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def request(self, method: str, path: str, **kwargs) -> Any:
        """Kirim satu request, dengan retry terbatas untuk kegagalan sementara.

        Kenapa perlu retry (Prioritas 2 — API Reliability):
          Discord membatasi ~5 req/detik per route. Satu burst bisa memicu 429,
          dan tanpa retry seluruh build gagal di tengah jalan — meninggalkan
          server dalam kondisi setengah jadi.

        Yang di-retry: 429, 5xx, timeout, koneksi putus.
        Yang TIDAK di-retry: 4xx lain (400/401/403/404) — itu bug pada payload
        atau izin, dan mengulanginya hanya memperbesar jejak error di Audit Log.
        """
        url = path if path.startswith("http") else f"{API}{path}"
        route = normalize_route(method, url)
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)

        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                response = self.session.request(method, url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                # Tidak sampai server — catat sebagai no-response, lalu backoff.
                if attempt >= MAX_RETRIES:
                    self.metrics.record(method, route, 0)
                    raise DiscordError(method, url, 0, f"koneksi gagal: {exc}") from exc
                self.metrics.note_retry()
                self._backoff(attempt, None)
                continue

            self.metrics.record(method, route, response.status_code)

            if response.status_code == 429 and attempt < MAX_RETRIES:
                # Discord menyimpan jeda yang benar di sini, bukan di header.
                # Membaca `retry_after` jauh lebih akurat daripada menebak.
                self.metrics.note_retry()
                self._backoff(attempt, self._retry_after(response))
                continue

            if response.status_code >= 500 and attempt < MAX_RETRIES:
                self.metrics.note_retry()
                self._backoff(attempt, None)
                continue

            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text
                raise DiscordError(method, url, response.status_code, body)

            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        raise DiscordError(method, url, 0, "retry habis")

    @staticmethod
    def _retry_after(response: requests.Response) -> Optional[float]:
        """Ambil `retry_after` dari body 429, dengan pengaman nilai aneh."""
        try:
            value = float(response.json().get("retry_after"))
        except (ValueError, AttributeError, TypeError):
            return None
        return value if 0 < value <= MAX_BACKOFF else None

    def _backoff(self, attempt: int, retry_after: Optional[float]) -> None:
        """Tidur sejenak sebelum percobaan berikutnya.

        `retry_after` dari Discord diutamakan kalau tersedia — itu jawaban
        yang benar atas pertanyaan "kapan boleh coba lagi". Kalau tidak ada,
        pakai backoff eksponensial.
        """
        delay = retry_after if retry_after is not None else BACKOFF_BASE * (2 ** attempt)
        time.sleep(min(delay, MAX_BACKOFF))

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, payload: Optional[Dict] = None) -> Any:
        return self.request("POST", path, json=payload or {})

    def patch(self, path: str, payload: Dict) -> Any:
        return self.request("PATCH", path, json=payload)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # ── baca state ──────────────────────────────────────────────────────────
    def guild(self, guild_id: str) -> Dict:
        return self.get(f"/guilds/{guild_id}")

    def channels(self, guild_id: str) -> List[Dict]:
        return self.get(f"/guilds/{guild_id}/channels")

    def roles(self, guild_id: str) -> List[Dict]:
        return self.get(f"/guilds/{guild_id}/roles")

    def me(self) -> Dict:
        return self.get("/users/@me")

    def my_roles(self, guild_id: str) -> List[str]:
        """Role yang dipegang bot di guild ini. Role pertama = role paling atas."""
        bot_id = self.me()["id"]
        member = self.get(f"/guilds/{guild_id}/members/{bot_id}")
        return member.get("roles", [])

    # ── tulis ───────────────────────────────────────────────────────────────
    def create_channel(self, guild_id: str, payload: Dict) -> Dict:
        return self.post(f"/guilds/{guild_id}/channels", payload)

    def update_channel(self, channel_id: str, payload: Dict) -> Dict:
        return self.patch(f"/channels/{channel_id}", payload)

    def delete_channel(self, channel_id: str) -> None:
        self.delete(f"/channels/{channel_id}")

    def create_role(self, guild_id: str, payload: Dict) -> Dict:
        return self.post(f"/guilds/{guild_id}/roles", payload)

    def update_role(self, guild_id: str, role_id: str, payload: Dict) -> Dict:
        return self.patch(f"/guilds/{guild_id}/roles/{role_id}", payload)

    def delete_role(self, guild_id: str, role_id: str) -> None:
        self.delete(f"/guilds/{guild_id}/roles/{role_id}")

    def set_role_positions(self, guild_id: str, placements: List[Dict]) -> Any:
        """Satu PATCH untuk banyak role. Lihat SKILL.md §4.5 — ini wajib,
        karena role baru semuanya lahir di position 1 dan urutannya terbalik."""
        return self.patch(f"/guilds/{guild_id}/roles", placements)

    def update_guild(self, guild_id: str, payload: Dict) -> Dict:
        return self.patch(f"/guilds/{guild_id}", payload)

    def create_invite(self, channel_id: str) -> Dict:
        return self.post(f"/channels/{channel_id}/invites", {"max_age": 0, "max_uses": 0, "unique": True})
