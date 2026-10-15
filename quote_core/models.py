"""Immutable inputs/results; settled amounts are integer cents, not UI text."""

from dataclasses import asdict, dataclass, field
from .numbers import MONEY_LIMIT, NUMERIC_PROFILE, RULE_VERSION, ValidationError, money_text, rounded_ratio


def _immutable_scalars(instance, fields):
    # Invalid immutable scalars (e.g. a bool quantity) survive until calculation
    # so the validator can report them. Widgets/mutable containers never do.
    for field in fields:
        if type(getattr(instance, field)) not in (str, int, float, bool, type(None)):
            raise ValidationError("SNAPSHOT_SCALAR_TYPE", field)


@dataclass(frozen=True, slots=True)
class NormalLine:
    product_id: str
    q: str
    h: str = ""
    w: str = ""
    name: str = ""
    line_kind: str = field(default="normal", init=False)

    def __post_init__(self):
        _immutable_scalars(self, ("product_id", "q", "h", "w", "name"))


@dataclass(frozen=True, slots=True)
class DiscountLine:
    percent: str
    name: str = "折扣"
    line_kind: str = field(default="discount", init=False)

    def __post_init__(self):
        _immutable_scalars(self, ("percent", "name"))


@dataclass(frozen=True, slots=True)
class PriceItem:
    product_id: str
    sale: str
    cost: str
    k: str = ""
    single: bool = False
    pricing_mode: str | None = None

    def __post_init__(self):
        _immutable_scalars(self, ("product_id", "sale", "cost", "k", "single", "pricing_mode"))


def price_wire(price):
    value = asdict(price)
    if price.pricing_mode is None:
        value.pop("pricing_mode")
    return value


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    price_version_id: str
    items: tuple[PriceItem, ...]

    def __post_init__(self):
        _immutable_scalars(self, ("price_version_id",))
        if not isinstance(self.items, (tuple, list)):
            raise ValidationError("PRICE_ITEMS_TYPE", "prices")
        object.__setattr__(self, "items", tuple(self.items))
        if any(not isinstance(item, PriceItem) for item in self.items):
            raise ValidationError("PRICE_ITEM_TYPE", "prices")


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    price_version_id: str
    lines: tuple[NormalLine | DiscountLine, ...]
    rule_version: str = RULE_VERSION
    numeric_profile: str = NUMERIC_PROFILE

    def __post_init__(self):
        _immutable_scalars(self, ("price_version_id", "rule_version", "numeric_profile"))
        if not isinstance(self.lines, (tuple, list)):
            raise ValidationError("LINES_TYPE", "lines")
        object.__setattr__(self, "lines", tuple(self.lines))
        if any(not isinstance(line, (NormalLine, DiscountLine)) for line in self.lines):
            raise ValidationError("LINE_TYPE", "lines")


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    reason: str
    field: str
    line_index: int | None = None  # one-based input row


@dataclass(frozen=True, slots=True)
class Amounts:
    income_cents: int
    cost_cents: int
    discount: bool = False

    def __post_init__(self):
        if (type(self.income_cents) is not int or type(self.cost_cents) is not int
                or type(self.discount) is not bool):
            raise ValidationError("MONEY_TYPE", "amounts")
        for value in (self.income_cents, self.cost_cents, self.profit_cents):
            if type(value) is not int or abs(value) > MONEY_LIMIT:
                raise ValidationError("MONEY_CAPACITY", "amounts")

    @property
    def profit_cents(self):
        return self.income_cents - self.cost_cents

    @property
    def margin_tenths(self):
        if not self.income_cents or self.discount:
            return None
        return rounded_ratio(self.profit_cents * 100, self.income_cents, 1)

    def display(self):
        tenths = self.margin_tenths
        margin = None if tenths is None else (
            ("-" if tenths < 0 else "") + f"{abs(tenths) // 10}.{abs(tenths) % 10}%"
        )
        return {"income": money_text(self.income_cents), "cost": money_text(self.cost_cents),
                "profit": money_text(self.profit_cents), "margin": margin}

    def cents_payload(self):
        return {"income_cents": str(self.income_cents), "cost_cents": str(self.cost_cents),
                "profit_cents": str(self.profit_cents)}


@dataclass(frozen=True, slots=True)
class CalculatedLine:
    sequence: int
    raw: NormalLine | DiscountLine
    price: PriceItem | None
    normalized: tuple[tuple[str, str], ...]
    amounts: Amounts
    subtotal_before_cents: int


@dataclass(frozen=True, slots=True)
class QuoteResult:
    status: str
    rule_version: str
    numeric_profile: str
    price_version_id: str
    lines: tuple[CalculatedLine, ...] | None
    totals: Amounts | None
    issues: tuple[Issue, ...] = ()
    warnings: tuple[Issue, ...] = ()

    def display(self):
        return {"status": self.status,
                "lines": None if self.lines is None else [line.amounts.display() for line in self.lines],
                "totals": None if self.totals is None else self.totals.display()}
