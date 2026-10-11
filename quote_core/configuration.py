"""Validate whole legacy/current JSON configurations without filesystem I/O.

Numbers are captured as their JSON tokens, never decoded through float. A bad
item rejects the whole candidate; refresh is a pure transition retaining the
previous validated configuration. Version allocation/publication belongs to
the caller, not this parser.
"""

from dataclasses import dataclass
import json

from .models import Issue, PriceItem, PriceSnapshot
from .numbers import RAW_LIMIT, ValidationError, parse_number

CONFIG_BYTE_LIMIT = 1024 * 1024
CONFIG_DEPTH_LIMIT = 32
PRODUCT_LIMIT = 10000
NAME_LIMIT = 256
PATH_TEXT_LIMIT = 32767


@dataclass(frozen=True, slots=True)
class ValidatedPriceConfig:
    prices: PriceSnapshot
    source_schema: str
    export_dir: str | None
    original_json: str
    screenshot_dir: str | None = None


@dataclass(frozen=True, slots=True)
class PriceConfigResult:
    status: str
    config: ValidatedPriceConfig | None
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceConfigRefresh:
    active: ValidatedPriceConfig | None
    validation: PriceConfigResult

    @property
    def applied(self):
        return self.validation.status == "ok"


class _JSONNumber(str):
    """Distinguish unquoted JSON numbers from name/path strings."""


def _number_token(token):
    if len(token) > RAW_LIMIT:
        raise ValidationError("JSON_NUMBER_CAPACITY", "json")
    return _JSONNumber(token)


def _nonfinite(token):
    raise ValidationError("JSON_NON_FINITE", "json")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON_DUPLICATE_KEY", "json")
        result[key] = value
    return result


def _check_depth(text):
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > CONFIG_DEPTH_LIMIT:
                raise ValidationError("JSON_DEPTH_CAPACITY", "json")
        elif char in "]}":
            depth -= 1


def _text(value, field, limit):
    if type(value) is not str or len(value) > limit:
        raise ValidationError("CONFIG_TEXT_TYPE_OR_CAPACITY", field)
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValidationError("CONFIG_TEXT_ENCODING", field) from error
    if any(ord(char) < 32 for char in value):
        raise ValidationError("CONFIG_TEXT_CONTROL", field)
    return value


def _name(value, field):
    name = _text(value, field, NAME_LIMIT).strip()
    if not name:
        raise ValidationError("PRODUCT_NAME_EMPTY", field)
    if name == "折扣":
        raise ValidationError("PRODUCT_NAME_RESERVED", field)
    return name


def _price_text(value, field, *, empty_k=False):
    if type(value) not in (str, _JSONNumber):
        raise ValidationError("CONFIG_NUMBER_TYPE", field)
    raw = str(value)
    parse_number(raw, field=field, empty_k=empty_k)
    return raw


def _issue(error):
    return Issue("VALIDATION", error.reason, error.field)


