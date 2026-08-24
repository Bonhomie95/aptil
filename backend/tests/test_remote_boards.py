"""Parsing + ATS routing for the free remote-board connectors.

Each connector's HTTP layer is mocked, so these are offline and deterministic.
They pin the field mapping (a provider renaming a field would silently empty the
feed) and the host->ats routing that decides auto-apply vs park.
"""

from __future__ import annotations

import types


def _mock_json(conn, payload):
    conn._fetch_json = types.MethodType(lambda self, *a, **k: payload, conn)


def test_remoteok_parses_and_routes():
    from app.services.connectors.remoteok import RemoteOKConnector

    conn = RemoteOKConnector()
    _mock_json(conn, [
        {"legal": "notice"},  # leading element, must be skipped
        {"id": 1, "position": "Site Reliability Engineer", "company": "Acme",
         "url": "https://boards.greenhouse.io/acme/jobs/1", "location": "Remote"},
    ])
    posts = conn.fetch({})
    assert len(posts) == 1
    assert posts[0]["title"] == "Site Reliability Engineer"
    assert posts[0]["ats_type"] == "greenhouse"
    assert posts[0]["remote"] is True


def test_remotive_parses():
    from app.services.connectors.remotive import RemotiveConnector

    conn = RemotiveConnector()
    _mock_json(conn, {"jobs": [
        {"id": 5, "title": "Platform Engineer", "company_name": "Globex",
         "url": "https://jobs.lever.co/globex/5",
         "candidate_required_location": "USA"},
    ]})
    posts = conn.fetch({"what": "Platform Engineer"})
    assert posts[0]["ats_type"] == "lever"
    assert posts[0]["company"] == "Globex"


def test_himalayas_parses():
    from app.services.connectors.himalayas import HimalayasConnector

    conn = HimalayasConnector()
    _mock_json(conn, {"jobs": [
        {"guid": "g1", "title": "Cloud Engineer", "companyName": "Initech",
         "applicationLink": "https://careers.initech.com/1",
         "locationRestrictions": ["USA", "Canada"]},
    ]})
    posts = conn.fetch({"what": "Cloud Engineer"})
    assert posts[0]["title"] == "Cloud Engineer"
    assert posts[0]["ats_type"] is None          # company site -> parks
    assert "USA" in posts[0]["location"]


def test_arbeitnow_parses():
    from app.services.connectors.arbeitnow import ArbeitnowConnector

    conn = ArbeitnowConnector()
    _mock_json(conn, {"data": [
        {"slug": "s1", "title": "Backend Engineer", "company_name": "ACME GmbH",
         "url": "https://www.arbeitnow.com/jobs/s1", "remote": True,
         "location": "Berlin"},
    ]})
    posts = conn.fetch({})
    assert posts[0]["company"] == "ACME GmbH"
    assert posts[0]["remote"] is True


def test_weworkremotely_parses_rss():
    from app.services.connectors.weworkremotely import WeWorkRemotelyConnector

    rss = """<?xml version="1.0"?><rss><channel>
      <item>
        <title>Acme: Senior Platform Engineer</title>
        <link>https://weworkremotely.com/remote-jobs/acme-spe</link>
        <description>&lt;p&gt;Great role&lt;/p&gt;</description>
        <pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate>
      </item></channel></rss>"""

    class _Resp:
        text = rss

    conn = WeWorkRemotelyConnector()
    conn._get = types.MethodType(lambda self, *a, **k: _Resp(), conn)
    posts = conn.fetch({})
    assert posts[0]["company"] == "Acme"
    assert posts[0]["title"] == "Senior Platform Engineer"
    assert posts[0]["remote"] is True


def test_browser_fallback_is_used_when_direct_fetch_fails(monkeypatch):
    """If httpx returns nothing, _fetch_json must try the browser path — and
    still return None gracefully if that also cannot run."""
    from app.services.connectors.remoteok import RemoteOKConnector

    conn = RemoteOKConnector()
    conn._get = types.MethodType(lambda self, *a, **k: None, conn)  # httpx blocked
    called = {}

    def _fallback(self, *a, **k):
        called["hit"] = True
        return None  # browser also yields nothing -> graceful empty

    conn._browser_fetch_text = types.MethodType(_fallback, conn)
    assert conn.fetch({}) == []          # no crash
    assert called.get("hit") is True     # browser fallback was attempted
