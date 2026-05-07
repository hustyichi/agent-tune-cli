#!/usr/bin/env python
from __future__ import annotations

import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--input-file", required=True)
args = parser.parse_args()
case = json.load(open(args.input_file))
query = case.get("inputs", {}).get("query", "")
if "no retrieval" in query:
    output = {
        "response": {"answer": "I cannot find that."},
        "debug_meta": {"route": "fallback", "retrieval_used": False, "retrieval_doc_count": 0, "tool_calls": [], "fallback_used": True, "error_code": "tool_not_called"},
    }
else:
    output = {
        "response": {"answer": "The pricing answer uses retrieved product pricing context."},
        "debug_meta": {"route": "knowledge_qa", "retrieval_used": True, "retrieval_doc_count": 2, "tool_calls": [{"name": "retriever.search", "latency_ms": 12}], "fallback_used": False, "error_code": ""},
    }
print(json.dumps(output, ensure_ascii=False))
