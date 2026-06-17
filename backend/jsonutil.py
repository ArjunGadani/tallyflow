"""Recover a JSON object from an LLM response that may be fenced or wrapped in
prose. Raises ValueError when nothing parses, so the caller can repair-retry."""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal


def jsonify(obj):
    """JSON-safe coercion: Decimal -> exact str (never float), UUID -> str,
    date/datetime -> ISO, recursing into dict/list. Shared by the API layer and
    the chat tools so money round-trips exactly everywhere."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonify(v) for v in obj]
    return obj


def parse_json_object(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("empty LLM response")
    s = text.strip()

    # Strip ```json ... ``` fences.
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Scan for the first balanced {...} object embedded in surrounding text.
    start = s.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no JSON object found in LLM response")
