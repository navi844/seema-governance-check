"""Sampled model-graded (LLM-as-judge) evaluation of SAR narratives against
the evidence actually gathered. Inherited base (M5)."""

import os
import random
import re
from collections import deque

from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

from src.core.metrics import record_eval_score

ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)

SAMPLE_RATE = float(os.environ.get("NIYANTRAN_EVAL_SAMPLE_RATE", "0.3"))
PASS_THRESHOLD = 4

JUDGE_SYSTEM_PROMPT = """You are grading a SAR narrative against the
evidence that was actually gathered for the investigation. Score 1-5: does
the narrative accurately reflect the typology findings and watchlist hits
present in the evidence, with no fabricated or missing findings? Respond
in exactly this format:
SCORE: <1-5>
REASON: <one sentence>
"""

_RECENT_JUDGED: deque = deque(maxlen=50)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def _parse_judge_reply(text: str) -> tuple[int, str]:
    score_match = re.search(r"SCORE:\s*(\d)", text)
    reason_match = re.search(r"REASON:\s*(.+)", text)
    score = int(score_match.group(1)) if score_match else 0
    reason = reason_match.group(1).strip() if reason_match else "(no reason parsed)"
    return score, reason


def maybe_grade(gathered_evidence: dict, sar_narrative: str) -> dict | None:
    if random.random() > SAMPLE_RATE:
        return None
    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Evidence: {gathered_evidence}\n\nSAR narrative: {sar_narrative}"},
        ],
    )
    score, reason = _parse_judge_reply(response.choices[0].message.content or "")
    verdict = "pass" if score >= PASS_THRESHOLD else "fail"
    entry = {"score": score, "reason": reason, "verdict": verdict}
    _RECENT_JUDGED.append(entry)
    record_eval_score(score)
    return entry


def recent_judged() -> list[dict]:
    return list(_RECENT_JUDGED)


def rolling_average_score() -> float | None:
    if not _RECENT_JUDGED:
        return None
    return round(sum(e["score"] for e in _RECENT_JUDGED) / len(_RECENT_JUDGED), 2)
