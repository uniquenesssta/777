"""Decimal operations for accepted numeric-v1; rounding uses exact integer ratios.

An explicit 256-digit context traps inexact non-division arithmetic. Division
rounding never relies on a finite-precision approximation of a repeating value.
"""

import ast
from decimal import (
    Context, Decimal, DivisionByZero, FloatOperation, Inexact,
    InvalidOperation, Overflow, ROUND_HALF_UP,
)
import re

RULE_VERSION = "business-v1"
NUMERIC_PROFILE = "numeric-v1"
MAX_FIELD = Decimal("1000000000")
MAX_INTERMEDIATE = Decimal("1e45")
MONEY_LIMIT = 9223372036854775807
FIELD_SCALE = DIVISION_SCALE = 12
INTERMEDIATE_SCALE = 60
EXACT_PRECISION = 256
RAW_LIMIT, EXPRESSION_LIMIT = 256, 80
AST_LIMIT, DEPTH_LIMIT = 64, 16
LINE_LIMIT = 10000


class ValidationError(ValueError):
    def __init__(self, reason, field=""):
        super().__init__(reason)
        self.reason = reason
        self.field = field


def exact_context():
    # Do not inherit precision, traps, rounding or flags from the calling thread.
    return Context(
        prec=EXACT_PRECISION, rounding=ROUND_HALF_UP, Emin=-999999,
        Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow,
                           Inexact, FloatOperation],
    )


def fractional_digits(value):
    if not value:
        return 0
    parts = value.as_tuple()
    trailing = 0
    for digit in reversed(parts.digits):
        if digit:
            break
        trailing += 1
    return max(0, -parts.exponent - trailing)


def checked(value):
    if (not value.is_finite() or value.copy_abs() > MAX_INTERMEDIATE
            or fractional_digits(value) > INTERMEDIATE_SCALE):
        raise ValidationError("INTERMEDIATE_CAPACITY")
    return value


def rounded_ratio(numerator, denominator, scale):
    """Return signed units at scale with HALF_UP, including negative half ties."""
    if not denominator:
        raise ValidationError("DIVISION_BY_ZERO")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator) * 10 ** scale, denominator)
    return sign * (quotient + (2 * remainder >= denominator))


def scaled_decimal(units, scale):
    # Decimal.scaleb/unary minus could obey a caller's small global context.
    return Decimal((int(units < 0), tuple(map(int, str(abs(units)))), -scale))


def divide(left, right):
    ln, ld = left.as_integer_ratio()
    rn, rd = right.as_integer_ratio()
    return checked(scaled_decimal(rounded_ratio(ln * rd, ld * rn, DIVISION_SCALE), DIVISION_SCALE))


def settle(value):
    numerator, denominator = value.as_integer_ratio()
    return rounded_ratio(numerator, denominator, 2)


def normalize(text):
    for old, new in (("，", ","), ("％", "%"), ("×", "*"), ("x", "*"),
                     ("X", "*"), ("÷", "/"), ("（", "("), ("）", ")"), ("人民币", "")):
        text = text.replace(old, new)
    for unit in ("￥", "¥", "元", "块", "米", "m", "M", "个", "件", "张", "套", "倍", " ", ","):
        text = text.replace(unit, "")
    return re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)%", r"(\1/100)", text)


def parse_number(raw, *, field="", empty_k=False):
    try:
        return _parse_number(raw, empty_k)
    except ValidationError as error:
        raise ValidationError(error.reason, field) from error


def _parse_number(raw, empty_k):
    if not isinstance(raw, str) or len(raw) > RAW_LIMIT:
        raise ValidationError("TEXT_TYPE_OR_CAPACITY")
    if not raw.strip():
        if empty_k:
            return Decimal(1)
        raise ValidationError("EMPTY")
    expression = normalize(raw.strip())
    if not expression or len(expression) > EXPRESSION_LIMIT:
        raise ValidationError("EXPRESSION_CAPACITY")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValidationError("SYNTAX") from error
    if sum(1 for _ in ast.walk(tree)) > AST_LIMIT:
        raise ValidationError("AST_CAPACITY")
    context = exact_context()

    def visit(node, depth=0):
        if depth > DEPTH_LIMIT:
            raise ValidationError("AST_DEPTH")
        if isinstance(node, ast.Constant):
            literal = ast.get_source_segment(expression, node)
            if (type(node.value) not in (int, float) or not re.fullmatch(
                    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", literal or "")):
                raise ValidationError("LITERAL")
            if "e" in literal.lower():
                exponent = int(literal.lower().split("e")[1])
                if not -12 <= exponent <= 9:
                    raise ValidationError("LITERAL_EXPONENT")
            value = Decimal(literal)  # original token, never AST's float value
            if value.copy_abs() > MAX_FIELD or fractional_digits(value) > FIELD_SCALE:
                raise ValidationError("LITERAL_CAPACITY")
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return checked(value.copy_negate() if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
                raise ValidationError("UNSUPPORTED_NODE")
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, (ast.Div, ast.Mod)) and not right:
                raise ValidationError("DIVISION_BY_ZERO")
            if isinstance(node.op, ast.Div):
                return divide(left, right)
            if isinstance(node.op, ast.Add):
                value = context.add(left, right)
            elif isinstance(node.op, ast.Sub):
                value = context.subtract(left, right)
            elif isinstance(node.op, ast.Mult):
                value = context.multiply(left, right)
            else:
                # Python remainder uses floor(a/b), while Decimal % truncates.
                ln, ld = left.as_integer_ratio()
                rn, rd = right.as_integer_ratio()
                floor_quotient = (ln * rd) // (ld * rn)
                value = context.subtract(left, context.multiply(Decimal(floor_quotient), right))
            return checked(value)
        raise ValidationError("UNSUPPORTED_NODE")

    value = visit(tree.body)
    if value < 0 or value > MAX_FIELD:
        raise ValidationError("FIELD_RANGE")
    if fractional_digits(value) > FIELD_SCALE:
        raise ValidationError("FIELD_SCALE")
    return value if value else Decimal(0)


def parse_percent(raw):
    if not isinstance(raw, str) or len(raw) > RAW_LIMIT:
        raise ValidationError("DISCOUNT_TEXT", "percent")
    text = raw.strip().replace("％", "%")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ValidationError("DISCOUNT_SYNTAX", "percent")
    value = Decimal(text)
    if not 0 <= value <= 100 or fractional_digits(value) > FIELD_SCALE:
        raise ValidationError("DISCOUNT_CAPACITY", "percent")
    return value


def decimal_text(value):
    if not value:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def money_text(cents):
    return ("-" if cents < 0 else "") + f"{abs(cents) // 100}.{abs(cents) % 100:02d}"
