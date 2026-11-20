import math

from clipforge.config import Settings, load_env_file
from clipforge.utils import fmt_time, safe_float


def test_fmt_time():
    assert fmt_time(0) == "00:00"
    assert fmt_time(65.9) == "01:05"
    assert fmt_time(3725) == "01:02:05"
    assert fmt_time(-5) == "00:00"


def test_safe_float():
    assert safe_float("3.5") == 3.5
    assert safe_float(None) is None
    assert safe_float("abc") is None
    assert safe_float(math.nan) is None
    assert safe_float(math.inf) is None


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("CLIPFORGE_OLLAMA_URL", "http://example:1234/")
    monkeypatch.setenv("CLIPFORGE_OLLAMA_TIMEOUT", "not-a-number")
    monkeypatch.setenv("CLIPFORGE_LOG_LEVEL", "debug")
    s = Settings.from_env()
    assert s.ollama_url == "http://example:1234"   # trailing slash stripped
    assert s.ollama_timeout == 600                 # invalid value -> default
    assert s.log_level == "DEBUG"


def test_load_env_file_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nCF_TEST_A="quoted value"\nCF_TEST_B=from_file\n\nbad line\n',
        encoding="utf-8-sig",
    )
    monkeypatch.delenv("CF_TEST_A", raising=False)
    monkeypatch.setenv("CF_TEST_B", "from_env")
    load_env_file(env)
    import os
    assert os.environ["CF_TEST_A"] == "quoted value"
    assert os.environ["CF_TEST_B"] == "from_env"
    monkeypatch.delenv("CF_TEST_A", raising=False)


def test_load_env_file_missing_is_fine(tmp_path):
    load_env_file(tmp_path / "nope.env")
