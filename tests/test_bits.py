"""Uji konversi permission bit.

Tidak butuh token atau jaringan — murni logika murni.
"""

import pytest

from bss import bits


def test_basic_bits_have_expected_values():
    """Nilai ini dipakai langsung di server produksi."""
    assert bits.VIEW_CHANNEL == 1024
    assert bits.SEND_MESSAGES == 2048
    assert bits.READ_MESSAGE_HISTORY == 65536
    assert bits.CONNECT == 1048576
    assert bits.SPEAK == 2097152
    assert bits.ADMINISTRATOR == 8


def test_high_bits_use_64_bit_ints():
    """Bit di atas 2^31 tidak muat di signed int32."""
    assert bits.MODERATE_MEMBERS == 1 << 40
    assert bits.SET_VOICE_CHANNEL_STATUS == 1 << 48
    assert bits.MODERATE_MEMBERS > 2 ** 31


def test_combinations_match_production_values():
    """Angka gabungan ini sudah terbukti bekerja di server sungguhan."""
    assert bits.READ_ONLY_DENY == 55296
    assert bits.HIDDEN_DENY == 68608
    assert bits.MUTED_TEXT_DENY == 6208
    assert bits.MUTED_VOICE_DENY == 3145728
    assert bits.MEMBER_TEXT_ALLOW == 117824
    assert bits.MEMBER_VOICE_ALLOW == 3146752
    assert bits.STAFF_ALLOW == 117760


def test_combinations_are_true_or_of_parts():
    assert bits.READ_ONLY_DENY == (
        bits.SEND_MESSAGES | bits.SEND_TTS_MESSAGES
        | bits.EMBED_LINKS | bits.ATTACH_FILES
    )
    assert bits.MEMBER_TEXT_ALLOW == (
        bits.VIEW_CHANNEL | bits.SEND_MESSAGES | bits.EMBED_LINKS
        | bits.ATTACH_FILES | bits.READ_MESSAGE_HISTORY | bits.ADD_REACTIONS
    )


def test_resolve_single_name():
    assert bits.resolve("SEND_MESSAGES") == 2048


def test_resolve_list():
    assert bits.resolve(["VIEW_CHANNEL", "SEND_MESSAGES"]) == 3072


def test_resolve_combination_name():
    assert bits.resolve("MEMBER_TEXT_ALLOW") == 117824


def test_resolve_raw_int():
    assert bits.resolve(6144) == 6144


def test_resolve_numeric_string():
    assert bits.resolve("6144") == 6144


def test_resolve_none_and_empty():
    assert bits.resolve(None) == 0
    assert bits.resolve([]) == 0


def test_resolve_rejects_unknown_name():
    with pytest.raises(ValueError, match="tidak dikenal"):
        bits.resolve("NOT_A_REAL_PERMISSION")


def test_resolve_rejects_bool():
    """True/False tidak boleh disamarkan jadi bit."""
    with pytest.raises(ValueError):
        bits.resolve(True)


def test_names_of_round_trips():
    value = bits.resolve(["VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY"])
    assert set(bits.names_of(value)) == {
        "VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY"
    }


def test_names_of_zero_is_empty():
    assert bits.names_of(0) == []


def test_every_upper_name_is_registered():
    """Setiap konstanta huruf besar yang diekspor harus punya nama bit."""
    for name in ("VIEW_CHANNEL", "ADMINISTRATOR", "USE_EXTERNAL_APPS"):
        assert name in bits.NAMES
