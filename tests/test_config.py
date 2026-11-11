import pytest

from config import Settings, _parse_days


def test_parse_days():
    assert _parse_days("Mon-Fri") == {0, 1, 2, 3, 4}
    assert _parse_days("Mon,Wed,Fri") == {0, 2, 4}
    assert _parse_days("Fri-Mon") == {4, 5, 6, 0}


def test_defaults():
    s = Settings.from_env({})
    assert s.bookable_hours == (10, 18)
    assert s.mode == "live"
    assert str(s.owner_tz) == "America/New_York"


def test_blocklist_normalized():
    s = Settings.from_env({"BLOCKLIST": "+1 (555) 111-2222, 15553334444"})
    assert s.blocklist == {"+15551112222", "+15553334444"}


def test_bad_mode():
    with pytest.raises(ValueError):
        Settings.from_env({"MODE": "pipeline"})
