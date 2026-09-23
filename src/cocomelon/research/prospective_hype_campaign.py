from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2,
    HistoricalDiscoveryFreezeSpec,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
    HYPE_PROSPECTIVE_VALIDATION_V2,
    ProspectiveValidationPlan,
)

ProspectiveHypeCampaignVersion = Literal["v1", "v2"]


@dataclass(frozen=True, slots=True)
class ProspectiveHypeCampaign:
    version: ProspectiveHypeCampaignVersion
    spec: HistoricalDiscoveryFreezeSpec
    plan: ProspectiveValidationPlan


HYPE_PROSPECTIVE_CAMPAIGN_V1 = ProspectiveHypeCampaign(
    version="v1",
    spec=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    plan=HYPE_PROSPECTIVE_VALIDATION_V1,
)

HYPE_PROSPECTIVE_CAMPAIGN_V2 = ProspectiveHypeCampaign(
    version="v2",
    spec=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2,
    plan=HYPE_PROSPECTIVE_VALIDATION_V2,
)


def resolve_prospective_hype_campaign(
    version: str,
) -> ProspectiveHypeCampaign:
    if version == "v1":
        return HYPE_PROSPECTIVE_CAMPAIGN_V1
    if version == "v2":
        return HYPE_PROSPECTIVE_CAMPAIGN_V2
    raise ValueError(f"unsupported prospective HYPE campaign: {version}")
