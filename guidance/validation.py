"""Rule-based validation of the local model's JSON output (plan D4, D5).

``validate_output()`` returns the cleaned fields, or ``None`` with reason codes.
Valid JSON is never treated as correct on its own: every field is checked
against the Python facts.

The rules catch known classes of error (wrong classes, invented or swapped
numbers, misread rain probabilities, contradictions, certainty, advice,
off-topic text). They do not guarantee that accepted text is semantically
correct. Phrase lists are module-level tuples so they can be reviewed.

Matching is case-insensitive. Phrases match at the start of a word, so
"cover" also catches "covering"; unsupported weather conditions match whole
words.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from guidance.schema import ENUM_VALUES, FIELD_LIMITS, OUTPUT_FIELDS

TEXT_FIELDS = tuple(FIELD_LIMITS)
MARKUP_CHARACTERS = "<>{}`"

# --- Rain scope (D2, D5) ------------------------------------------------------
ALL_DAY_PHRASES = (
    "all day", "all-day", "throughout the day", "the whole day", "the entire day",
    "all morning", "all afternoon", "all evening", "continuous", "constant",
    "steady rain", "nonstop", "non-stop", "the chance of rain for the day",
    "daily chance of rain",
)
PEAK_QUALIFIERS = (
    "highest", "peak", "maximum", "max", "at least one hour", "single hour", "any hour",
    "most likely hour",
)
APPOINTMENT_QUALIFIERS = ("appointment", "that hour", "your time", "the hour you")
RAIN_WORDS = ("rain", "precipitation", "shower", "drizzle")

# --- Contradictions (D5) --------------------------------------------------------
RAIN_WET_PHRASES = ("rain is likely", "rain is expected", "heavy rain", "will rain")
RAIN_ALWAYS_WRONG_PHRASES = ("will rain", "rain is expected all day")
_RAIN = r"(?:rain|rainfall|showers?|drizzle|precipitation)"
# Claims that it will be dry. "Unlikely" counts only when it is about rain, so
# "Strong winds are unlikely" is not a rain claim. "No rain" followed by a data
# word ("no rain probability is available") states missing data, not dry weather.
RAIN_DRY_CLAIMS = (
    r"\bno\s+rain\b(?!\s+(?:probability|chance|data|forecast|information|values?|percentage))",
    rf"\b{_RAIN}\s+(?:is|are|seems|looks|appears)\s+(?:\w+\s+)?unlikely\b",
    rf"\b{_RAIN}\s+unlikely\b",
    r"\bunlikely\s+(?:that\s+)?(?:it\s+)?(?:will\s+)?(?:to\s+)?rain\b",
    r"\bdry\s+(?:days?|weather|conditions|skies)\b",
)
# With rain unknown, any statement about whether it will rain is unsupported.
UNKNOWN_RAIN_CLAIMS = (
    rf"\b{_RAIN}\s+(?:is|are|was|looks|seems|appears)\s+(?:\w+\s+){{0,2}}"
    r"(?:possible|likely|probable|expected|forecast|predicted)\b",
    rf"\b{_RAIN}\s+(?:may|might|could|can|will|would|should)\s+(?:\w+\s+)?"
    r"(?:occur|fall|happen|develop|arrive|start|begin|move\s+in"
    r"|be\s+(?:possible|likely|expected))\b",
    r"\b(?:may|might|could|will|would|should|going\s+to)\s+(?:\w+\s+)?rain\b",
    r"\b(?:rainy|wet\s+(?:days?|weather|conditions)|rain\s+showers)\b",
    r"\b(?:some|light|scattered|passing|isolated)\s+(?:rain|showers?|drizzle)\b",
    r"\bexpect(?:s|ed|ing)?\s+(?:\w+\s+)?(?:rain|showers?|drizzle)\b",
)
# "Chance of rain" is a claim unless that phrase is itself the subject of an
# unavailability statement: "The chance of rain [for this date] is not available."
# "Missing data" said elsewhere in the sentence ("A high chance of rain, but the
# probability is unavailable") does not excuse it, and nor does a qualifier
# between "the" and the phrase ("The high chance of rain is unknown").
_RAIN_ODDS = rf"(?:chances?|possibility|risk|likelihood|threat|odds)\s+of\s+{_RAIN}"
UNKNOWN_RAIN_MENTIONS = (rf"\b{_RAIN_ODDS}\b",)
UNAVAILABLE_RAIN_ODDS = (
    rf"\bthe\s+{_RAIN_ODDS}"
    r"(?:\s+(?:for|on|at)\s+(?:this|that|the|your)\s+(?:date|day|appointment|hour))?"
    r"\s+(?:is|are)\s+(?:currently\s+)?"
    r"(?:not\s+available|unavailable|not\s+known|unknown|missing|not\s+included)\b"
)
WIND_CALM_PHRASES = ("calm", "gentle", "light breeze")
WIND_STRONG_PHRASES = ("strong", "gusty", "very windy")
FREEZING_PHRASES = ("freezing", "icy")
WARM_PHRASES = ("warm", "hot")

# --- Certainty, advice and topic (D5) -------------------------------------------
CERTAINTY_PHRASES = (
    "guarantee", "definitely", "certainly", "for sure", "will not rain", "won't rain",
    "will stay dry", "no chance",
)
ADVICE_PHRASES = (
    "wax", "coating", "sealant", "ceramic", "polish", "cover", "tarp", "garage", "indoors",
    "umbrella", "apply", "spray", "make sure", "ensure", "you should", "we recommend",
    "recommend", "reschedule", "cancel", "another day", "another date",
)
OFF_TOPIC_PHRASES = ("price", "discount", "refund", "medical", "insurance", "as an ai")
# Weather the facts never contain (they hold rain probability, precipitation,
# temperature and wind only), so any mention is unsupported.
UNSUPPORTED_CONDITIONS = (
    "snow", "snowy", "snowfall", "sleet", "hail", "thunder", "thunderstorm", "thunderstorms",
    "lightning", "storm", "storms", "stormy", "tornado", "hurricane", "fog", "foggy", "mist",
    "misty", "sunny", "sunshine", "cloudy", "clouds", "overcast", "humid", "humidity",
)

# D5 uncertainty pattern, used exactly as planned.
UNCERTAINTY_PATTERN = re.compile(
    r"\b(?:may|can|could|might) change\b|\buncertain|\bcheck again\b"
    r"|\bcloser to your appointment\b",
    re.IGNORECASE,
)


def _starts(phrases):
    """Any phrase at the start of a word."""
    return re.compile(r"\b(?:" + "|".join(map(re.escape, phrases)) + ")", re.IGNORECASE)


def _words(words):
    """Any whole word."""
    return re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", re.IGNORECASE)


ALL_DAY = _starts(ALL_DAY_PHRASES)
PEAK_QUALIFIER = _starts(PEAK_QUALIFIERS)
RAIN_MENTION = _starts(RAIN_WORDS)
RAIN_WET = _starts(RAIN_WET_PHRASES)
RAIN_DRY = re.compile("|".join(RAIN_DRY_CLAIMS), re.IGNORECASE)
UNKNOWN_RAIN_CLAIM = re.compile("|".join(UNKNOWN_RAIN_CLAIMS), re.IGNORECASE)
UNKNOWN_RAIN_MENTION = re.compile("|".join(UNKNOWN_RAIN_MENTIONS), re.IGNORECASE)
UNAVAILABLE_RAIN_ODDS_STATEMENT = re.compile(UNAVAILABLE_RAIN_ODDS, re.IGNORECASE)
RAIN_ALWAYS_WRONG = _starts(RAIN_ALWAYS_WRONG_PHRASES)
WIND_CALM = _starts(WIND_CALM_PHRASES)
WIND_STRONG = _starts(WIND_STRONG_PHRASES)
FREEZING = _starts(FREEZING_PHRASES)
WARM = _starts(WARM_PHRASES)
CERTAINTY = _starts(CERTAINTY_PHRASES)
ADVICE = _starts(ADVICE_PHRASES)
OFF_TOPIC = _starts(OFF_TOPIC_PHRASES)
OFF_TOPIC_PATTERNS = (
    re.compile(r"https?://|\bwww\.", re.IGNORECASE),
    # Starts only at the beginning of a word and never backtracks (possessive ++),
    # so a long run of letters or digits is scanned in linear time.
    re.compile(r"(?<![\w.+-])[\w.+-]++@[\w-]++\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"\$"),
)
UNSUPPORTED_CONDITION = _words(UNSUPPORTED_CONDITIONS)
# An interior service whose result rain, wind or weather "will/could/may affect".
INTERIOR_EFFECT = re.compile(
    r"\b(?:rain|wind|weather)\w*[^.!?]{0,80}?\b(?:will|could|may|might|can|would)\s+"
    r"(?:\w+\s+)?(?:affect|ruin|damage|harm|spoil)",
    re.IGNORECASE,
)

# --- Numbers and units (D5) -----------------------------------------------------
# A complete number: digits joined by "." or "," and an optional exponent are one
# token ("1,060", "1e3"), so no fragment of it can match a fact value. A leading
# minus (hyphen or U+2212) is kept when it follows a space, "(" or "[" or starts
# the text; in "37-52" the hyphen joins a range and is not a sign.
_NUMBER = r"(?<![\d.,])(?:(?<![^\s(\[])[-\u2212](?=\d))?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?"
NUMBER = re.compile(_NUMBER)
_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    "sixty|seventy|eighty|ninety|hundred"
)
SPELLED_NUMBER = re.compile(
    rf"\b(?:{_NUMBER_WORDS})(?:[\s-]+(?:{_NUMBER_WORDS}|and))*\s*"
    r"(?:%|°|(?:per\s?cent|mph|miles?|degrees?|inch(?:es)?)\b)",
    re.IGNORECASE,
)
# A number directly followed by a unit. Units outside °F, mph, % and inch never
# match a fact value.
UNIT = re.compile(
    rf"({_NUMBER})\s*("
    r"%|\u2103|\u2109|°\s*c(?![a-z])|°\s*celsius|°\s*f(?![a-z])|°"
    r"|(?:per\s?cent|(?:degrees?|deg\.?)\s*(?:c|celsius|centigrade)|celsius|centigrade|c"
    r"|km/h|kph|kmh|knots?|m/s|millimet(?:er|re)s?|centimet(?:er|re)s?|mm|cm|mph"
    r"|miles per hour|miles?|(?:degrees?|deg\.?)\s*(?:f|fahrenheit)|degrees?|fahrenheit|f"
    r"|inch(?:es)?)(?![a-z])"
    r")",
    re.IGNORECASE,
)
UNIT_CATEGORIES = (
    (re.compile(r"%|per\s?cent", re.IGNORECASE), "rain", "%"),
    (re.compile(r"mph|miles per hour|miles?", re.IGNORECASE), "wind", "mph"),
    (re.compile(r"\u2109|°\s*f?|(?:degrees?|deg\.?)\s*(?:f|fahrenheit)|degrees?|fahrenheit|f",
                re.IGNORECASE),
     "temperature", "°F"),
    (re.compile(r"inch(?:es)?", re.IGNORECASE), "precipitation", "inch"),
)
# Every Celsius spelling is reported as "°c"; it never matches a fact value.
CELSIUS = re.compile(
    r"\u2103|°\s*c|°\s*celsius|(?:degrees?|deg\.?)\s*(?:c|celsius|centigrade)|celsius"
    r"|centigrade|c",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])(?<![AaPp]\.[Mm]\.)\s+")


def validate_output(data: object, facts) -> tuple[dict | None, list[str]]:
    """Return ``(clean_fields, [])`` or ``(None, reason_codes)``."""
    if (
        not isinstance(data, dict)
        or set(data) != set(OUTPUT_FIELDS)
        or not all(isinstance(data[field], str) for field in OUTPUT_FIELDS)
        or any(data[field] not in values for field, values in ENUM_VALUES.items())
    ):
        return None, ["schema"]

    reasons = [f"enum_mismatch:{field}" for field in ENUM_VALUES
               if data[field] != getattr(facts, field)]
    clean = {field: data[field] for field in ENUM_VALUES}
    for field in TEXT_FIELDS:
        text = clean_text(data[field])
        clean[field] = text
        if not text and field != "uncertainty_note":
            reasons.append(f"empty:{field}")
        if len(text) > FIELD_LIMITS[field]:
            reasons.append(f"length:{field}")
        if any(character in text for character in MARKUP_CHARACTERS):
            reasons.append(f"markup:{field}")
        reasons.extend(text_reasons(text, facts))
    if facts.lead_days >= 3 and not UNCERTAINTY_PATTERN.search(clean["uncertainty_note"]):
        reasons.append("missing_uncertainty")

    reasons = list(dict.fromkeys(reasons))
    return (None, reasons) if reasons else (clean, [])


def clean_text(text: str) -> str:
    """Whitespace collapsed to single spaces; control and format characters removed."""
    text = re.sub(r"\s+", " ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))
    return re.sub(r" {2,}", " ", text).strip()


def text_reasons(text: str, facts) -> list[str]:
    """Every content rule for one text field."""
    return number_reasons(text, facts) + phrase_reasons(text, facts)


def number_reasons(text: str, facts) -> list[str]:
    """Spelled numbers, unsupported numbers, unit binding and rain-percentage scope."""
    allowed = facts.allowed_numbers()
    reasons = []
    if SPELLED_NUMBER.search(text):
        reasons.append("spelled_number")
    for token in NUMBER.findall(text):
        if not _allowed(token, allowed["all"]):
            reasons.append(f"unsupported_number:{token}")
    rain_values = allowed["rain_peak"] | allowed["rain_appointment"]
    for number, unit in UNIT.findall(text):
        category, label = _unit_category(unit)
        pool = rain_values if category == "rain" else allowed.get(category, set())
        if not _allowed(number, pool):
            reasons.append(f"unit_mismatch:{number}{label}")
    if _rain_percent_misused(text, facts, allowed):
        reasons.append("rain_scope")
    return reasons


def phrase_reasons(text: str, facts) -> list[str]:
    """All-day rain wording, contradictions, certainty, advice and topic."""
    text = text.replace("\u2019", "'")
    reasons = []
    if any(RAIN_MENTION.search(s) and ALL_DAY.search(s) for s in _sentences(text)):
        reasons.append("rain_scope")

    rain = facts.rain_level
    if (
        RAIN_ALWAYS_WRONG.search(text)
        or (rain in ("low", "unknown") and RAIN_WET.search(text))
        or (rain in ("likely", "very likely", "unknown") and RAIN_DRY.search(text))
        or (rain == "unknown" and _claims_rain(text))
    ):
        reasons.append("contradiction:rain")
    wind = facts.wind_level
    if (
        (wind in ("windy", "very windy", "unknown") and WIND_CALM.search(text))
        or (wind in ("light", "unknown") and WIND_STRONG.search(text))
    ):
        reasons.append("contradiction:wind")
    temperature = facts.temperature_level
    if (
        (temperature != "freezing risk" and FREEZING.search(text))
        or (temperature != "warm" and WARM.search(text))
    ):
        reasons.append("contradiction:temperature")

    if CERTAINTY.search(text):
        reasons.append("certainty")
    if ADVICE.search(text):
        reasons.append("advice")
    if facts.weather_sensitivity == "interior" and INTERIOR_EFFECT.search(text):
        reasons.append("service_contradiction")
    if OFF_TOPIC.search(text) or any(p.search(text) for p in OFF_TOPIC_PATTERNS):
        reasons.append("off_topic")
    if UNSUPPORTED_CONDITION.search(text):
        reasons.append("unsupported_condition")
    return reasons


def _claims_rain(text: str) -> bool:
    """A statement about whether it will rain, other than saying the value is unavailable.

    Each "chance of rain" mention is judged on its own: only a mention that is
    itself declared unavailable is removed, so any other mention still counts.
    """
    for sentence in _sentences(text):
        if UNKNOWN_RAIN_CLAIM.search(sentence):
            return True
        if UNKNOWN_RAIN_MENTION.search(UNAVAILABLE_RAIN_ODDS_STATEMENT.sub(" ", sentence)):
            return True
    return False


def _rain_percent_misused(text: str, facts, allowed: dict) -> bool:
    """A rain % must sit in a sentence that names which rain probability it is."""
    peak, hour = allowed["rain_peak"], allowed["rain_appointment"]
    has_hour_value = facts.appt_rain_chance_pct is not None
    appointment = _appointment_qualifier(facts)
    for sentence in _sentences(text):
        percents = [n for n, unit in UNIT.findall(sentence)
                    if _unit_category(unit)[0] == "rain"]
        if not percents:
            continue
        peak_named = bool(PEAK_QUALIFIER.search(sentence))
        hour_named = bool(appointment.search(sentence))
        for number in percents:
            is_peak, is_hour = _allowed(number, peak), _allowed(number, hour)
            if hour_named and not has_hour_value:
                return True
            if is_peak and is_hour:
                if not (peak_named or hour_named):
                    return True
            elif is_peak and not peak_named:
                return True
            elif is_hour and not hour_named:
                return True
    return False


def _appointment_qualifier(facts):
    patterns = [r"\b(?:" + "|".join(map(re.escape, APPOINTMENT_QUALIFIERS)) + ")"]
    if facts.time is not None:
        hour, minute = facts.time.hour, facts.time.minute
        patterns.append(rf"\b0?{hour}:{minute:02d}\b")
        patterns.append(rf"\b{hour % 12 or 12}(?::{minute:02d})?\s*[ap]\.?m\b")
    return re.compile("|".join(patterns), re.IGNORECASE)


def _unit_category(unit: str) -> tuple[str | None, str]:
    for pattern, category, label in UNIT_CATEGORIES:
        if pattern.fullmatch(unit):
            return category, label
    if CELSIUS.fullmatch(unit):
        return None, "°c"
    return None, re.sub(r"\s+", "", unit.lower())


def _allowed(token: str, numbers: set[str]) -> bool:
    """The token, sign included, is one of the numbers.

    Plain decimals also match in normalised form ("60.0" is "60"). A token with a
    comma or an exponent must match exactly, so "1,060" and "6e1" never pass.
    """
    token = token.replace("\u2212", "-")
    if token in numbers:
        return True
    if any(character in token for character in ",eE"):
        return False
    try:
        return format(Decimal(token).normalize(), "f") in numbers
    except InvalidOperation:
        return False


def _sentences(text: str) -> list[str]:
    return SENTENCE_BREAK.split(text)
