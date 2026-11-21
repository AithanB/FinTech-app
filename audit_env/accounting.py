"""Public accounting rules: directional FX, one rounding, local period membership."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from zoneinfo import ZoneInfo

from .schemas import CURRENCY_EXPONENTS, aware_timestamp, positive_rate


def convert_minor(amount_minor: int, source: str, target: str, rate: Decimal | str) -> int:
    """Convert source minor -> source major -> target major -> target minor once."""
    if type(amount_minor) is not int or amount_minor < 0:
        raise ValueError("amount must be nonnegative integer minor units")
    rate = positive_rate(rate)
    # Do not inherit a caller's decimal precision or round intermediate amounts.
    with localcontext() as context:
        context.prec = max(34, len(str(amount_minor)) + len(rate.as_tuple().digits) + abs(rate.adjusted()) + 10)
        result = Decimal(amount_minor).scaleb(-CURRENCY_EXPONENTS[source]) * rate
        result = result.scaleb(CURRENCY_EXPONENTS[target])
        return int(result.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def local_date(timestamp: datetime, timezone: str):
    return aware_timestamp(timestamp).astimezone(ZoneInfo(timezone)).date()


def in_period(timestamp: datetime, manifest) -> bool:
    zone = ZoneInfo(manifest.timezone)
    local = aware_timestamp(timestamp).astimezone(zone)
    return manifest.period_start.astimezone(zone) <= local < manifest.period_end.astimezone(zone)


def applicable_fx(episode, currency: str, timestamp: datetime):
    """Identity conversion needs no FX row; missing directional rates invalidate data."""
    if currency == episode.manifest.base_currency:
        return None
    date = local_date(timestamp, episode.manifest.timezone)
    matches = [r for r in episode.fx if r.date == date and r.source_currency == currency
               and r.target_currency == episode.manifest.base_currency]
    if len(matches) != 1:
        raise ValueError("missing or ambiguous required FX rate")
    return matches[0]


def base_amount(episode, amount_minor: int, currency: str, timestamp: datetime) -> int:
    fx = applicable_fx(episode, currency, timestamp)
    return convert_minor(amount_minor, currency, episode.manifest.base_currency, fx.rate if fx else "1")
