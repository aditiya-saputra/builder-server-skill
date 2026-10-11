"""Pengukuran request — dipakai untuk membandingkan strategi eksekusi.

Tujuannya menjawab satu pertanyaan: **sebenarnya berapa request yang
dibutuhkan, dan berapa yang gagal?**

Tanpa pengukuran begini, klaim "cara ini lebih hemat" tidak bisa diverifikasi.
Adapter Python bisa menghitung otomatis karena ia klien HTTP-nya sendiri.
Approach curl tidak bisa — di sana yang menghitung adalah agent, dan hitungannya
ada di kepala, bukan di kode.

Karena itu metrik ini sengaja ditaruh di lapisan paling bawah (client.request),
supaya setiap request yang benar-benar meninggalkan proses tercatat — termasuk
yang di-retry.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Metrics:
    """Catatan semua request yang dikirim satu client."""

    requests: int = 0              # request yang benar-benar dikirim ke API
    retries: int = 0               # percobaan ulang (429 / 5xx / koneksi putus)
    rate_limit_hits: int = 0       # berapa kali kena 429
    timeouts: int = 0              # berapa kali timeout / koneksi gagal
    failures: int = 0              # respons 4xx akhir yang tidak di-retry lagi

    by_method: Counter = field(default_factory=Counter)
    by_status: Counter = field(default_factory=Counter)
    by_route: Counter = field(default_factory=Counter)   # method+path tanpa id

    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def start(self) -> None:
        self.started_at = time.monotonic()

    def stop(self) -> None:
        self.finished_at = time.monotonic()

    @property
    def duration(self) -> float:
        """Durasi dalam detik. Belum di-stop → pakai waktu berjalan."""
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return end - self.started_at

    def record(self, method: str, route: str, status: int,
               *, error: Optional[str] = None) -> None:
        """Catat satu request keluar.

        Args:
            method: HTTP method.
            route:  path yang SUDAH dinormalisasi (id diganti) — untuk
                    menghitung per-route tanpa membuat entri unik tiap channel.
            status: kode status; 0 berarti tidak sampai (timeout/koneksi).
            error:  keterangan tambahan bila status 0.
        """
        self.requests += 1
        self.by_method[method] += 1
        self.by_route[f"{method} {route}"] += 1

        if status == 0:
            self.timeouts += 1
            self.by_status["<no-response>"] += 1
            return

        self.by_status[str(status)] += 1
        if status == 429:
            # 429 BUKAN kegagalan — itu rate limit yang sudah ditangani retry.
            # Menghitungnya dua kali akan membuat strategi yang lebih agresif
            # terlihat lebih buruk dari kenyataan.
            self.rate_limit_hits += 1
        elif status >= 400:
            self.failures += 1

    def note_retry(self) -> None:
        self.retries += 1

    def reset(self) -> None:
        """Kosongkan semua hitungan. Dipakai antar-runs benchmark."""
        self.__dict__.update(Metrics().__dict__)

    def snapshot(self) -> Dict:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "rate_limit_hits": self.rate_limit_hits,
            "timeouts": self.timeouts,
            "failures": self.failures,
            "duration_s": round(self.duration, 2),
            "by_status": dict(self.by_status),
            "top_routes": dict(self.by_route.most_common(8)),
        }


def normalize_route(method: str, url: str) -> str:
    """Ganti snowflake di path jadi placeholder.

    Tanpa ini, `/channels/1234` dan `/channels/5678` dihitung sebagai dua route
    berbeda, sehingga laporan per-route tidak terbaca. Dengan normalisasi,
    semua panggilan channel menyatu jadi satu entri yang berguna.
    """
    parts = url.split("?")[0].split("/")
    out = []
    for segment in parts:
        if segment.isdigit() and len(segment) >= 17:
            out.append("{id}")
        else:
            out.append(segment)
    return "/".join(out)
