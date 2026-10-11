"""bss — Discord server structure adapter untuk builder-server-skill.

Dirancang HTTP-only dan stateless: tidak ada gateway, tidak ada proses yang
harus jalan terus. Setiap operasi adalah request REST biasa.

Lapisan yang tersedia:
    config   muat + validasi YAML terhadap schema
    plan     hitung diff rancangan vs keadaan nyata (murni, bisa diuji offline)
    apply    eksekusi diff ke Discord, dengan urutan yang benar
    verify   baca ulang server, bandingkan, laporkan selisih
"""

__version__ = "0.1.0"
