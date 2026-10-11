"""Owner-thread draft state and synchronous output gates; no UI or file I/O.

Workers only receive immutable calculation requests. Price-source observations
must come from the caller's verified loader/service, not from financial input.
This local gate is not authentication, a transaction or a published-price proof.
"""

from dataclasses import dataclass, field, replace

from .calculation import calculate_quote
from .models import Amounts, CalculatedLine, Issue, PriceSnapshot, QuoteResult, QuoteSnapshot
from .numbers import NUMERIC_PROFILE, RULE_VERSION


@dataclass(frozen=True, slots=True)
class DraftDetails:
    customer: str = ""
    order_ref: str = ""
    wechat: str = ""

    def __post_init__(self):
        if any(type(value) is not str for value in (self.customer, self.order_ref, self.wechat)):
            raise TypeError("Draft details must be text, not controls or numeric identifiers")


@dataclass(frozen=True, slots=True)
class QuoteState:
    revision: int
    calculation_revision: int | None
    status: str  # uncalculated / stale / valid / invalid; valid is not permission
    snapshot: QuoteSnapshot | None
    prices: PriceSnapshot | None
    details: DraftDetails
    result: QuoteResult | None
    input_issues: tuple[Issue, ...]
    price_source: str
    latest_price_version_id: str | None
    price_confirmation_required: bool


@dataclass(frozen=True, slots=True)
class CalculationRequest:
    _owner: object = field(repr=False)
    revision: int
    snapshot: QuoteSnapshot | None
    prices: PriceSnapshot | None
    details: DraftDetails
    input_issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class CalculationCompletion:
    request: CalculationRequest
    result: QuoteResult


def run_calculation(request):
    """Worker-safe pure calculation. A completion must return to its owner."""
    if type(request) is not CalculationRequest:
        raise TypeError("Expected CalculationRequest")
    if request.input_issues or request.snapshot is None or request.prices is None:
        issues = request.input_issues or (
            Issue("VALIDATION", "SNAPSHOT_REQUIRED", "snapshot") if request.snapshot is None
            else Issue("VALIDATION", "PRICE_SNAPSHOT_REQUIRED", "prices"),)
        snapshot = request.snapshot
        result = QuoteResult("VALIDATION", snapshot.rule_version if snapshot else RULE_VERSION,
                             snapshot.numeric_profile if snapshot else NUMERIC_PROFILE,
                             snapshot.price_version_id if snapshot else "", None, None, issues)
    else:
        result = calculate_quote(request.snapshot, request.prices)
    return CalculationCompletion(request, result)


@dataclass(frozen=True, slots=True)
class OutputPayload:
    revision: int
    snapshot: QuoteSnapshot
    prices: PriceSnapshot
    details: DraftDetails
    result: QuoteResult


@dataclass(frozen=True, slots=True)
class OutputDecision:
    kind: str
    status: str
    payload: OutputPayload | None = None
    issues: tuple[Issue, ...] = ()

    @property
    def allowed(self):
        return self.status == "ok"


class OutputBlocked(Exception):
    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.status)


