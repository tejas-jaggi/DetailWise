# Task 10 prompt v1: review packet

*Prepared November 12, 2026 from the saved results of the prompt v1 baseline run. For an independent reviewer; no knowledge of the evaluation code is needed.*

## What you are reviewing

On the booking page, DetailWise can ask an AI model (Llama 3, run locally through Ollama) to explain a weather forecast for the customer's chosen service. Python computes every number and class (for example "rain: likely") and sends them to the model as facts. The model writes three short texts: a **summary**, a **service explanation** and an optional **uncertainty note**.

For Task 10, five fixed, made-up forecasts (cases A–E) were each sent to the model once. This packet shows the facts the model received, its exact reply, and what the automatic validator decided. Your job is to judge whether each reply is correct and appropriate for a customer.

## Three different kinds of check

| Check | What it is | Status |
|---|---|---|
| **Validator acceptance** | An automatic, rule-based check in the app: the classes were copied exactly, no number outside the facts, no listed advice words, required wording present. It does **not** check meaning. | Done: 5 of 5 accepted, 0 of 5 fell back |
| **AI-assisted preliminary review** | A first reading prepared with an AI assistant while assembling this packet. It is **not** a human review and decides nothing. | Done; shown under each case as "Preliminary note" |
| **Independent human review** | Your judgment, using the template under each case. | **Pending** |

Validator acceptance is **not** semantic accuracy: a reply can pass every rule and still be confusing, incomplete or misleading. Please judge each reply yourself rather than relying on the validator result or the preliminary note.

## Run details

| Item | Value |
|---|---|
| Run | One complete five-case run, November 12, 2026, 9:03 PM Central |
| Model | `llama3` resolved to `llama3:latest` (digest `365c0bd3c000`, 8.0B, Q4_0), Ollama 0.30.6 |
| Prompt | `v1`; temperature 0, at most 220 tokens, timeout 45 s |
| Validator | 5 of 5 accepted; 0 of 5 fell back |
| Latency | median 11,360 ms, maximum 18,230 ms |

## Terms used below

- **Highest hourly rain probability:** the highest chance of rain for any single hour of the date. It is **not** the chance of rain all day.
- **Appointment-hour rain probability:** the chance of rain in the hour of the appointment (given only when an appointment time is set).
- **Confidence:** `higher` when the date is less than 3 days ahead, `lower` otherwise. When it is `lower`, the uncertainty note must say the forecast may change.
- **Outlook:** Python's overall class: `favorable`, `concerns` (with the listed concerns), `weather_minor` (interior service: the weather matters less) or `incomplete` (some values are missing).
- **Service sentence:** a fixed sentence Python supplies for each kind of service. The model is told to explain only this sentence, with no products, techniques or instructions, and never to suggest changing the booking.

## How to review a case

1. Read the facts table first.
2. Read the model's reply as a customer would.
3. Mark each of the five checks **Pass** or **Fail**, with a short note for every Fail (quote the words that fail).
4. Answer the case questions, then give an overall Pass or Fail.

The five checks, for every case:

1. **Facts and classes:** the text agrees with the facts and Python's classes.
2. **Nothing unsupported:** no weather information or number that is not in the facts.
3. **No advice:** no products, techniques, instructions or booking advice (such as moving or cancelling).
4. **Service type:** interior, exterior and mixed services are described correctly.
5. **Uncertainty:** the uncertainty wording suits the confidence (and is not commentary about the reply itself).

## Case A: favorable exterior

**Intended behaviour:** No invented concern; the classes match Python's (favorable outlook).

**Facts sent to the model**

| Fact | Value |
|---|---|
| Service | Exterior Wash (exterior) |
| Date and lead time | 2026-11-17, 1 day(s) ahead ("today" is fixed at 2026-11-16) |
| Appointment time | 10:00 |
| High / low temperature | 72 / 52 °F |
| Highest hourly rain probability | 10% |
| Precipitation | 0.0 in |
| Max wind / gust | 8 / 14 mph |
| Appointment hour: temperature / wind / rain probability | 60 °F / 6 mph / 10% |
| Python's classes | rain low, wind light, temperature mild, confidence higher, outlook favorable |
| Concerns | none |
| Missing values | none |
| Service sentence supplied by Python | "An exterior wash is done outside, so rain on the day of your appointment can make the car dirty again sooner." |

**Model reply (exact, as saved)** · validator: **accepted** · latency 18,230 ms (first call; includes loading the model)

| Field | Reply |
|---|---|
| `rain_level` | low |
| `wind_level` | light |
| `temperature_level` | mild |
| `confidence` | higher |
| `outlook` | favorable |
| `summary` | The weather is expected to be mild with a low chance of rain and light winds. |
| `service_explanation` | Please note that an exterior wash done outside may make the car dirty again sooner if it rains on the day of your appointment. |
| `uncertainty_note` | *(empty)* |

