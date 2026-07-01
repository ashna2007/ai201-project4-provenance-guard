# Provenance Guard Planning

## Project Overview

Provenance Guard is a backend system that helps creative platforms classify whether submitted text is likely AI-generated, likely human-written, or uncertain. The system does not treat detection as perfect. It uses multiple signals, returns a confidence score, shows a transparency label, logs every decision, and gives creators a way to appeal.

## Architecture


**Submission Flow:**

POST /submit
  |
  v
Validate text + creator_id
  |
  v
Signal 1: LLM classification using Groq
  |
  v
Signal 2: Stylometric heuristics
  |
  v
Confidence scoring
  |
  v
Transparency label generation
  |
  v
Audit log entry
  |
  v
JSON response to platform

Appeal Flow:

POST /appeal
  |
  v
Validate content_id + creator_reasoning
  |
  v
Find original decision
  |
  v
Update status to under_review
  |
  v
Write appeal entry to audit log
  |
  v
JSON confirmation response


A submitted text enters through POST /submit, where the API validates the text and creator ID. The text is evaluated by two independent signals: an LLM-based classifier and a stylometric heuristic classifier. The system combines those scores into one confidence score, chooses a transparency label, stores the decision in an audit log, and returns the result.

If a creator disagrees with the classification, they can submit an appeal through POST /appeal. The system records the creator's reasoning, updates the content status to under_review, and logs the appeal alongside the original decision.

# Detection Signals

## Signal 1: LLM Classification

The first signal uses Groq with llama-3.3-70b-versatile to judge whether a text appears AI-generated or human-written.

**It captures:**

- overall tone
- semantic flow
- generic phrasing
- overly polished or template-like structure
- signs of natural personal voice

*Output:*

- a score from 0.0 to 1.0
- 1.0 means strongly AI-like
- 0.0 means strongly human-like

**Blind spots:**

- polished human writing may look AI-generated
- edited AI writing may look human
- short texts may not provide enough evidence
- personal or creative writing can be difficult for an LLM to judge fairly

## Signal 2: Stylometric Heuristics

The second signal uses measurable writing statistics. It checks sentence length variation, vocabulary diversity, punctuation density, and casual markers.

**It captures:**

- whether sentence lengths are too uniform
- whether vocabulary is repetitive
- whether punctuation and style feel natural or mechanical
- whether the writing has informal human markers

**Output:**

- a score from 0.0 to 1.0
- higher means more AI-like
- lower means more human-like

**Blind spots:**

- formal academic human writing may look AI-like
- poems or short creative writing may confuse the metrics
- non-native English writing may be misread as unusual or AI-like
- edited AI text may contain enough human variation to avoid detection
- Confidence Scoring

The system combines both signal scores into one AI-likelihood score.

**Formula:**

--> combined_score = (0.65 * llm_score) + (0.35 * stylometric_score)

I weight the LLM signal more because it can judge meaning, tone, and style more holistically. I still include the stylometric score because it provides an independent structural signal.

**Thresholds:**

- 0.75 - 1.00: likely_ai
- 0.40 - 0.74: uncertain
- 0.00 - 0.39: likely_human

A score around 0.50 or 0.60 means the system does not have enough confidence to make a strong claim. Because false positives can harm human creators, the system uses a wide uncertain range instead of forcing a binary decision.

# Transparency Label Design

**High-confidence AI label:**

"This work appears likely to be AI-generated. Our system found strong signals of automated writing, but this decision is not final and the creator may appeal."

**High-confidence human label:**

"This work appears likely to be human-written. Our system found stronger signs of original human authorship than automated generation."

**Uncertain label:**

"We are not confident enough to label this work as AI-generated or human-written. The writing has mixed signals, so readers should treat the attribution as uncertain."

**Appeals Workflow**

Any creator with a content_id can submit an appeal.

*The appeal endpoint accepts:*

1. content_id
2. creator_reasoning

*When an appeal is received, the system:*

- checks that the content ID exists
- records the creator's explanation
- updates the content status to under_review
- writes the appeal to the audit log
- returns a confirmation response

*A human reviewer would see:*

1. original text
2. original attribution
3. confidence score
4. individual signal scores
5. creator reasoning
6. current status

**Automated re-classification is not required.**

API Surface

```
POST /submit

Input:

{
  "text": "submitted creative text",
  "creator_id": "creator123"
}

Output:

{
  "content_id": "unique-id",
  "attribution": "likely_ai / likely_human / uncertain",
  "confidence": 0.82,
  "label": "label text",
  "status": "classified"
}
POST /appeal

Input:

{
  "content_id": "unique-id",
  "creator_reasoning": "I wrote this myself..."
}

Output:

{
  "message": "Appeal received",
  "content_id": "unique-id",
  "status": "under_review"
}
GET /log

Output:

{
  "entries": []
}
``` 


# Anticipated Edge Cases
- A poem with repeated phrases and simple vocabulary may be wrongly scored as AI-like because  stylometric heuristics may treat repetition as mechanical.
- A formal essay written by a human may be scored as AI-like because polished academic writing can have uniform structure and low casual variation.
- A very short text may not contain enough evidence for either signal to classify it reliably.
- A non-native English writer may use sentence patterns that differ from the training assumptions of the LLM or the heuristic rules.
- Rate Limiting Plan

**The /submit endpoint will use this rate limit:**

--> 10 submissions per minute and 100 submissions per day

**Reasoning:**

A normal creator on a writing platform would not usually submit more than 10 pieces of writing per minute. The daily limit still allows regular testing and realistic use, but it helps block automated abuse or scripts flooding the system.

*Audit Log Plan*

--> Every classification decision will be saved as a structured JSON entry.

*Each submission log entry should include:*

- timestamp
- content_id
- creator_id
- attribution
- confidence score
- LLM signal score
- stylometric signal score
- transparency label
- status

**Each appeal log entry should include:**

- timestamp
- content_id
- creator_reasoning
- status set to under_review
- AI Tool Plan
- M3: Submission Endpoint and First Signal

**I will provide the AI tool with the architecture section and the LLM signal description. I will ask it to generate a Flask app skeleton, a POST /submit route, and a Groq-based scoring function.**

**I will verify it by running the Flask app and testing the route with curl before adding the second signal.**

# M4: Second Signal and Confidence Scoring

I will provide the AI tool with the detection signals section, confidence scoring formula, thresholds, and architecture diagram. I will ask it to generate the stylometric heuristic function and combined scoring logic.

I will verify it by testing four inputs: clearly AI-like, clearly human-like, formal human writing, and borderline edited writing.

# M5: Production Layer

I will provide the AI tool with the label variants, appeals workflow, and API surface. I will ask it to generate the label function, POST /appeal, GET /log, audit logging, and Flask-Limiter setup.

I will verify it by checking that all three labels can appear, appeals update status to under_review, and rate limiting returns 429.