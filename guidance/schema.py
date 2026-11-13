"""The JSON object the local model must return (plan D4).

``OUTPUT_SCHEMA`` is passed to Ollama's ``format`` option. Ollama's constrained
output is not trusted: ``guidance.validation`` checks every field again.
"""

from guidance import classify

# Classification fields: the model copies the values computed by Python.
ENUM_VALUES = {
    "rain_level": classify.RAIN_LEVELS,
    "wind_level": classify.WIND_LEVELS,
    "temperature_level": classify.TEMPERATURE_LEVELS,
    "confidence": classify.CONFIDENCE_LEVELS,
    "outlook": classify.OUTLOOKS,
}
# Free-text fields and their maximum lengths in characters.
FIELD_LIMITS = {"summary": 280, "service_explanation": 280, "uncertainty_note": 200}

OUTPUT_FIELDS = tuple(ENUM_VALUES) + tuple(FIELD_LIMITS)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        **{field: {"type": "string", "enum": list(values)}
           for field, values in ENUM_VALUES.items()},
        **{field: {"type": "string", "maxLength": limit}
           for field, limit in FIELD_LIMITS.items()},
    },
    "required": list(OUTPUT_FIELDS),
    "additionalProperties": False,
}