**Preliminary note (AI-assisted, not a human review):** Minor. The service explanation adds a conditional rain caveat ("if it rains") although the outlook is favorable and rain is low. Note: the service sentence Python supplies for every exterior service mentions rain, and the prompt tells the model to explain only that sentence, so this may come from the design rather than from the model.

**Questions for the reviewer**

- Is the conditional rain caveat acceptable for a favorable forecast, or is it an unsupported concern? Is it a model problem or a problem with the fixed service sentence?

**Reviewer template**

| Check | Pass / Fail | Notes |
|---|---|---|
| 1. Facts and classes | | |
| 2. Nothing unsupported | | |
| 3. No advice | | |
| 4. Service type | | |
| 5. Uncertainty | | |
| Case questions above | | |
| **Overall** | | |

Reviewer: ______________ Date: ______________

## Case B: two different rain values

**Intended behaviour:** Keeps the highest hourly rain probability (70%) separate from the appointment-hour probability (10%); never calls either an all-day chance.

**Facts sent to the model**

| Fact | Value |
|---|---|
| Service | Exterior Wash (exterior) |
| Date and lead time | 2026-11-17, 1 day(s) ahead ("today" is fixed at 2026-11-16) |
| Appointment time | 10:00 |
| High / low temperature | 68 / 50 °F |
| Highest hourly rain probability | 70% |
| Precipitation | 0.12 in |
| Max wind / gust | 8 / 15 mph |
| Appointment hour: temperature / wind / rain probability | 56 °F / 6 mph / 10% |
| Python's classes | rain likely, wind light, temperature mild, confidence higher, outlook concerns |
| Concerns | rain |
| Missing values | none |
| Service sentence supplied by Python | "An exterior wash is done outside, so rain on the day of your appointment can make the car dirty again sooner." |

**Model reply (exact, as saved)** · validator: **accepted** · latency 11,716 ms

| Field | Reply |
|---|---|
| `rain_level` | likely |
| `wind_level` | light |
| `temperature_level` | mild |
| `confidence` | higher |
| `outlook` | concerns |
| `summary` | There is a high chance of rain on the day of your appointment, with a peak hourly rain probability of 70%. The temperature will be mild and the wind will be light. |
| `service_explanation` | Please note that an exterior wash done outside may not last as long if it rains. This might affect the cleanliness of your car. |
| `uncertainty_note` | *(empty)* |

**Preliminary note (AI-assisted, not a human review):** Reports the 70% peak hourly probability correctly, but omits the 10% appointment-hour probability. "A high chance of rain on the day of your appointment" may read as an all-day probability.

**Questions for the reviewer**

- Does the reply make clear that 70% is the highest chance for any single hour, not the chance at 10:00 AM and not the chance all day?
- Is leaving out the 10% appointment-hour probability a failure?
- Could a customer conclude that rain is likely at their appointment time?

**Reviewer template**

| Check | Pass / Fail | Notes |
|---|---|---|
| 1. Facts and classes | | |
| 2. Nothing unsupported | | |
| 3. No advice | | |
| 4. Service type | | |
| 5. Uncertainty | | |
| Case questions above | | |
| **Overall** | | |

Reviewer: ______________ Date: ______________

## Case C: interior with severe weather

**Intended behaviour:** Keeps the interior outlook; does not claim the weather will affect indoor work.

**Facts sent to the model**

| Fact | Value |
|---|---|
| Service | Interior Clean (interior) |
| Date and lead time | 2026-11-17, 1 day(s) ahead ("today" is fixed at 2026-11-16) |
| Appointment time | none (daily facts only) |
| High / low temperature | 85 / 65 °F |
| Highest hourly rain probability | 90% |
| Precipitation | 0.35 in |
| Max wind / gust | 32 / 41 mph |
| Python's classes | rain very likely, wind very windy, temperature warm, confidence higher, outlook weather_minor |
| Concerns | rain, wind |
| Missing values | none |
| Service sentence supplied by Python | "Interior cleaning happens inside the car, so the forecast matters less for this service." |

**Model reply (exact, as saved)** · validator: **accepted** · latency 11,135 ms

| Field | Reply |
|---|---|
| `rain_level` | very likely |
| `wind_level` | very windy |
| `temperature_level` | warm |
| `confidence` | higher |
| `outlook` | weather_minor |
| `summary` | There is a high chance of rain and strong winds on the scheduled date. The temperature will be warm. |
| `service_explanation` | The interior cleaning service happens inside the car, so the forecast matters less for this service. |
| `uncertainty_note` | Since it's only one day ahead, there's no uncertainty note needed. |

**Preliminary note (AI-assisted, not a human review):** The uncertainty note, which customers see, is commentary about why no note is needed ("there's no uncertainty note needed"). It should have been empty.

**Questions for the reviewer**

- Is the uncertainty note acceptable to show a customer, or should the field have been empty?
- Does the reply avoid claiming that the weather will affect indoor work?

**Reviewer template**

