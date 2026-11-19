import pytest

from opengwaspy.auth import AuthProvider, DeveloperKey, NoAuth, OpenGWASToken


@pytest.mark.parametrize("cls", [DeveloperKey, OpenGWASToken])
def test_bearer_headers_and_hidden_token(cls: type[DeveloperKey]) -> None:
    provider = cls("  s3cret-token ")
    assert provider.headers() == {"Authorization": "Bearer s3cret-token"}
    assert provider.refresh() is False
    assert "s3cret" not in repr(provider)
    assert "s3cret" not in str(provider)
    assert isinstance(provider, AuthProvider)


@pytest.mark.parametrize("bad", ["", "   ", "two words", "tab\there"])
def test_bearer_rejects_bad_tokens(bad: str) -> None:
    with pytest.raises(ValueError):
        DeveloperKey(bad)


def test_equality_depends_on_kind_and_token() -> None:
    assert DeveloperKey("a") == DeveloperKey("a")
    assert DeveloperKey("a") != DeveloperKey("b")
    assert DeveloperKey("a") != OpenGWASToken("a")
    assert len({DeveloperKey("a"), DeveloperKey("a"), OpenGWASToken("a")}) == 2


def test_no_auth() -> None:
    assert NoAuth().headers() == {}
    assert NoAuth().refresh() is False
    assert NoAuth() == NoAuth()
    assert hash(NoAuth()) == hash(NoAuth())
    assert repr(NoAuth()) == "NoAuth()"
    assert isinstance(NoAuth(), AuthProvider)
