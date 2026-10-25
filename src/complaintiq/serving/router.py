"""Deterministic team routing from product/issue/priority (SPEC B6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from complaintiq.config import load_config


@dataclass(frozen=True)
class ProductRoute:
    """One row of the routing table: substrings of product labels -> team."""

    team: str
    match: tuple[str, ...]


@dataclass(frozen=True)
class FraudOverride:
    """HIGH-priority fraud/identity cases go to this team, overriding product routes."""

    team: str
    priority: str
    issue_keywords: tuple[str, ...]


class Router:
    """Map a prediction to a destination team using ``configs/routing.yaml``."""

    def __init__(
        self,
        product_routes: list[ProductRoute],
        fraud_override: FraudOverride | None,
        default_team: str,
        human_review_team: str,
    ) -> None:
        self.product_routes = product_routes
        self.fraud_override = fraud_override
        self.default_team = default_team
        self.human_review_team = human_review_team

    @classmethod
    def from_config(cls, routing: dict[str, Any] | None = None) -> Router:
        """Build from a routing mapping, defaulting to ``configs/routing.yaml``."""
        cfg = routing if routing is not None else load_config("routing")
        routes = [
            ProductRoute(team=r["team"], match=tuple(m.lower() for m in r["match"]))
            for r in cfg.get("product_routes", [])
        ]
        fo = cfg.get("fraud_override")
        override = (
            FraudOverride(
                team=fo["team"],
                priority=fo.get("priority", "HIGH"),
                issue_keywords=tuple(k.lower() for k in fo.get("issue_keywords", [])),
            )
            if fo
            else None
        )
        human = cfg.get("human_review_team", "Human Review Queue")
        return cls(routes, override, cfg.get("default_team", human), human)

    def route(self, product: str, issue: str, priority: str) -> str:
        """Return the team for an auto-routed prediction.

        The fraud override is checked first; then the first product route with a
        matching substring wins; otherwise ``default_team``.
        """
        if self.fraud_override and priority == self.fraud_override.priority:
            issue_lc = issue.lower()
            if any(k in issue_lc for k in self.fraud_override.issue_keywords):
                return self.fraud_override.team
        product_lc = product.lower()
        for r in self.product_routes:
            if any(m in product_lc for m in r.match):
                return r.team
        return self.default_team
