"""Configuration: where the API is, and how to authenticate.

Settings are taken, in order of precedence, from explicit arguments, then the
environment, then the user's config file, then the defaults:

=================  ====================  ==========================
Setting            Environment           Config file key
=================  ====================  ==========================
API URL            ``OPENGWAS_URL``      ``url``
Profile            ``OPENGWAS_PROFILE``  ``profile``
Developer key      ``OPENGWAS_TOKEN``    ``token``
OpenGWAS token     ``OPENGWAS_JWT``      ``jwt``
=================  ====================  ==========================

The config file is TOML, at ``$OPENGWAS_CONFIG`` or else
``<user config dir>/opengwaspy/config.toml``. A project's ``.env`` file is
never read implicitly.
"""

from __future__ import annotations

import os
import stat
import sys
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from opengwaspy.auth import AuthProvider, DeveloperKey, NoAuth, OpenGWASToken

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

__all__ = ["PROFILES", "Config", "ConfigError", "config_path", "save_setting"]

#: Named base URLs, as ieugwaspy's ``select_api`` had.
PROFILES: dict[str, str] = {
    # The OpenGWAS Gateway, which serves the Data API under /ogdb. Not yet the
    # default: the Gateway's user login flow is not final.
    "gateway": "https://api.opengwas.io/ogdb",
    # A Data API on this machine, at its default port.
    "local": "http://localhost:6432",
}

DEFAULT_PROFILE = "local"


class ConfigError(ValueError):
    """The configuration is invalid or ambiguous."""


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    """The user config file's path (it need not exist).

    Args:
        environ: Environment to read; defaults to ``os.environ``.

    Returns:
        ``$OPENGWAS_CONFIG`` if set, else ``config.toml`` in the platform's
        user config directory, under ``opengwaspy``.
    """
    env = os.environ if environ is None else environ
    if env.get("OPENGWAS_CONFIG"):
        return Path(env["OPENGWAS_CONFIG"]).expanduser()
    if sys.platform == "win32":  # pragma: no cover - platform specific
        base = Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":  # pragma: no cover - platform specific
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "opengwaspy" / "config.toml"


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    if (
        os.name == "posix"
        and ("token" in data or "jwt" in data)
        and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)
    ):
        warnings.warn(
            f"{path} holds a credential but is readable by others; run: chmod 600 {path}",
            stacklevel=3,
        )
    return data


def _normalise_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(f"API URL must be an http(s) URL, got {url!r}")
    if parts.query or parts.fragment:
        raise ConfigError(f"API URL must not have a query or fragment: {url!r}")
    return url


