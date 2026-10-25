"""Unit tests for the routing table in configs/routing.yaml."""

import pytest

from complaintiq.config import load_config
from complaintiq.data import taxonomy
from complaintiq.serving.router import Router


@pytest.fixture(scope="module")
def router() -> Router:
    return Router.from_config()


@pytest.mark.parametrize(
    ("product", "team"),
    [
        (
            "Credit reporting, credit repair services, or other personal consumer reports",
            "Credit Bureau Disputes",
        ),
        ("Debt collection", "Collections Compliance"),
        ("Mortgage", "Lending Servicing"),
        ("Student loan", "Lending Servicing"),
        ("Vehicle loan or lease", "Lending Servicing"),
        ("Credit card or prepaid card", "Card Operations"),
        ("Checking or savings account", "Deposits and Payments"),
        ("Money transfer, virtual currency, or money service", "Deposits and Payments"),
    ],
)
def test_product_routes(router: Router, product: str, team: str) -> None:
    assert router.route(product, "Some issue", "NORMAL") == team


def test_fraud_override_for_high_priority(router: Router) -> None:
    team = router.route("Credit card or prepaid card", "Fraud or scam", "HIGH")
    assert team == "Fraud and Risk"


def test_no_fraud_override_for_normal_priority(router: Router) -> None:
    team = router.route("Credit card or prepaid card", "Fraud or scam", "NORMAL")
    assert team == "Card Operations"


def test_unknown_product_goes_to_default(router: Router) -> None:
    assert router.route("Something new", "Other", "NORMAL") == router.default_team


def explicit_route(router: Router, product: str) -> str | None:
    """Team of the first product route that matches, or None if only the default applies."""
    product_lc = product.lower()
    for r in router.product_routes:
        if any(m in product_lc for m in r.match):
            return r.team
    return None


def test_every_harmonized_product_class_has_an_explicit_route(router: Router) -> None:
    data_cfg = load_config("data")
    other = data_cfg["taxonomy"]["other_label"]
    classes = set(taxonomy.product_map(data_cfg).values()) - {other}
    for cls in sorted(classes):
        team = explicit_route(router, cls)
        assert team is not None, f"{cls!r} falls through to the default team"
        assert team != router.human_review_team, f"{cls!r} routes to human review"
        assert router.route(cls, "Some issue", "NORMAL") == team


def test_other_class_routes_to_human_review_explicitly(router: Router) -> None:
    other = load_config("data")["taxonomy"]["other_label"]
    assert explicit_route(router, other) == router.human_review_team
    assert router.route(other, "Some issue", "NORMAL") == router.human_review_team
