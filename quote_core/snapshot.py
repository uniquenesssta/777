"""Capture the two legacy row layouts on their UI thread, once per used field.

Callers provide an already obtained price mapping and explicit version. This
adapter never loads prices or reads summary/result widgets. P02-04 wires it in.
"""

from .models import DiscountLine, NormalLine, PriceItem, PriceSnapshot, QuoteSnapshot
from .numbers import LINE_LIMIT, ValidationError


def _text(value, field):
    if not isinstance(value, str):
        getter = getattr(value, "get", None)
        if callable(getter):
            value = getter()
    if not isinstance(value, str):
        raise ValidationError("SNAPSHOT_TEXT_TYPE", field)
    return value


def capture_legacy_quote(rows, config, *, price_version_id):
    """Return immutable quote/prices; getters must be read on the owning UI thread."""
    lines, items = [], {}
    for row in rows:
        if len(lines) >= LINE_LIMIT:
            raise ValidationError("LINE_CAPACITY", "lines")
        kind = row.get("row_kind", "normal")
        name = _text(row.get("display_name", ""), "name")
        if kind == "discount":
            choice = _text(row["discount_choice"], "percent")
            # Preserve explicit selection; an empty selection is an error.
            raw = _text(row["discount_custom"], "percent") if choice.strip() == "自定义" else choice
            lines.append(DiscountLine(raw, name))
        elif kind == "normal":
            product_id = _text(row["base_type"], "product_id")
            if product_id not in items:
                if product_id not in config:
                    raise ValidationError("PRODUCT_NOT_FOUND", "product_id")
                price = config[product_id]
                items[product_id] = PriceItem(product_id, _text(price.get("sale", ""), "sale"),
                    _text(price.get("cost", ""), "cost"), _text(price.get("k", ""), "k"), price.get("single", False), price.get("pricing_mode"))
            single = items[product_id].single is True
            lines.append(NormalLine(product_id, _text(row["q"], "q"),
                "" if single else _text(row["h"], "h"),
                "" if single else _text(row["w"], "w"), name))
        else:
            raise ValidationError("LINE_KIND", "kind")
    return QuoteSnapshot(price_version_id, tuple(lines)), PriceSnapshot(price_version_id, tuple(items.values()))
