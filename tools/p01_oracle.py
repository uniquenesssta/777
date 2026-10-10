"""P01 diagnostic oracle: exact rational checks of static golden expectations.

Not imported by either business app. No persistence, price loading or auth.
Fraction arithmetic deliberately differs from the planned Decimal/Rust core.
"""
import ast
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "docs/baseline/p01-04-numeric-profile.json").read_text(encoding="utf-8"))
MONEY_LIMIT = int(PROFILE["max_money_cents"])


class Validation(ValueError):
    pass


def half_up(value, scale):
    value *= 10 ** scale
    sign = -1 if value < 0 else 1
    quotient, remainder = divmod(abs(value.numerator), value.denominator)
    return sign * (quotient + (2 * remainder >= value.denominator))


def fraction_digits(value):
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    return max(twos, fives) if denominator == 1 else float("inf")


def checked(value):
    if abs(value) > Fraction(PROFILE["max_intermediate_abs"]) or fraction_digits(value) > PROFILE["intermediate_fraction_digits"]:
        raise Validation("INTERMEDIATE_CAPACITY")
    return value


def normalize(text):
    for old, new in [("，", ","), ("％", "%"), ("×", "*"), ("x", "*"), ("X", "*"), ("÷", "/"), ("（", "("), ("）", ")"), ("人民币", "")]:
        text = text.replace(old, new)
    for unit in ["￥", "¥", "元", "块", "米", "m", "M", "个", "件", "张", "套", "倍", " ", ","]:
        text = text.replace(unit, "")
    return re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)%", r"(\1/100)", text)


def number(raw, default=None):
    if not isinstance(raw, str) or len(raw) > PROFILE["raw_character_limit"]:
        raise Validation("TEXT_TYPE_OR_CAPACITY")
    if not raw.strip():
        if default is not None:
            return Fraction(default)
        raise Validation("EMPTY")
    expression = normalize(raw.strip())
    if not expression or len(expression) > PROFILE["normalized_character_limit"]:
        raise Validation("EXPRESSION_CAPACITY")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise Validation("SYNTAX") from exc
    if len(list(ast.walk(tree))) > PROFILE["ast_node_limit"]:
        raise Validation("AST_CAPACITY")

    def visit(node, depth=0):
        if depth > PROFILE["ast_depth_limit"]:
            raise Validation("AST_DEPTH")
        if isinstance(node, ast.Constant):
            literal = ast.get_source_segment(expression, node)
            if type(node.value) not in (int, float) or not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", literal or ""):
                raise Validation("LITERAL")
            # Bound exponent before constructing huge Decimal/Fraction values.
            if "e" in literal.lower() and not -12 <= int(literal.lower().split("e")[1]) <= 9:
                raise Validation("LITERAL_EXPONENT")
            value = Fraction(Decimal(literal))  # source text, never node.value/float
            if abs(value) > Fraction(PROFILE["max_field_value"]) or fraction_digits(value) > PROFILE["field_fraction_digits"]:
                raise Validation("LITERAL_CAPACITY")
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return checked(-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, (ast.Div, ast.Mod)) and not right:
                raise Validation("DIVISION_BY_ZERO")
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                scale = PROFILE["division_fraction_digits"]
                value = Fraction(half_up(left / right, scale), 10 ** scale)
            else:
                value = left - (left // right) * right
            return checked(value)
        raise Validation("UNSUPPORTED_NODE")

    value = visit(tree.body)
    if value < 0 or value > Fraction(PROFILE["max_field_value"]):
        raise Validation("FIELD_RANGE")
    if fraction_digits(value) > PROFILE["field_fraction_digits"]:
        raise Validation("FIELD_SCALE")
    return value


def percent(raw):
    if not isinstance(raw, str) or len(raw) > PROFILE["raw_character_limit"]:
        raise Validation("DISCOUNT_TEXT")
    raw = raw.strip().replace("％", "%")
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise Validation("DISCOUNT_SYNTAX")
    value = Fraction(Decimal(raw))
    if not 0 <= value <= 100 or fraction_digits(value) > PROFILE["field_fraction_digits"]:
        raise Validation("DISCOUNT_CAPACITY")
    return value


def money_text(cents):
    return ("-" if cents < 0 else "") + f"{abs(cents) // 100}.{abs(cents) % 100:02d}"


def amounts(income, cost, discount=False):
    profit = income - cost
    if any(abs(value) > MONEY_LIMIT for value in (income, cost, profit)):
        raise Validation("MONEY_CAPACITY")
    margin = None
    if income and not discount:
        tenths = half_up(Fraction(profit * 100, income), 1)
        margin = ("-" if tenths < 0 else "") + f"{abs(tenths) // 10}.{abs(tenths) % 10}%"
    return {"income": money_text(income), "cost": money_text(cost), "profit": money_text(profit), "margin": margin}


def quote(case):
    lines, prices = case["input"], case["price_snapshot"]["items"]
    try:
        if not lines or len(lines) > PROFILE["max_order_lines"]:
            raise Validation("LINE_CAPACITY")
        results, income, cost = [], 0, 0
        for line in lines:
            is_discount = line["kind"] == "discount"
            if is_discount:
                sale = half_up(Fraction(income, 100) * (percent(line["percent"]) / 100 - 1), 2)
                expense = 0
            else:
                price = prices[line["product_id"]]
                if type(price["single"]) is not bool:
                    raise Validation("SINGLE_NOT_BOOLEAN")
                base = number(line["q"])
                if not price["single"]:
                    base = checked(base * number(line["h"]) * number(line["w"]))
                sale = half_up(checked(base * number(price["sale"]) * number(price["k"], default="1")), 2)
                expense = half_up(checked(base * number(price["cost"])), 2)
            results.append(amounts(sale, expense, is_discount))
            income, cost = income + sale, cost + expense
            amounts(income, cost)  # subtotal capacity, before later discounts
        return {"status": "ok", "lines": results, "totals": amounts(income, cost)}
    except Validation as exc:
        return {"status": "VALIDATION", "reason": str(exc), "lines": None, "totals": None}
