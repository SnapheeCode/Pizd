from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(slots=True)
class Order:
    id: str
    title: str
    creation: datetime
    budget: Optional[int]
    recommended_budget: Optional[int]
    subject_id: Optional[str]
    type_id: Optional[str]
    count_offers: int
    author_has_offer: bool

    @classmethod
    def from_graphql(cls, payload: Dict[str, Any]) -> "Order":
        creation = payload.get("creation")
        if isinstance(creation, str):
            creation_dt = datetime.fromisoformat(creation.replace("Z", "+00:00"))
        else:
            creation_dt = datetime.utcnow()
        budget = payload.get("budget")
        recommended = payload.get("recommendedBudget")
        subject = (payload.get("category") or {}).get("id")
        type_id = (payload.get("type") or {}).get("id")
        return cls(
            id=str(payload.get("id")),
            title=payload.get("title", ""),
            creation=creation_dt,
            budget=budget,
            recommended_budget=recommended,
            subject_id=subject,
            type_id=type_id,
            count_offers=int(payload.get("countOffers") or 0),
            author_has_offer=bool(payload.get("authorHasOffer")),
        )

    @property
    def is_new(self) -> bool:
        return not self.author_has_offer and self.count_offers == 0
