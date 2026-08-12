from __future__ import annotations

from pathlib import Path

TARGET = Path("backend/production/zel_production_ai_proposal_layer_v1.py")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    import_old = (
        "from backend.production.zel_production_improvement_controller_v1 "
        "import atomic_json_write, read_json, stable_sha\n"
    )
    import_new = import_old + (
        "from backend.production.zel_production_openai_critic_v1 "
        "import review_or_hold, validate_critic_config\n"
    )
    if import_new not in text:
        if text.count(import_old) != 1:
            raise SystemExit("OPENAI_PATCH_IMPORT_ANCHOR_MISMATCH")
        text = text.replace(import_old, import_new, 1)

    start_marker = (
        '    api_key = os.environ.get("GEMINI_API_KEY", "").strip()\n\n'
        '    def caller(prompt: str) -> tuple[str, Mapping[str, Any]]:\n'
    )
    end_marker = "    result, should_write = proposal_tick(\n"

    if "critic_trace: dict[str, Any] = {}" not in text:
        start = text.find(start_marker)
        end = text.find(end_marker, start + 1)
        if start < 0 or end < 0:
            raise SystemExit("OPENAI_PATCH_MAIN_ANCHOR_MISMATCH")
        replacement = '''    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    critic_cfg = validate_critic_config(cfg.get("openai_critic"))
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    openai_model = os.environ.get(
        str(critic_cfg.get("model_env") or "OPENAI_MODEL"), ""
    ).strip() or str(critic_cfg.get("default_model") or "gpt-5-mini")
    critic_trace: dict[str, Any] = {}

    previous_for_tick = previous
    if critic_cfg.get("enabled") is True and critic_cfg.get("required") is True:
        prior_receipt = previous.get("critic_receipt") if isinstance(previous, Mapping) else None
        prior_ok = (
            isinstance(prior_receipt, Mapping)
            and previous.get("critic_provider") == "OPENAI"
            and str(prior_receipt.get("decision") or "") in {"PASS", "HOLD", "REJECT"}
        )
        if not prior_ok:
            previous_for_tick = None

    def caller(prompt: str) -> tuple[str, Mapping[str, Any]]:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY_MISSING")
        gemini_model, raw = call_gemini(
            api_key,
            [str(v) for v in cfg["models"]],
            prompt,
            int(cfg["max_output_tokens"]),
            float(cfg["temperature"]),
        )
        raw_proposals = raw.get("proposals") if isinstance(raw, Mapping) else None
        if critic_cfg.get("enabled") is True and isinstance(raw_proposals, list) and raw_proposals:
            critic_model, receipt = review_or_hold(
                openai_key,
                openai_model,
                raw,
                timeout_sec=int(critic_cfg["timeout_sec"]),
                max_output_tokens=int(critic_cfg["max_output_tokens"]),
            )
            critic_trace.clear()
            critic_trace.update(
                {
                    "provider": "OPENAI",
                    "model": critic_model,
                    "receipt": receipt,
                    "required": bool(critic_cfg.get("required")),
                }
            )
            if critic_cfg.get("required") is True and receipt.get("decision") != "PASS":
                raw = {
                    "status": "HOLD",
                    "proposals": [],
                    "hold_reason": f"OPENAI_CRITIC_{receipt.get('decision')}",
                }
        return gemini_model, raw

'''
        text = text[:start] + replacement + text[end:]

    old_call = '''        previous=previous,
        ai_caller=caller,
    )
    if result is None:
'''
    new_call = '''        previous=previous_for_tick,
        ai_caller=caller,
    )
    if isinstance(result, dict) and critic_trace:
        result = dict(result)
        receipt = dict(critic_trace["receipt"])
        result["critic_provider"] = "OPENAI"
        result["critic_model"] = critic_trace["model"]
        result["critic_required"] = bool(critic_trace["required"])
        result["critic_receipt"] = receipt
        if result["critic_required"] and receipt.get("decision") != "PASS":
            result["state"] = f"HOLD_AI_PROPOSAL_OPENAI_CRITIC_{receipt.get('decision')}"
            result["proposal_count"] = 0
            result["source_ready_count"] = 0
            result["proposals"] = []
        result["receipt_sha256"] = stable_sha(
            {k: v for k, v in result.items() if k != "receipt_sha256"}
        )
    if result is None:
'''
    if new_call not in text:
        if text.count(old_call) != 1:
            raise SystemExit("OPENAI_PATCH_CALL_ANCHOR_MISMATCH")
        text = text.replace(old_call, new_call, 1)

    TARGET.write_text(text, encoding="utf-8")
    print("PASS_OPENAI_CRITIC_WIRING_HELPER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
