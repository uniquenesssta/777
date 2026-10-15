"""Exact final unit-price modes; legacy entries keep their original multiplier."""
from .numbers import checked, exact_context, parse_number, ValidationError


def unit_sale(price):
    cost = parse_number(price.cost, field="cost")
    k = parse_number(price.k, field="k", empty_k=True)
    if price.pricing_mode == "cost_plus":
        return checked(exact_context().multiply(cost, k))
    sale = parse_number(price.sale, field="sale")
    if price.pricing_mode == "manual":
        return sale
    if price.pricing_mode is not None:
        raise ValidationError("PRICING_MODE_INVALID", "pricing_mode")
    return checked(exact_context().multiply(sale, k))