def parse_price_config(source, *, price_version_id, legacy_single_names=None):
    """Validate UTF-8 bytes/text; return a detached candidate or only errors.

    Legacy dictionaries lack type flags: an explicit collection of single-item
    names (possibly empty) is required. Current ``single``/``qty_only`` values
    must be real booleans; absence means False, as in the existing readers.
    """
    try:
        version = _text(price_version_id, "price_version_id", RAW_LIMIT)
        if not version or version != version.strip():
            raise ValidationError("PRICE_VERSION_ID", "price_version_id")
        if type(source) is bytes:
            if len(source) > CONFIG_BYTE_LIMIT:
                raise ValidationError("JSON_BYTE_CAPACITY", "json")
            try:
                original = source.decode("utf-8")
            except UnicodeError as error:
                raise ValidationError("JSON_ENCODING", "json") from error
        elif type(source) is str:
            original = source
        else:
            raise ValidationError("JSON_SOURCE_TYPE", "json")
        try:
            if len(original) > CONFIG_BYTE_LIMIT or len(original.encode("utf-8")) > CONFIG_BYTE_LIMIT:
                raise ValidationError("JSON_BYTE_CAPACITY", "json")
        except UnicodeError as error:
            raise ValidationError("JSON_ENCODING", "json") from error
        text = original.removeprefix("\ufeff")
        _check_depth(text)
        try:
            data = json.loads(text, parse_int=_number_token, parse_float=_number_token,
                              parse_constant=_nonfinite, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValidationError("JSON_SYNTAX", "json") from error
        if type(data) is not dict:
            raise ValidationError("CONFIG_ROOT_TYPE", "json")

        issues = []
        directories = {}
        for field in ("export_dir", "screenshot_dir"):
            if field not in data:
                continue
            try:
                directories[field] = _text(data[field], field, PATH_TEXT_LIMIT)
            except ValidationError as error:
                issues.append(_issue(error))
        if "items" in data:
            schema = "json_items"
            for key in data:
                if key not in {"items", "export_dir", "screenshot_dir"}:
                    issues.append(Issue("VALIDATION", "CONFIG_UNKNOWN_FIELD", key))
            if type(data["items"]) is not list:
                raise ValidationError("CONFIG_ITEMS_TYPE", "items")
            entries = data["items"]
            single_names = frozenset()
        else:
            schema = "json_legacy_price_dict"
            entries = [(key, value) for key, value in data.items() if key not in {"export_dir", "screenshot_dir"}]
            if entries:
                if type(legacy_single_names) not in (tuple, list, set, frozenset):
                    raise ValidationError("LEGACY_SINGLE_POLICY_REQUIRED", "legacy_single_names")
                if len(legacy_single_names) > PRODUCT_LIMIT:
                    raise ValidationError("CONFIG_PRODUCT_CAPACITY", "legacy_single_names")
                single_names = frozenset(_name(name, "legacy_single_names") for name in legacy_single_names)
        if not entries or len(entries) > PRODUCT_LIMIT:
            raise ValidationError("CONFIG_PRODUCT_CAPACITY", "items")

        items, seen = [], set()
        for index, entry in enumerate(entries):
            base = f"items[{index}]" if schema == "json_items" else f"legacy[{index}]"
            try:
                if schema == "json_legacy_price_dict":
                    name, values = entry
                    if type(values) is not list or len(values) != 3:
                        raise ValidationError("LEGACY_PRICE_SHAPE", base)
                    entry = dict(zip(("sale", "cost", "k"), values), name=name)
                elif type(entry) is not dict:
                    raise ValidationError("CONFIG_ITEM_TYPE", base)
                for key in entry:
                    if key not in {"name", "sale", "cost", "k", "single", "qty_only"}:
                        issues.append(Issue("VALIDATION", "CONFIG_UNKNOWN_FIELD", f"{base}.{key}"))
                name = _name(entry.get("name"), f"{base}.name")
                if name in seen:
                    raise ValidationError("PRODUCT_NAME_DUPLICATE", f"{base}.name")
                seen.add(name)
                single = name in single_names
                for flag in ("single", "qty_only"):
                    if flag in entry and type(entry[flag]) is not bool:
                        raise ValidationError("SINGLE_NOT_BOOLEAN", f"{base}.{flag}")
                if "single" in entry and "qty_only" in entry and entry["single"] != entry["qty_only"]:
                    raise ValidationError("SINGLE_FLAGS_CONFLICT", f"{base}.single")
                if schema == "json_items":
                    single = entry.get("single", entry.get("qty_only", False))
                sale = _price_text(entry.get("sale"), f"{base}.sale")
                cost = _price_text(entry.get("cost"), f"{base}.cost")
                k = _price_text(entry.get("k", ""), f"{base}.k", empty_k=True)
                items.append(PriceItem(name, sale, cost, k, single))
            except ValidationError as error:
                issues.append(_issue(error))
        if issues:
            return PriceConfigResult("VALIDATION", None, tuple(issues))
        return PriceConfigResult("ok", ValidatedPriceConfig(
            PriceSnapshot(version, tuple(items)), schema, directories.get("export_dir"), original,
            directories.get("screenshot_dir")))
    except ValidationError as error:
        return PriceConfigResult("VALIDATION", None, (_issue(error),))


def refresh_price_config(previous, source, *, price_version_id, legacy_single_names=None):
    """Pure replace-on-success transition; failure retains the identical object.

    ``previous`` is a configuration returned by a prior successful validation.
    An absent previous value stays absent after an invalid first load. Retention
    alone does not authorize stale/offline prices for a transaction.
    """
    if previous is not None and not isinstance(previous, ValidatedPriceConfig):
        raise TypeError("previous must be a validated configuration or None")
    validation = parse_price_config(source, price_version_id=price_version_id,
                                    legacy_single_names=legacy_single_names)
    return PriceConfigRefresh(validation.config if validation.status == "ok" else previous, validation)
