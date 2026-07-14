from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .lineage import profile_sha256
from .types import MethodProfile, MethodSubtype, TradeMethod

ALLOWED_COMBINATIONS: Mapping[TradeMethod, tuple[MethodSubtype, ...]] = {
    TradeMethod.SCALP_FIRST: (MethodSubtype.REVERT, MethodSubtype.CONTINUATION, MethodSubtype.LIQUIDITY_RECLAIM),
    TradeMethod.INTRADAY: (MethodSubtype.BREAKOUT_PROBE, MethodSubtype.RESCUE),
    TradeMethod.TACTICAL_SWING: (MethodSubtype.CONTINUATION,),
    TradeMethod.BLOCKED: (),
}


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    method: TradeMethod
    method_subtype: MethodSubtype
    profile_version: str
    profile_sha256: str


def is_allowed(method: TradeMethod, subtype: MethodSubtype) -> bool:
    return subtype in ALLOWED_COMBINATIONS.get(method, ())


def build_manifest(profiles: Mapping[tuple[TradeMethod, MethodSubtype], MethodProfile]) -> tuple[ManifestEntry, ...]:
    entries = [ManifestEntry(method=method, method_subtype=subtype, profile_version=profile.profile_version, profile_sha256=profile_sha256(profile)) for (method, subtype), profile in profiles.items()]
    return tuple(sorted(entries, key=lambda item: (item.method.value, item.method_subtype.value)))


def manifest_index(profiles: Mapping[tuple[TradeMethod, MethodSubtype], MethodProfile]) -> dict[tuple[TradeMethod, MethodSubtype], ManifestEntry]:
    return {(entry.method, entry.method_subtype): entry for entry in build_manifest(profiles)}
