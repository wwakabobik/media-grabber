from i18n import get_language, set_language, tr


def test_default_language_is_english():
    set_language("en")
    assert get_language() == "en"
    assert tr("button.download") == "Download"


def test_set_language_switches_translation():
    set_language("ru")
    try:
        assert get_language() == "ru"
        assert tr("button.download") == "Скачать"
    finally:
        set_language("en")


def test_set_language_rejects_unknown_falls_back_to_english():
    set_language("fr")
    try:
        assert get_language() == "en"
    finally:
        set_language("en")


def test_tr_unknown_key_returns_the_key_itself():
    assert tr("no.such.key") == "no.such.key"


def test_tr_formats_placeholders():
    set_language("en")
    assert tr("status.error_prefix", msg="boom") == "Error: boom"
