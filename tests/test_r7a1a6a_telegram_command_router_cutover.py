from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
ADAPTER_PATH = HERE / "services" / "telegram" / "zel_q4r3_telegram_pos_adapter_v2.py"
ROUTER_PATH = HERE / "tools" / "r7a1a6a_telegram_command_router_cutover.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module("adapter", ADAPTER_PATH)
ROUTER = load_module("router", ROUTER_PATH)


def sample_inputs():
    status = {
        "lane": "ZEL_FOCUS",
        "mode": "shadow",
        "epoch": "Q4R3",
        "candidate": 0,
        "admitted": 0,
        "open": 0,
        "closed": 0,
        "pnl_r": 0,
        "shadow_open": 0,
        "paper_open": 0,
        "live_open": 0,
        "state": "HOLD_ZERO_EPOCH_PENDING",
        "action": "hold",
        "order_authority": "blocked",
        "execution_authority": "none",
    }
    ledger = {"closed": 0, "pnl_r": 0, "last_close": "none", "rows": []}
    trace = {"rows": [], "last12_r": 0, "wr_pct": 0, "ev_r": 0}
    view = {
        "safety": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
        },
        "writers7": {"configured_writer_count": 7, "active_writer_count": 0},
        "closed": 0,
        "pnl_r": 0,
    }
    return status, ledger, trace, view


def test_renderers_are_distinct(monkeypatch):
    monkeypatch.setattr(ADAPTER, "canonical_inputs", sample_inputs)
    outputs = {command: ADAPTER.render_command(command) for command in ADAPTER.SUPPORTED_COMMANDS}
    assert outputs["/pos"][0] == "POS"
    assert outputs["/pnl"][0] == "PNL"
    assert outputs["/view"][0] == "VIEW"
    assert outputs["/pos"][1].splitlines()[0] == "ZEL POS"
    assert outputs["/pnl"][1].splitlines()[0] == "ZEL PNL"
    assert outputs["/view"][1].splitlines()[0] == "ZEL VIEW"
    assert len({text for _, text in outputs.values()}) == 3


def test_normalize_command_supports_bot_suffix():
    assert ADAPTER.normalize_command("/view@z_os_zel_bot") == "/view"
    assert ADAPTER.normalize_command("/pnl extra") == "/pnl"


def test_main_uses_long_poll_timeout_and_records_command(monkeypatch):
    monkeypatch.setenv("ZEL_TELEGRAM_BOT_TOKEN", "12345678:abcdefghijklmnopqrstuvwxyzABCDE")
    monkeypatch.setenv("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "42")
    calls = []
    writes = []

    def fake_api(token, method, params=None, request_timeout=15):
        calls.append((method, params or {}, request_timeout))
        if method == "getUpdates":
            return {
                "ok": True,
                "result": [{
                    "update_id": 7,
                    "message": {"text": "/pnl", "chat": {"id": 42}},
                }],
            }
        return {"ok": True}

    monkeypatch.setattr(ADAPTER, "api", fake_api)
    monkeypatch.setattr(ADAPTER, "load", lambda path: {})
    monkeypatch.setattr(ADAPTER, "canonical_inputs", sample_inputs)
    monkeypatch.setattr(ADAPTER, "awrite", lambda path, payload: writes.append((path, payload)))
    ADAPTER.main()

    get_updates = next(call for call in calls if call[0] == "getUpdates")
    assert get_updates[1]["timeout"] == 25
    assert get_updates[2] == 35
    send = next(call for call in calls if call[0] == "sendMessage")
    assert send[1]["text"].startswith("ZEL PNL\n")
    report = writes[-1][1]
    assert report["last_command"] == "/pnl"
    assert report["last_response_kind"] == "PNL"
    assert report["last_response_title"] == "ZEL PNL"


class FakeParity:
    @staticmethod
    def writer_counts(payload):
        writers = payload["writers7"]
        return writers["configured_writer_count"], writers["active_writer_count"]


def test_critical_view_parity_ignores_volatile_metadata():
    _, _, _, left = sample_inputs()
    right = dict(left)
    left["updated_at"] = "a"
    right["updated_at"] = "b"
    assert ROUTER.critical_views_equal(left, right, FakeParity) is True


def test_critical_view_parity_detects_safety_mismatch():
    _, _, _, left = sample_inputs()
    _, _, _, right = sample_inputs()
    right["safety"] = dict(right["safety"])
    right["safety"]["execution_authority"] = "paper"
    assert ROUTER.critical_views_equal(left, right, FakeParity) is False
