from __future__ import annotations

from typing import Any


def run(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one case using the Python function contract.

    Agent-Eval passes the full case dict, including fields such as:
    - id: stable case identifier
    - inputs: user-defined prompt/request data
    - context: optional supporting data for the case
    - expected_execution / assertions / evaluation_policy: evaluation hints

    Return either a raw response object or a dict with response + debug_meta.
    """

    inputs = case.get("inputs", {})
    context = case.get("context", {})
    query = inputs.get("query", "")
    product = context.get("product", "pricing")

    if "no retrieval" in query:
        return {
            "response": {"answer": "I cannot find that."},
            "debug_meta": {
                "route": "fallback",
                "retrieval_used": False,
                "retrieval_doc_count": 0,
                "tool_calls": [],
                "fallback_used": True,
                "error_code": "tool_not_called",
            },
        }

    return {
        "response": {
            "answer": f"The {product} answer uses retrieved product pricing context."
        },
        "debug_meta": {
            "route": "knowledge_qa",
            "retrieval_used": True,
            "retrieval_doc_count": 2,
            "tool_calls": [{"name": "retriever.search", "latency_ms": 12}],
            "fallback_used": False,
            "error_code": "",
        },
    }
