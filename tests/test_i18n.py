from dotde.i18n import current_language, label, t


def test_italian(monkeypatch):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert current_language() == "it"
    assert t("test.greeting", name="Ada") == "Ciao Ada"


def test_unsupported_or_missing_falls_back_to_english(monkeypatch):
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert t("test.greeting", name="Ada") == "Hello Ada"
    monkeypatch.delenv("LANG")
    assert current_language() == "en"


def test_missing_italian_key_falls_back_to_english():
    assert t("test.only_en", lang="it") == "Only English"


def test_unknown_key_returns_key():
    assert t("does.not.exist", lang="it") == "does.not.exist"


def test_lc_all_wins(monkeypatch):
    monkeypatch.setenv("LC_ALL", "it_IT.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert current_language() == "it"


def test_label():
    assert label({"en": "Appearance", "it": "Aspetto"}, "it") == "Aspetto"
    assert label({"en": "Appearance"}, "it") == "Appearance"
