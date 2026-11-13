"""Client for the local Ollama model that explains the weather facts (plan Task 5, D4).

``request_explanation(facts)`` sends the system prompt and the prepared facts to
Ollama's ``/api/chat``. Ollama's ``format`` option is given the output schema, and
the function returns the JSON object the model wrote. It does not validate that
object (``guidance.validation`` does) and never builds fallback text (the service
layer does).

Only ``facts.as_prompt_dict()`` is sent: the service, date, appointment time and
forecast values. No customer details are sent, and the model has no tools, so it
cannot fetch weather of its own.

Every failure raises ``LLMUnavailable`` with a ``kind``:

* ``unreachable``: no connection (refused, reset, bad base URL);
* ``timeout``: no answer within ``LLM_TIMEOUT`` seconds;
* ``http``: Ollama answered with an error status, e.g. 404 when the model is missing;
* ``malformed``: the reply, or the model's content, is not a usable JSON object.

The exception never carries server text, URLs or model output.
"""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from guidance.schema import OUTPUT_SCHEMA

# Part of the accepted-output cache key (Task 6): change it whenever the prompt changes.
PROMPT_VERSION = "v1"
MAX_RESPONSE_BYTES = 64 * 1024
OPTIONS = {"temperature": 0, "num_predict": 220}
KEEP_ALIVE = "30m"

SYSTEM_PROMPT = "\n".join((
    "You explain a weather forecast to a customer of a car-detailing shop.",
    "Return one JSON object with the fields rain_level, wind_level, temperature_level, "
    "confidence, outlook, summary, service_explanation and uncertainty_note.",
    "Rules:",
    "- The facts in the user message are the only source of weather information.",
    "- Copy rain_level, wind_level, temperature_level, confidence and outlook exactly "
    "as they appear in the facts.",
    "- Never write a number that is not in the facts.",
    "- Write at most 2 short sentences per text field, in plain customer language.",
    "- summary explains the weather conditions in the facts.",
    "- service_explanation must explain only the provided service_consideration, "
    "with no products, techniques or instructions.",
    "- Make no promises, and never suggest changing, moving or cancelling the booking.",
    "- When lead_days is 3 or more, uncertainty_note must say the forecast may change. "
    "Otherwise it may be empty.",
    "- peak_hourly_rain_probability_pct is the highest chance of rain for any single hour "
    "of the date, never the chance of rain all day. "
    'Call it "the highest hourly rain probability".',
    "- Use appointment_hour_rain_probability_pct only for the appointment hour, and only "
    "when it is present.",
))


class LLMUnavailable(Exception):
    """The local model gave no usable reply. ``kind`` says why."""

    KINDS = ("unreachable", "timeout", "http", "malformed")

    def __init__(self, kind: str):
        if kind not in self.KINDS:
            raise ValueError(f"Unknown LLMUnavailable kind: {kind!r}")
        super().__init__(f"Local AI model unavailable ({kind}).")
        self.kind = kind


def build_messages(facts) -> list[dict]:
    """The fixed system prompt, then the prepared facts as JSON."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(facts.as_prompt_dict())},
    ]


def request_explanation(facts) -> dict:
    """Return the model's JSON object, unvalidated, or raise ``LLMUnavailable``."""
    config = settings.GUIDANCE
    body = {
        "model": config["OLLAMA_MODEL"],
        "messages": build_messages(facts),
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "options": OPTIONS,
        "keep_alive": KEEP_ALIVE,
    }
    # The handlers are ordered: HTTPError is a URLError, and URLError and
    # TimeoutError are OSErrors. "from None" drops the original exception, whose
    # text can contain hosts or server output.
    try:
        request = Request(
            f"{config['OLLAMA_BASE_URL'].rstrip('/')}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=config["LLM_TIMEOUT"]) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError:
        raise LLMUnavailable("http") from None
    except URLError as exc:
        kind = "timeout" if isinstance(exc.reason, TimeoutError) else "unreachable"
        raise LLMUnavailable(kind) from None
    except TimeoutError:
        raise LLMUnavailable("timeout") from None
    except (OSError, ValueError):
        raise LLMUnavailable("unreachable") from None
    except HTTPException:
        raise LLMUnavailable("malformed") from None
    return _model_object(raw)


def _model_object(raw: bytes) -> dict:
    """The JSON object inside ``message.content`` of an Ollama chat reply."""
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LLMUnavailable("malformed")
    try:
        # json.loads raises TypeError when content is not a string (null, a number).
        output = json.loads(json.loads(raw)["message"]["content"])
    except (ValueError, KeyError, TypeError, RecursionError):
        raise LLMUnavailable("malformed") from None
    if not isinstance(output, dict):
        raise LLMUnavailable("malformed")
    return output
