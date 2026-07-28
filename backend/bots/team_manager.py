from __future__ import annotations

from typing import Any, Dict, List, Optional

from .bot_registry import get_bot
from .team_config import TEAM_CONFIGS
from .types import TeamDetail, TeamSnapshot
from .legacy_adapter import adapt_legacy_decision
from .diff_logger import write_shadow_diff


def _to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        try:
            return {k: v for k, v in vars(value).items() if not str(k).startswith("_")}
        except Exception:
            return {}
    return {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _unique_str_list(*parts: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in parts:
        for item in _as_list(part):
            text = str(item).strip()
            if not text or text in seen:
                continue
            out.append(text)
            seen.add(text)
    return out


def _cfg_to_dict(cfg: Any) -> Dict[str, Any]:
    if isinstance(cfg, dict):
        return dict(cfg)
    if hasattr(cfg, "model_dump"):
        try:
            dumped = cfg.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return {}


def _decision_to_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return _to_dict(value)


def _shadow_log(scope: str, bot_name: str, team_cfg: Any, raw_decision: Dict[str, Any], new_decision: Dict[str, Any]) -> None:
    cfg_dict = _cfg_to_dict(team_cfg)
    team_name = str(_get(team_cfg, "name", "unknown") or "unknown")
    legacy = adapt_legacy_decision(bot_name, raw_decision, cfg_dict)
    try:
        write_shadow_diff(team_name=team_name, scope=scope, bot_name=bot_name, legacy_decision=legacy, new_decision=new_decision)
    except Exception:
        return


class TeamManager:
    def __init__(self, mode: str = "paper"):
        self.mode = mode

    def _team_score(self, lead_decision: Dict[str, Any], support_decision: Dict[str, Any], helper_decision: Optional[Dict[str, Any]] = None) -> float:
        lead_fit = float(lead_decision.get("fit", 0.0) or 0.0)
        support_fit = float(support_decision.get("fit", 0.0) or 0.0)
        helper_fit = float((helper_decision or {}).get("fit", 0.0) or 0.0)
        helper_bonus = 0.05 * helper_fit if helper_decision and ((helper_decision.get("meta") or {}).get("helper_trigger")) else 0.0
        return round((lead_fit * 0.70) + (support_fit * 0.25) + helper_bonus, 4)

    def _team_health(self, warnings: List[str]) -> str:
        return "warn" if warnings else "ok"

    def _watcher_consensus(self, decisions: List[Dict[str, Any]]) -> str:
        values = []
        for d in decisions:
            meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
            values.append(str(meta.get("watcher_consensus", "unknown")))
        if values and all(v == "high" for v in values):
            return "high"
        if any(v == "low" for v in values):
            return "low"
        return "medium" if values else "unknown"

    def _runtime_policy(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        policy = cfg.get("team_runtime_policy")
        return dict(policy) if isinstance(policy, dict) else {}

    def _assemble_bot_decision(self, bot_name: str, team_cfg: Dict[str, Any], market_state: Dict[str, Any]) -> Dict[str, Any]:
        policy = self._runtime_policy(team_cfg)
        bot = get_bot(bot_name)
        raw = bot.decide(market_state, team_policy=policy)
        decision = _decision_to_dict(raw)
        _shadow_log(bot_name.lower(), bot_name, team_cfg, decision, decision)
        return decision

    def _snapshot(self, cfg: Dict[str, Any], lead_decision: Dict[str, Any], support_decision: Dict[str, Any], helper_decision: Optional[Dict[str, Any]], selected: bool = False, next_candidate: Optional[str] = None) -> TeamSnapshot:
        warnings = _unique_str_list(
            lead_decision.get("warnings"),
            support_decision.get("warnings"),
            helper_decision.get("warnings") if helper_decision else [],
        )
        why = _unique_str_list(
            (lead_decision.get("why", []) or [])[:3],
            (support_decision.get("why", []) or [])[:2],
            (helper_decision.get("why", []) or [])[:1] if helper_decision else [],
        )
        helper_trigger = bool(((lead_decision.get("meta") or {}).get("helper_trigger")) or ((support_decision.get("meta") or {}).get("helper_trigger")))
        return TeamSnapshot(
            name=str(cfg.get("name")),
            selected=selected,
            score=self._team_score(lead_decision, support_decision, helper_decision),
            health=self._team_health(warnings),
            mode=self.mode,
            lead=str(cfg.get("lead")),
            support=str(cfg.get("support")),
            conditional_helper=str(cfg.get("conditional_helper") or "") or None,
            watchers=list(cfg.get("watchers", []) or []),
            why=why,
            warnings=warnings,
            next_candidate=next_candidate,
            watcher_consensus=self._watcher_consensus([lead_decision, support_decision] + ([helper_decision] if helper_decision else [])),
            helper_trigger=helper_trigger,
            decision_id=str(lead_decision.get("decision_id") or support_decision.get("decision_id") or ""),
            stale_ms=int(lead_decision.get("stale_ms") or support_decision.get("stale_ms") or 0),
            source_ts=int(lead_decision.get("source_ts") or support_decision.get("source_ts") or 0),
            reconcile_status=str(lead_decision.get("reconcile_status") or support_decision.get("reconcile_status") or "ok"),
            source=str(lead_decision.get("source") or support_decision.get("source") or ""),
        )

    def list_teams(self, market_state: Dict[str, Any]) -> List[TeamSnapshot]:
        rows = []
        for name, cfg in TEAM_CONFIGS.items():
            lead_decision = self._assemble_bot_decision(str(cfg.get("lead")), cfg, market_state)
            support_decision = self._assemble_bot_decision(str(cfg.get("support")), cfg, market_state)
            helper_name = cfg.get("conditional_helper")
            helper_decision: Optional[Dict[str, Any]] = None
            if helper_name:
                lead_meta = lead_decision.get("meta") if isinstance(lead_decision.get("meta"), dict) else {}
                support_meta = support_decision.get("meta") if isinstance(support_decision.get("meta"), dict) else {}
                if bool(lead_meta.get("helper_trigger")) or bool(support_meta.get("helper_trigger")):
                    helper_decision = self._assemble_bot_decision(str(helper_name), cfg, market_state)
            rows.append({
                "name": name,
                "cfg": cfg,
                "lead_decision": lead_decision,
                "support_decision": support_decision,
                "helper_decision": helper_decision,
                "score": self._team_score(lead_decision, support_decision, helper_decision),
            })
        rows.sort(key=lambda x: x["score"], reverse=True)

        out: List[TeamSnapshot] = []
        for idx, row in enumerate(rows):
            out.append(
                self._snapshot(
                    row["cfg"],
                    row["lead_decision"],
                    row["support_decision"],
                    row["helper_decision"],
                    selected=(idx == 0),
                    next_candidate=rows[idx + 1]["name"] if idx == 0 and len(rows) > 1 else None,
                )
            )
        return out

    def get_team_detail(self, team_name: str, market_state: Dict[str, Any]) -> TeamDetail:
        cfg = TEAM_CONFIGS[team_name]
        lead_decision = self._assemble_bot_decision(str(cfg.get("lead")), cfg, market_state)
        support_decision = self._assemble_bot_decision(str(cfg.get("support")), cfg, market_state)
        helper_name = cfg.get("conditional_helper")
        helper_decision: Optional[Dict[str, Any]] = None
        if helper_name:
            lead_meta = lead_decision.get("meta") if isinstance(lead_decision.get("meta"), dict) else {}
            support_meta = support_decision.get("meta") if isinstance(support_decision.get("meta"), dict) else {}
            if bool(lead_meta.get("helper_trigger")) or bool(support_meta.get("helper_trigger")):
                helper_decision = self._assemble_bot_decision(str(helper_name), cfg, market_state)

        team = self._snapshot(cfg, lead_decision, support_decision, helper_decision, selected=True, next_candidate=None)
        return TeamDetail(
            team=team,
            lead_decision=lead_decision,
            support_decision=support_decision,
            helper_decision=helper_decision,
            runtime_policy=self._runtime_policy(cfg),
        )