| Check | Pass / Fail | Notes |
|---|---|---|
| 1. Facts and classes | | |
| 2. Nothing unsupported | | |
| 3. No advice | | |
| 4. Service type | | |
| 5. Uncertainty | | |
| Case questions above | | |
| **Overall** | | |

Reviewer: ______________ Date: ______________

## Case D: mixed service, missing facts

**Intended behaviour:** Keeps the missing values unknown, invents no numbers, says the forecast may change.

**Facts sent to the model**

| Fact | Value |
|---|---|
| Service | Full Detail (mixed) |
| Date and lead time | 2026-11-23, 7 day(s) ahead ("today" is fixed at 2026-11-16) |
| Appointment time | none (daily facts only) |
| High / low temperature | 72 / not given °F |
| Highest hourly rain probability | not given |
| Precipitation | 0.0 in |
| Max wind / gust | 8 / 14 mph |
| Python's classes | rain unknown, wind light, temperature unknown, confidence lower, outlook incomplete |
| Concerns | none |
| Missing values | low temperature, peak hourly rain probability |
| Service sentence supplied by Python | "This service includes exterior work, so rain on the day of your appointment can make the exterior dirty again sooner. Weather matters less for the interior work." |

**Model reply (exact, as saved)** · validator: **accepted** · latency 11,360 ms

| Field | Reply |
|---|---|
| `rain_level` | unknown |
| `wind_level` | light |
| `temperature_level` | unknown |
| `confidence` | lower |
| `outlook` | incomplete |
| `summary` | The weather forecast is incomplete, but it's currently expected to be light and unknown. |
| `service_explanation` | As this service includes exterior work, rain on the day of your appointment may make the exterior dirty again sooner. Weather matters less for the interior work. |
| `uncertainty_note` | Since there are 7 lead days, the forecast may change. |

**Preliminary note (AI-assisted, not a human review):** The missing values stay unknown and no number is invented, but the summary is incoherent ("expected to be light and unknown") and the uncertainty note uses the internal term "lead days".

**Questions for the reviewer**

- Is the summary understandable to a customer?
- Does the reply make clear which values are missing (low temperature and rain probability)?
- Is "lead days" acceptable customer language?
- Is any number or weather condition invented?

**Reviewer template**

| Check | Pass / Fail | Notes |
|---|---|---|
| 1. Facts and classes | | |
| 2. Nothing unsupported | | |
| 3. No advice | | |
| 4. Service type | | |
| 5. Uncertainty | | |
| Case questions above | | |
| **Overall** | | |

Reviewer: ______________ Date: ______________

## Case E: exterior with two concerns

**Intended behaviour:** Mentions both the freezing and the wind concerns; gives no product, technique or rescheduling advice.

**Facts sent to the model**

| Fact | Value |
|---|---|
| Service | Exterior Wash (exterior) |
| Date and lead time | 2026-11-23, 7 day(s) ahead ("today" is fixed at 2026-11-16) |
| Appointment time | none (daily facts only) |
| High / low temperature | 45 / 30 °F |
| Highest hourly rain probability | 20% |
| Precipitation | 0.01 in |
| Max wind / gust | 22 / 31 mph |
| Python's classes | rain possible, wind windy, temperature freezing risk, confidence lower, outlook concerns |
| Concerns | wind, freezing |
| Missing values | none |
| Service sentence supplied by Python | "An exterior wash is done outside, so rain on the day of your appointment can make the car dirty again sooner." |

**Model reply (exact, as saved)** · validator: **accepted** · latency 11,106 ms

| Field | Reply |
|---|---|
| `rain_level` | possible |
| `wind_level` | windy |
| `temperature_level` | freezing risk |
| `confidence` | lower |
| `outlook` | concerns |
| `summary` | There is a possibility of rain and the temperature may be freezing, with windy conditions. This could affect your exterior wash appointment. |
| `service_explanation` | Please consider that rain on the day of your appointment can make the car dirty again sooner. |
| `uncertainty_note` | The forecast may change in the next few days. |

**Preliminary note (AI-assisted, not a human review):** The summary mentions wind and freezing, but the service explanation mentions only rain. Note: as in case A, the supplied service sentence mentions only rain, and the prompt limits the explanation to it.

**Questions for the reviewer**

- Are both concerns (wind and freezing risk) represented clearly enough?
- Is a service explanation that mentions only rain acceptable, given that the supplied service sentence mentions only rain?
- Does any wording suggest rescheduling or other advice?

**Reviewer template**

| Check | Pass / Fail | Notes |
|---|---|---|
| 1. Facts and classes | | |
| 2. Nothing unsupported | | |
| 3. No advice | | |
| 4. Service type | | |
| 5. Uncertainty | | |
| Case questions above | | |
| **Overall** | | |

Reviewer: ______________ Date: ______________

## After the review

Return the completed templates. The decisions will be recorded in [`task10_evaluation.md`](task10_evaluation.md) and in the `human_review` field of the saved results file, which stays out of Git. Until then, every `human_review` field is empty and the review is pending.

The cases contain no customer data; all forecasts are made up.
