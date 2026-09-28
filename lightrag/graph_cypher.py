"""Validation helpers for the developer-facing, read-only Cypher explorer."""

from __future__ import annotations

import re


MAX_CYPHER_QUERY_LENGTH = 8_000
MAX_CYPHER_RESULT_ROWS = 200
_INTERNAL_LIMIT_PARAMETER = "__lightrag_cypher_limit"

_BLOCKED_KEYWORDS = (
    "ALTER",
    "CALL",
    "CONSTRAINT",
    "CREATE",
    "DATABASE",
    "DBMS",
    "DELETE",
    "DENY",
    "DETACH",
    "DROP",
    "FOREACH",
    "GRANT",
    "INDEX",
    "LOAD",
    "MERGE",
    "NODETACH",
    "REMOVE",
    "RENAME",
    "REVOKE",
    "SET",
    "SHOW",
    "START",
    "STOP",
    "TERMINATE",
    "UNION",
    "USE",
    "YIELD",
)


class ReadOnlyCypherError(ValueError):
    """Raised when a query exceeds the Cypher explorer's read-only contract."""


def _strip_literals_and_comments(query: str) -> str:
    """Return query syntax while replacing comments and quoted values with spaces.

    Keyword checks must ignore strings such as ``WHERE n.name = 'create'`` and
    comments. This is deliberately a small lexer, not a Cypher parser.
    """

    result: list[str] = []
    index = 0
    state = "code"

    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""

        if state == "code":
            if char == "/" and next_char == "/":
                result.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and next_char == "*":
                result.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char == "'":
                result.append(" ")
                index += 1
                state = "single_quote"
                continue
            if char == '"':
                result.append(" ")
                index += 1
                state = "double_quote"
                continue
            if char == "`":
                result.append(" ")
                index += 1
                state = "backtick"
                continue
            result.append(char)
            index += 1
            continue

        if state == "line_comment":
            result.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "code"
            continue

        if state == "block_comment":
            result.append(" ")
            if char == "*" and next_char == "/":
                result.append(" ")
                index += 2
                state = "code"
            else:
                index += 1
            continue

        quote = {"single_quote": "'", "double_quote": '"', "backtick": "`"}[state]
        result.append(" ")
        if char == "\\" and state != "backtick" and next_char:
            result.append(" ")
            index += 2
            continue
        if char == quote:
            if next_char == quote:
                result.append(" ")
                index += 2
                continue
            state = "code"
        index += 1

    return "".join(result)


def validate_read_only_cypher(query: str, max_records: int) -> str:
    """Validate and bound a Cypher query for the graph explorer.

    Only ``MATCH`` / ``OPTIONAL MATCH`` queries with a ``RETURN`` clause are
    accepted. The result limit is capped even when the caller omits ``LIMIT``.
    """

    if not isinstance(query, str) or not query.strip():
        raise ReadOnlyCypherError("Cypher query must not be empty.")
    if len(query) > MAX_CYPHER_QUERY_LENGTH:
        raise ReadOnlyCypherError(
            f"Cypher query exceeds the {MAX_CYPHER_QUERY_LENGTH}-character limit."
        )
    if isinstance(max_records, bool) or not isinstance(max_records, int):
        raise ReadOnlyCypherError("max_records must be an integer.")
    if not 1 <= max_records <= MAX_CYPHER_RESULT_ROWS:
        raise ReadOnlyCypherError(
            f"max_records must be between 1 and {MAX_CYPHER_RESULT_ROWS}."
        )

    syntax = _strip_literals_and_comments(query)
    normalized = re.sub(r"\s+", " ", syntax).strip()

    if ";" in normalized:
        raise ReadOnlyCypherError("Only one Cypher statement is allowed.")
    if not re.match(r"^(?:OPTIONAL\s+MATCH|MATCH)\b", normalized, re.IGNORECASE):
        raise ReadOnlyCypherError("Cypher explorer queries must start with MATCH or OPTIONAL MATCH.")
    if not re.search(r"\bRETURN\b", normalized, re.IGNORECASE):
        raise ReadOnlyCypherError("Cypher explorer queries must include a RETURN clause.")

    for keyword in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", normalized, re.IGNORECASE):
            raise ReadOnlyCypherError(
                f"'{keyword}' is not allowed in the read-only Cypher explorer."
            )

    limit_match = re.search(r"\bLIMIT\s+([^\s]+)", normalized, re.IGNORECASE)
    if limit_match:
        try:
            requested_limit = int(limit_match.group(1))
        except ValueError as exc:
            raise ReadOnlyCypherError(
                "Cypher explorer LIMIT must be a literal integer."
            ) from exc
        if not 1 <= requested_limit <= max_records:
            raise ReadOnlyCypherError(
                f"Cypher explorer LIMIT must be between 1 and {max_records}."
            )
        return query.strip()

    return f"{query.rstrip()}\nLIMIT ${_INTERNAL_LIMIT_PARAMETER}"


def cypher_explorer_limit_parameter_name() -> str:
    """Expose the reserved limit parameter without duplicating its literal."""

    return _INTERNAL_LIMIT_PARAMETER
