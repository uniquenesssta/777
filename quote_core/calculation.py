"""Stateless Decimal quotation; no partial authoritative result after an error."""

from decimal import Decimal

from .models import Amounts, CalculatedLine, DiscountLine, Issue, QuoteResult
from .numbers import (
    LINE_LIMIT, NUMERIC_PROFILE, RULE_VERSION, ValidationError, checked,
    decimal_text, exact_context, parse_number, parse_percent, scaled_decimal, settle,
)


def calculate_quote(snapshot, prices):
    index = None
    warnings = []
    try:
        if snapshot.rule_version != RULE_VERSION or snapshot.numeric_profile != NUMERIC_PROFILE:
            raise ValidationError("RULE_VERSION_UNSUPPORTED", "rule_version")
        if (not isinstance(snapshot.price_version_id, str) or not snapshot.price_version_id
                or snapshot.price_version_id != prices.price_version_id):
            raise ValidationError("PRICE_VERSION_MISMATCH", "price_version_id")
        if not snapshot.lines or len(snapshot.lines) > LINE_LIMIT:
            raise ValidationError("LINE_CAPACITY", "lines")
        catalog = {}
        for item in prices.items:
            if not isinstance(item.product_id, str) or not item.product_id or item.product_id in catalog:
                raise ValidationError("PRICE_ID_INVALID_OR_DUPLICATE", "prices")
            catalog[item.product_id] = item
        context = exact_context()
        income = cost = 0
        lines = []
        for index, raw in enumerate(snapshot.lines, 1):
            before = income
            if isinstance(raw, DiscountLine):
                percent = parse_percent(raw.percent)
                # This /100 is an exact settlement factor, not expression division.
                factor = context.subtract(context.multiply(percent, Decimal("0.01")), Decimal(1))
                sale = settle(context.multiply(scaled_decimal(income, 2), factor))
                expense = 0
                price = None
                normalized = (("percent", decimal_text(percent)),)
                if not income:
                    warnings.append(Issue("WARNING", "DISCOUNT_ZERO_SUBTOTAL", "percent", index))
            else:
                if not isinstance(raw.product_id, str) or raw.product_id not in catalog:
                    raise ValidationError("PRODUCT_NOT_FOUND", "product_id")
                price = catalog[raw.product_id]
                if type(price.single) is not bool:
                    raise ValidationError("SINGLE_NOT_BOOLEAN", "single")
                q = parse_number(raw.q, field="q")
                fields = [("q", decimal_text(q))]
                base = q
                if not price.single:
                    h, w = parse_number(raw.h, field="h"), parse_number(raw.w, field="w")
                    base = checked(context.multiply(checked(context.multiply(h, w)), q))
                    fields += [("h", decimal_text(h)), ("w", decimal_text(w))]
                sale_price = parse_number(price.sale, field="sale")
                cost_price = parse_number(price.cost, field="cost")
                k = parse_number(price.k, field="k", empty_k=True)
                sale = settle(checked(context.multiply(checked(context.multiply(base, sale_price)), k)))
                expense = settle(checked(context.multiply(base, cost_price)))
                normalized = tuple(fields + [("sale", decimal_text(sale_price)),
                                             ("cost", decimal_text(cost_price)), ("k", decimal_text(k))])
            amounts = Amounts(sale, expense, isinstance(raw, DiscountLine))
            income += sale
            cost += expense
            totals = Amounts(income, cost)  # each subtotal checked before a later discount
            lines.append(CalculatedLine(index, raw, price, normalized, amounts, before))
        return QuoteResult("ok", snapshot.rule_version, snapshot.numeric_profile,
                           snapshot.price_version_id, tuple(lines), totals, warnings=tuple(warnings))
    except ValidationError as error:
        return QuoteResult("VALIDATION", snapshot.rule_version, snapshot.numeric_profile,
                           snapshot.price_version_id, None, None,
                           (Issue("VALIDATION", error.reason, error.field, index),))
