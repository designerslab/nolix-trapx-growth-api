from decimal import Decimal

from app.revenue_api import _fmt, _money, _shop_money


def test_money_helpers():
    assert _money("12.34") == Decimal("12.34")
    assert _money(None) == Decimal("0")
    assert _fmt(Decimal("12.3")) == "12.30"


def test_shop_money():
    order = {
        "currentTotalPriceSet": {
            "shopMoney": {
                "amount": "99.95",
                "currencyCode": "USD",
            }
        }
    }
    amount, currency = _shop_money(order, "currentTotalPriceSet")
    assert amount == Decimal("99.95")
    assert currency == "USD"
