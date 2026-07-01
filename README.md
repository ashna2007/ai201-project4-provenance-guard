
# PROVENANCE GUARD

Provenance Guard is a Flask-based backend system that helps creative platforms determine whether submitted text is likely AI-generated, likely human-written, or uncertain. Rather than forcing a binary decision, the system combines multiple detection signals into a confidence score, generates a transparent label for readers, records every decision in an audit log, and allows creators to appeal classifications.

---

Demo Video Link: https://drive.google.com/file/d/1W-h9eq2tbuwY_mICq_jmnbj6WGwE6J8h/view?usp=sharing 

---

# Features

- Multi-signal AI content classification
- Confidence scoring with uncertainty
- Three transparency label variants
- Appeals workflow
- Rate limiting using Flask-Limiter
- Structured audit logging
- REST API built with Flask

---

# Architecture Overview

When a creator submits text through the `POST /submit` endpoint, the system first validates the request. The submission is analyzed using two independent detection signals:

1. A Groq LLM classifier
2. Stylometric heuristics

The outputs from both signals are combined into a single confidence score. Based on this score, the system determines an attribution result (`likely_ai`, `likely_human`, or `uncertain`) and generates a transparency label. The complete decision is stored in the audit log before being returned as a JSON response.

If a creator disagrees with the classification, they may submit an appeal through `POST /appeal`. The appeal records the creator's reasoning, updates the submission status to `under_review`, and stores the appeal alongside the original classification in the audit log.

---

# Detection Signals

## Signal 1: LLM Classification

The first signal uses the Groq API with the `llama-3.3-70b-versatile` model to analyze the overall writing style.

This signal evaluates:

- semantic coherence
- writing style
- tone
- generic phrasing
- natural human voice

### Strengths

- understands overall writing quality
- recognizes common AI writing patterns

### Limitations

- highly polished human writing may appear AI-generated
- edited AI writing may appear human
- short passages provide less evidence

---

## Signal 2: Stylometric Heuristics

The second signal analyzes measurable writing characteristics using Python.

Metrics include:

- sentence length variation
- vocabulary diversity (type-token ratio)
- punctuation density
- casual writing markers

### Strengths

- independent from the LLM
- fast to compute
- measures structural properties of writing

### Limitations

- formal essays may resemble AI writing
- poems and creative writing may confuse heuristics
- non-native English writing may produce unusual statistics

---

# Confidence Scoring

The system combines both signals into a single confidence score using:

```text
combined_score =
(0.65 × llm_score)
+
(0.35 × stylometric_score)
```

Confidence thresholds:

| Score | Attribution |
|-------:|-------------|
| 0.75 – 1.00 | Likely AI |
| 0.40 – 0.74 | Uncertain |
| 0.00 – 0.39 | Likely Human |

The uncertain range is intentionally wide because falsely labeling a human creator as AI-generated is considered more harmful than failing to detect AI-generated writing.

---

# Example Results

## Example 1 — High Confidence AI

| Field | Value |
|------|------|
| Attribution | likely_ai |
| Confidence | **0.8285** |
| LLM Score | 0.9000 |
| Stylometric Score | 0.6957 |

---

## Example 2 — High Confidence Human

| Field | Value |
|------|------|
| Attribution | likely_human |
| Confidence | **0.1331** |
| LLM Score | 0.1000 |
| Stylometric Score | 0.1944 |

---

## Example 3 — Uncertain

| Field | Value |
|------|------|
| Attribution | uncertain |
| Confidence | **0.4538** |
| LLM Score | 0.4000 |
| Stylometric Score | 0.5538 |

These examples demonstrate that the system produces meaningfully different confidence scores rather than always returning a binary result.

---

# Transparency Labels

## High Confidence AI

> This work appears likely to be AI-generated. Our system found strong signals of automated writing, but this decision is not final and the creator may appeal.

---

## High Confidence Human

> This work appears likely to be human-written. Our system found stronger signs of original human authorship than automated generation.

---

## Uncertain

> We are not confident enough to label this work as AI-generated or human-written. The writing has mixed signals, so readers should treat the attribution as uncertain.

---

# API Endpoints

## POST /submit

Accepts:

```json
{
  "text": "...",
  "creator_id": "..."
}
```

Returns:

- content_id
- attribution
- confidence
- llm_score
- stylometric_score
- transparency label
- status

---

## POST /appeal

Accepts:

```json
{
  "content_id": "...",
  "creator_reasoning": "..."
}
```

Updates the submission status to:

```text
under_review
```

and records the appeal in the audit log.

---

## GET /log

Returns all structured audit log entries.

---

# Appeals Workflow

Creators who believe their work has been misclassified can submit an appeal using the content ID returned by `/submit`.

Each appeal:

- records the creator's reasoning
- changes the submission status to `under_review`
- preserves the original classification
- records the appeal in the audit log

---

# Audit Log

Each submission stores:

- timestamp
- content ID
- creator ID
- attribution result
- confidence score
- LLM score
- stylometric score
- transparency label
- status

Appeals additionally store:

- creator reasoning
- updated status (`under_review`)

---

# Rate Limiting

The submission endpoint is protected using Flask-Limiter.

Limit:

```text
10 submissions per minute
100 submissions per day
```

These limits allow normal creator activity while preventing automated abuse or flooding attacks.

### Test Output

```
200
200
200
200
200
200
200
200
200
200
429
429
```

The first ten requests succeeded while the final two exceeded the configured limit, demonstrating that rate limiting functions correctly.

---

# Testing

The backend was manually tested using `curl`.

The following functionality was verified:

- successful submission
- AI classification
- human classification
- uncertain classification
- appeal submission
- audit logging
- rate limiting

---

# Known Limitations

The system is not intended to perfectly identify AI-generated writing.

Potential failure cases include:

- highly polished human writing
- edited AI-generated text
- poetry
- very short submissions
- non-native English writing
- unusual creative writing styles

Future improvements could include additional detection signals, larger evaluation datasets, and model calibration using real-world writing samples.

---

# Spec Reflection

Writing the planning document before implementation helped define the architecture, confidence thresholds, API endpoints, and transparency labels before coding. This made implementation more organized and reduced redesign later in development.

One implementation difference from the original planning stage was adjusting and refining heuristic calculations after testing. Testing revealed that some inputs required threshold tuning to better represent uncertainty.

---

# AI Usage

AI tools were used throughout development as implementation assistants.

### Instance 1

AI generated the initial Flask application structure, including route skeletons and project organization.

After generation, the code was reviewed and modified to match the project requirements and API contract.

### Instance 2

AI assisted with implementing confidence scoring, audit logging, and endpoint structure.

The generated code was revised to match the project's confidence thresholds, transparency labels, and audit logging requirements.

---

# Technologies Used

- Python
- Flask
- Flask-Limiter
- Groq API
- python-dotenv
- JSON audit logging

---

# Running the Project

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```text
GROQ_API_KEY=your_api_key_here
```

Run the application:

```bash
python app.py
```

The server will start on:

```
http://localhost:5001
```

---

# Future Improvements

Potential future enhancements include:

- additional detection signals
- ensemble scoring
- analytics dashboard
- provenance certificates
- multi-modal support
- persistent database storage
- authentication for protected endpoints
