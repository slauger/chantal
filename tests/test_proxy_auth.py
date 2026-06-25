"""Tests for proxy credential handling in the download manager.

Proxy credentials must go into the proxy URL (sent to the proxy as
Proxy-Authorization), never onto ``session.auth`` (which would be sent to the
destination host, leaking the proxy credentials upstream, and would be
overwritten by repository basic auth).
"""

from __future__ import annotations

from chantal.core.config import AuthConfig, ProxyConfig, RepositoryConfig
from chantal.core.downloader import DownloadManager, _proxy_url_with_auth


def test_proxy_url_with_auth_embeds_credentials():
    assert (
        _proxy_url_with_auth("http://proxy.example.com:8080", "user", "pass")
        == "http://user:pass@proxy.example.com:8080"
    )
    # No credentials -> unchanged.
    assert _proxy_url_with_auth("http://proxy:8080", None, None) == "http://proxy:8080"
    # Already-credentialed URL -> unchanged.
    assert _proxy_url_with_auth("http://a:b@proxy:8080", "user", "pass") == "http://a:b@proxy:8080"
    # Special characters are percent-encoded.
    assert (
        _proxy_url_with_auth("http://proxy:8080", "u@ser", "p:ss/word")
        == "http://u%40ser:p%3Ass%2Fword@proxy:8080"
    )


def _manager(proxy: ProxyConfig, auth: AuthConfig | None = None) -> DownloadManager:
    config = RepositoryConfig(
        id="r", name="R", type="rpm", feed="http://upstream.example.com/repo", auth=auth
    )
    return DownloadManager(config=config, proxy_config=proxy)


def test_proxy_credentials_go_into_proxy_url_not_session_auth():
    proxy = ProxyConfig(
        http_proxy="http://proxy:8080",
        https_proxy="http://proxy:8080",
        username="puser",
        password="ppass",
    )
    mgr = _manager(proxy)
    session = mgr.session

    # Credentials are carried by the proxy URLs (-> Proxy-Authorization).
    assert session.proxies["http"] == "http://puser:ppass@proxy:8080"
    assert session.proxies["https"] == "http://puser:ppass@proxy:8080"
    # NOT on session.auth (which would leak to the destination host).
    assert session.auth is None


def test_repo_basic_auth_coexists_with_proxy_auth():
    proxy = ProxyConfig(http_proxy="http://proxy:8080", username="puser", password="ppass")
    auth = AuthConfig(type="basic", username="repouser", password="repopass")
    mgr = _manager(proxy, auth)
    session = mgr.session

    # Proxy creds in the proxy URL; repository creds on session.auth — no clash.
    assert session.proxies["http"] == "http://puser:ppass@proxy:8080"
    assert session.auth == ("repouser", "repopass")


def test_proxy_without_credentials_is_unchanged():
    proxy = ProxyConfig(http_proxy="http://proxy:8080")
    mgr = _manager(proxy)
    assert mgr.session.proxies["http"] == "http://proxy:8080"
    assert mgr.session.auth is None
