import pytest

from anonymizer.cf import cf_variants, checksum, decode_cf, is_plausible_cf, is_valid_cf


def cf(prefix="VLTLVE80C03L219"):
    return prefix + checksum(prefix)


def test_valid_synthetic_code_and_corrupted_checksum():
    value = cf()
    assert is_valid_cf(value)
    invalid = value[:-1] + ("A" if value[-1] != "A" else "B")
    assert is_plausible_cf(invalid)
    assert not is_valid_cf(invalid)
    assert not decode_cf(invalid).checksum_valid


@pytest.mark.parametrize("letter", list("LMNPRSTV"))
def test_birthplace_initial_is_not_translated_as_omocodia(letter):
    decoded = decode_cf(cf(f"VLTLVE80C03{letter}219"))
    assert decoded.birthplace_code == f"{letter}219"
    assert decoded.century is None
    assert decoded.year_two_digits == 80


def test_omocodia_and_female_day():
    value = cf("VLTLVEULCQPMLMV")
    decoded = decode_cf(value)
    assert is_valid_cf(value)
    assert (decoded.year_two_digits, decoded.month, decoded.day, decoded.sex) == (80, 3, 3, "F")
    assert decoded.birthplace_code == "M019"


@pytest.mark.parametrize("prefix", ["VLTLVE80B30L219", "VLTLVE81B29L219", "VLTLVE80C00L219"])
def test_impossible_date_is_not_valid(prefix):
    assert not is_valid_cf(cf(prefix))
    with pytest.raises(ValueError):
        decode_cf(cf(prefix))


def test_leap_century_remains_ambiguous():
    decoded = decode_cf(cf("VLTLVE00B29L219"))
    assert decoded.day == 29
    assert decoded.century is None


def test_ocr_variants_and_normalization():
    value = cf()
    assert value in cf_variants(value[:6] + "8O" + value[8:])
    assert is_valid_cf(" ".join(value.lower()))
    assert cf_variants("invalid") == ()


@pytest.mark.parametrize("value", ["", "X" * 16, "VLTLVE80C03L21!X", "0" * 16])
def test_malformed_cf(value):
    assert not is_valid_cf(value)
