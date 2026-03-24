#!/usr/bin/env python3

import json


class RetryableBatchRecordError(Exception):
    def __init__(self, reason, *, request_id=None, finish_reason=None):
        super().__init__(reason)
        self.reason = reason
        self.request_id = request_id
        self.finish_reason = finish_reason


def extract_tool_arguments(record):
    response = record.get("response")
    if not isinstance(response, dict):
        raise RetryableBatchRecordError("batch record is missing a response object")

    request_id = response.get("request_id")
    body = response.get("body")
    if not isinstance(body, dict):
        raise RetryableBatchRecordError(
            "batch record is missing a response body",
            request_id=request_id,
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RetryableBatchRecordError(
            "batch record did not contain any choices",
            request_id=request_id,
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RetryableBatchRecordError(
            "batch record choice was malformed",
            request_id=request_id,
        )

    finish_reason = first_choice.get("finish_reason")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RetryableBatchRecordError(
            "batch record choice did not contain a message",
            request_id=request_id,
            finish_reason=finish_reason,
        )

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        reason = "model response did not contain a tool call"
        if finish_reason == "length":
            reason = "model response hit the token limit before emitting a tool call"
        raise RetryableBatchRecordError(
            reason,
            request_id=request_id,
            finish_reason=finish_reason,
        )

    first_tool_call = tool_calls[0]
    if not isinstance(first_tool_call, dict):
        raise RetryableBatchRecordError(
            "model response contained a malformed tool call",
            request_id=request_id,
            finish_reason=finish_reason,
        )

    function_call = first_tool_call.get("function")
    if not isinstance(function_call, dict):
        raise RetryableBatchRecordError(
            "model response contained a tool call without a function payload",
            request_id=request_id,
            finish_reason=finish_reason,
        )

    arguments_text = function_call.get("arguments")
    if not isinstance(arguments_text, str) or not arguments_text.strip():
        raise RetryableBatchRecordError(
            "model response did not contain tool arguments",
            request_id=request_id,
            finish_reason=finish_reason,
        )

    try:
        return json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        raise RetryableBatchRecordError(
            f"model returned malformed tool arguments: {exc.msg}",
            request_id=request_id,
            finish_reason=finish_reason,
        ) from exc