class QuoteSession:
    """Mutate on the UI/owner thread; never share this controller with workers.

    Every input, metadata, price refresh or source-status change invalidates the
    current result. An explicit price refresh rebinds the draft, then requires
    recalculation and confirmation. Merely observing a new version never binds.
    """

    def __init__(self, snapshot=None, prices=None, *, details=None,
                 price_source="unverified", latest_price_version_id=None):
        self._check(snapshot, QuoteSnapshot, optional=True)
        self._check(prices, PriceSnapshot, optional=True)
        details = DraftDetails() if details is None else details
        self._check(details, DraftDetails)
        self._check_source(price_source, latest_price_version_id)
        self._owner = object()
        self._snapshot, self._prices, self._details = snapshot, prices, details
        self._source, self._latest = price_source, latest_price_version_id
        self._revision = 0
        self._calculation_revision = None
        self._result = None
        self._input_issues = ()
        self._has_calculated = False
        self._confirmation_required = False

    @staticmethod
    def _check(value, expected, *, optional=False):
        if not (optional and value is None) and type(value) is not expected:
            raise TypeError("Expected " + expected.__name__)

    @staticmethod
    def _check_source(status, version):
        if type(status) is not str or status not in ("current", "unavailable", "unverified", "invalid"):
            raise ValueError("Unknown price-source status")
        if version is not None and (type(version) is not str or not version
                or version != version.strip() or len(version) > 256
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in version)):
            raise ValueError("Invalid latest price version")

    @property
    def state(self):
        status = ("invalid" if self._input_issues or self._result is not None and self._result.status != "ok"
                  else "valid" if self._result is not None
                  else "stale" if self._has_calculated else "uncalculated")
        return QuoteState(self._revision, self._calculation_revision, status,
                          self._snapshot, self._prices, self._details, self._result, self._input_issues,
                          self._source, self._latest, self._confirmation_required)

    def _invalidate(self):
        self._revision += 1
        self._result = None
        self._calculation_revision = None

    def update_inputs(self, snapshot, *, details=None):
        self._check(snapshot, QuoteSnapshot)
        if details is not None:
            self._check(details, DraftDetails)
        self._invalidate()
        self._snapshot = snapshot
        if details is not None:
            self._details = details
        self._input_issues = ()

    def update_details(self, details):
        self._check(details, DraftDetails)
        self._invalidate()
        self._details = details

    def invalidate_inputs(self, issues=()):
        """Call immediately on edits, even before the next snapshot is captured."""
        if type(issues) not in (tuple, list) or any(type(i) is not Issue or i.code != "VALIDATION" for i in issues):
            raise TypeError("Expected validation issues")
        self._invalidate()
        self._snapshot = None
        self._input_issues = tuple(issues)

    def observe_price_source(self, status, *, latest_price_version_id=None):
        self._check_source(status, latest_price_version_id)
        if (status, latest_price_version_id) != (self._source, self._latest):
            self._invalidate()
            self._source, self._latest = status, latest_price_version_id

    def refresh_prices(self, prices):
        """Explicit refresh only; source verification is a separate observation."""
        self._check(prices, PriceSnapshot)
        snapshot = replace(self._snapshot, price_version_id=prices.price_version_id) if self._snapshot else None
        self._confirmation_required = self._confirmation_required or self._prices is not None
        self._invalidate()
        self._prices, self._snapshot = prices, snapshot

    def begin_calculation(self):
        return CalculationRequest(self._owner, self._revision, self._snapshot, self._prices,
                                  self._details, self._input_issues)

    def apply_calculation(self, completion):
        self._check(completion, CalculationCompletion)
        request = completion.request
        if (type(request) is not CalculationRequest or request._owner is not self._owner
                or request.revision != self._revision or request.snapshot is not self._snapshot
                or request.prices is not self._prices or request.details is not self._details
                or request.input_issues != self._input_issues):
            return False  # Old/cross-draft work cannot replace a newer result or error.
        self._check(completion.result, QuoteResult)
        self._result = completion.result
        self._calculation_revision = request.revision
        self._has_calculated = True
        return True

    def calculate(self):
        self.apply_calculation(run_calculation(self.begin_calculation()))
        return self.state

    def _output_problem(self, *, check_confirmation=True):
        def problem(code, reason, field):
            return code, (Issue(code, reason, field),)
        if self._input_issues:
            return "VALIDATION", self._input_issues
        if self._result is not None and self._result.status != "ok":
            return "VALIDATION", self._result.issues
        if self._source == "unavailable":
            return problem("IO_UNAVAILABLE", "PRICES_UNAVAILABLE", "price_source")
        if self._source != "current" or self._latest is None:
            return problem("VALIDATION", "PRICE_CONFIG_INVALID" if self._source == "invalid"
                           else "PRICE_SOURCE_UNVERIFIED", "price_source")
        if self._prices is None:
            return problem("VALIDATION", "PRICE_SNAPSHOT_REQUIRED", "prices")
        if self._prices.price_version_id != self._latest:
            return problem("PRICE_STALE", "PRICE_VERSION_CHANGED", "price_version_id")
        if self._snapshot is None or self._result is None or self._calculation_revision != self._revision:
            return problem("CALCULATION_STALE" if self._has_calculated else "VALIDATION",
                           "CALCULATION_REQUIRED", "calculation_revision")
        result = self._result
        if (result.price_version_id != self._snapshot.price_version_id or result.price_version_id != self._latest
                or result.rule_version != self._snapshot.rule_version or result.numeric_profile != self._snapshot.numeric_profile):
            return problem("CALCULATION_STALE", "RESULT_VERSION_MISMATCH", "calculation_revision")
        if (type(result.lines) is not tuple or not result.lines or type(result.totals) is not Amounts
                or len(result.lines) != len(self._snapshot.lines)
                or any(type(line) is not CalculatedLine or type(line.amounts) is not Amounts
                       for line in result.lines)):
            return problem("VALIDATION", "RESULT_INCOMPLETE", "lines")
        if (any(line.sequence != index or line.raw != raw
                for index, (line, raw) in enumerate(zip(result.lines, self._snapshot.lines), 1))
                or sum(line.amounts.income_cents for line in result.lines) != result.totals.income_cents
                or sum(line.amounts.cost_cents for line in result.lines) != result.totals.cost_cents):
            return problem("VALIDATION", "RESULT_INCONSISTENT", "lines")
        if check_confirmation and self._confirmation_required:
            return problem("VALIDATION", "PRICE_CONFIRMATION_REQUIRED", "price_version_id")
        return None

    def confirm_prices(self, *, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Expected a draft revision integer")
        if expected_revision != self._revision or self._output_problem(check_confirmation=False):
            return False
        self._confirmation_required = False
        return True

    def prepare_output(self, kind):
        if type(kind) is not str or kind not in ("excel", "quote_image", "screenshot"):
            raise ValueError("Unknown output kind")
        problem = self._output_problem()
        if problem:
            return OutputDecision(kind, problem[0], issues=problem[1])
        return OutputDecision(kind, "ok", OutputPayload(self._revision, self._snapshot, self._prices,
                                                       self._details, self._result))

    def dispatch_output(self, kind, writer):
        """Gate again at invocation; the writer must not yield or mutate the draft.

        Select paths/dialogs beforehand. Blocked calls never invoke the writer.
        Writer exceptions propagate: this layer cannot infer persistence state.
        """
        decision = self.prepare_output(kind)
        if not decision.allowed:
            raise OutputBlocked(decision)
        if not callable(writer):
            raise TypeError("Expected an output writer")
        return writer(decision.payload)