@dataclass(frozen=True)
class Config:
    """Where the API is, how to authenticate, and how patient to be.

    Build one with :meth:`Config.load`, which applies the precedence rules, or
    directly for full control.

    Attributes:
        base_url: The API's base URL, without ``/api``. Through the Gateway this
            includes its prefix, for example ``https://api.opengwas.io/ogdb``.
        auth: The authentication provider.
        timeout: Seconds to wait for each HTTP response.
        max_retry_wait: Most seconds to spend waiting on ``Retry-After`` for one call.
        max_attempts: Most attempts for one call after transport errors or 5xx.
        max_in_flight: Most jobs one runner keeps in flight at once.
    """

    base_url: str = PROFILES[DEFAULT_PROFILE]
    auth: AuthProvider = field(default_factory=NoAuth)
    timeout: float = 60.0
    max_retry_wait: float = 600.0
    max_attempts: int = 5
    max_in_flight: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalise_url(self.base_url))
        if self.timeout <= 0 or self.max_retry_wait < 0:
            raise ConfigError("timeout must be positive and max_retry_wait not negative")
        if self.max_attempts < 1 or self.max_in_flight < 1:
            raise ConfigError("max_attempts and max_in_flight must be at least 1")

    @classmethod
    def load(
        cls,
        url: str | None = None,
        *,
        profile: str | None = None,
        token: str | None = None,
        jwt: str | None = None,
        auth: AuthProvider | None = None,
        environ: Mapping[str, str] | None = None,
        config_file: Path | None = None,
        **options: Any,
    ) -> Config:
        """Build a configuration from arguments, the environment and the config file.

        Args:
            url: The API's base URL. Overrides ``profile``.
            profile: A name in :data:`PROFILES`.
            token: A Data API developer key.
            jwt: An OpenGWAS token, for the Gateway.
            auth: An authentication provider. Overrides ``token`` and ``jwt``.
            environ: Environment to read; defaults to ``os.environ``.
            config_file: Config file to read; defaults to :func:`config_path`.
            **options: Other :class:`Config` fields, such as ``timeout``.

        Returns:
            The configuration.

        Raises:
            ConfigError: An unknown profile, a bad URL, or both a developer key
                and an OpenGWAS token at the same level of precedence.
        """
        env = os.environ if environ is None else environ
        path = config_path(env) if config_file is None else config_file
        layers: list[Mapping[str, Any]] = [
            {"url": url, "profile": profile, "token": token, "jwt": jwt},
            {
                "url": env.get("OPENGWAS_URL"),
                "profile": env.get("OPENGWAS_PROFILE"),
                "token": env.get("OPENGWAS_TOKEN"),
                "jwt": env.get("OPENGWAS_JWT"),
            },
            _read_config_file(path),
        ]

        base_url = None
        for layer in layers:
            if layer.get("url"):
                base_url = str(layer["url"])
                break
            if layer.get("profile"):
                name = str(layer["profile"])
                if name not in PROFILES:
                    raise ConfigError(
                        f"unknown profile {name!r}; choose one of {', '.join(PROFILES)}"
                    )
                base_url = PROFILES[name]
                break

        provider = auth
        if provider is None:
            for layer in layers:
                has_token, has_jwt = bool(layer.get("token")), bool(layer.get("jwt"))
                if has_token and has_jwt:
                    raise ConfigError(
                        "both a developer key and an OpenGWAS token are set; set only one"
                    )
                if has_token:
                    provider = DeveloperKey(str(layer["token"]))
                    break
                if has_jwt:
                    provider = OpenGWASToken(str(layer["jwt"]))
                    break

        settings: dict[str, Any] = {k: v for k, v in options.items() if v is not None}
        if base_url is not None:
            settings["base_url"] = base_url
        if provider is not None:
            settings["auth"] = provider
        return cls(**settings)

    def with_options(self, **changes: Any) -> Config:
        """A copy of this configuration with some fields changed."""
        return replace(self, **changes)

    def url(self, path: str) -> str:
        """The absolute URL of an API path.

        ``api/...`` paths are relative to :attr:`base_url`, so they pick up the
        Gateway's prefix. Absolute paths returned by the API (``/ogdb/api/jobs/...``)
        already carry any prefix, so they are resolved against the origin only.

        Args:
            path: ``api/...`` or ``/api/...`` for an API route, or an absolute
                path returned by the API in ``status_url``, ``result_url`` or
                ``Location``, or a full URL.

        Returns:
            The absolute URL.
        """
        if urlsplit(path).scheme:
            return path
        if path.startswith("/") and not path.startswith("/api/"):
            return urljoin(self.base_url + "/", path)
        return f"{self.base_url}/{path.lstrip('/')}"


def save_setting(key: str, value: str, path: Path | None = None) -> Path:
    """Save one setting to the user config file, keeping the others.

    The file is written with mode 0600, because it may hold a credential. Only one
    credential may be set, so saving a ``token`` removes a saved ``jwt``, and the
    other way round.

    Args:
        key: ``url``, ``profile``, ``token`` or ``jwt``.
        value: The value.
        path: The config file; defaults to :func:`config_path`.

    Returns:
        The file written.
    """
    if key not in ("url", "profile", "token", "jwt"):
        raise ConfigError(f"unknown setting {key!r}")
    path = path or config_path()
    data = {k: v for k, v in _read_config_file(path).items() if isinstance(v, str)}
    data[key] = value
    if key in ("token", "jwt"):
        data.pop("jwt" if key == "token" else "token", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{k} = {_toml_string(v)}\n" for k, v in sorted(data.items()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    if os.name == "posix":
        path.chmod(0o600)
    return path


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
