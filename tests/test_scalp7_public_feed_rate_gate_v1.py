"""Pure fake-clock regression for BingX 100410 proactive source pacing."""
from __future__ import annotations
import pytest
from ops.scalp7_orderless_shadow_v1 import PublicFeed

class Clock:
    def __init__(self):
        self.value = 100.0
        self.sleeps = []
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds

def test_first_request_not_delayed(monkeypatch):
    clock = Clock()
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.monotonic", clock.now)
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.sleep", clock.sleep)
    x = PublicFeed()
    x._pace_public_request()
    assert clock.sleeps == []
    assert x._last_public_request_monotonic == 100.0

def test_back_to_back_requests_paced_at_1_25_seconds(monkeypatch):
    clock = Clock()
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.monotonic", clock.now)
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.sleep", clock.sleep)
    x = PublicFeed()
    x._pace_public_request()
    x._pace_public_request()
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(1.25)
    assert x._last_public_request_monotonic == pytest.approx(101.25)

def test_elapsed_cooldown_does_not_introduce_sleep(monkeypatch):
    clock = Clock()
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.monotonic", clock.now)
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.sleep", clock.sleep)
    x = PublicFeed()
    x._pace_public_request()
    clock.value += 2.0
    x._pace_public_request()
    assert clock.sleeps == []
    assert x._last_public_request_monotonic == 102.0


def test_actual_public_get_path_invokes_pacing(monkeypatch):
    clock=Clock()
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.monotonic",clock.now)
    monkeypatch.setattr("ops.scalp7_orderless_shadow_v1.time.sleep",clock.sleep)
    class Resp:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self):return b'{"code":0,"data":[]}'
    class FakeOpener:
        def __init__(self):self.requests=[]
        def open(self,request,timeout):self.requests.append(request);return Resp()
    feed=PublicFeed()
    opener=FakeOpener()
    feed.opener=opener
    url="https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol=BTC-USDT&interval=1m&timestamp=1234"
    assert feed(url)==(200,b'{"code":0,"data":[]}')
    assert feed(url)==(200,b'{"code":0,"data":[]}')
    assert len(opener.requests)==2
    assert clock.sleeps==[pytest.approx(1.25)]
    assert len(feed.receipts)==2
