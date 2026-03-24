import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from batch_response_parser import RetryableBatchRecordError, extract_tool_arguments


def test_extract_tool_arguments_parses_forced_tool_call():
    record = {
        "response": {
            "request_id": "req_ok",
            "body": {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "arguments": '{"directors": [{"name": "Ada Lovelace"}]}'
                                    }
                                }
                            ]
                        },
                    }
                ]
            },
        }
    }

    assert extract_tool_arguments(record) == {"directors": [{"name": "Ada Lovelace"}]}


def test_extract_tool_arguments_flags_length_truncation_without_tool_call():
    record = {
        "response": {
            "request_id": "req_truncated",
            "body": {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "annotations": [],
                        },
                    }
                ]
            },
        }
    }

    try:
        extract_tool_arguments(record)
    except RetryableBatchRecordError as exc:
        assert exc.request_id == "req_truncated"
        assert exc.finish_reason == "length"
        assert "token limit" in exc.reason
    else:
        raise AssertionError("Expected truncated response without tool calls to be retryable")


def test_extract_tool_arguments_flags_malformed_tool_json():
    record = {
        "response": {
            "request_id": "req_bad_json",
            "body": {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "arguments": '{"directors": [}'
                                    }
                                }
                            ]
                        },
                    }
                ]
            },
        }
    }

    try:
        extract_tool_arguments(record)
    except RetryableBatchRecordError as exc:
        assert exc.request_id == "req_bad_json"
        assert "malformed tool arguments" in exc.reason
    else:
        raise AssertionError("Expected malformed tool arguments to be retryable")
