import asyncio

from emailcheck import check_email, normalize, spell


def test_normalize_spoken_tokens():
    assert normalize("jane dot doe at acme dot com")[0] == "jane.doe@acme.com"
    assert normalize("s underscore k at gmail dot com")[0] == "s_k@gmail.com"
    assert normalize("Jane.Doe@Acme.com")[0] == "jane.doe@acme.com"
    assert normalize("bob at example dot co")[0] == "bob@example.co"


def test_spell_reads_each_symbol():
    assert spell("a.b@x.com") == "A dot B at X dot com".replace("com", "C O M")


def test_common_domain_is_valid_without_dns():
    r = asyncio.run(check_email("suhaas at gmail dot com"))
    assert r.email == "suhaas@gmail.com"
    assert r.status in {"valid", "needs_confirmation"}
    assert r.spelled.startswith("S U H A A S at")


def test_invalid_syntax():
    r = asyncio.run(check_email("not an email"))
    assert r.status == "invalid"
