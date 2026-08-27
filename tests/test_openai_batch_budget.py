import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai_batch_budget import (
    OPENAI_BATCH_MODEL,
    OPENAI_BATCH_REASONING_EFFORT,
    estimate_request_prompt_tokens,
    validate_batch_requests,
)


def make_batch_request(
    content="hello",
    model=OPENAI_BATCH_MODEL,
    reasoning_effort=OPENAI_BATCH_REASONING_EFFORT,
):
    return {
        "custom_id": "https://example.test/filing.htm",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "messages": [
                {"role": "system", "content": "Extract directors."},
                {"role": "user", "content": content},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "show_directors",
                        "parameters": {
                            "type": "object",
                            "properties": {"directors": {"type": "array"}},
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "show_directors"}},
        },
    }


def write_batch_file(tmp_path, requests):
    batch_file = tmp_path / "batch.jsonl"
    with batch_file.open("w") as output:
        for request in requests:
            output.write(json.dumps(request) + "\n")
    return batch_file


def test_estimate_request_prompt_tokens_scales_with_content():
    short_count = estimate_request_prompt_tokens(make_batch_request("short"))
    long_count = estimate_request_prompt_tokens(make_batch_request("long " * 1000))

    assert short_count > 0
    assert long_count > short_count


def test_validate_batch_requests_accepts_expected_model_and_budget(tmp_path):
    request = make_batch_request("short")
    batch_file = write_batch_file(tmp_path, [request])

    request_count, prompt_tokens = validate_batch_requests(
        batch_file,
        "/v1/chat/completions",
        OPENAI_BATCH_MODEL,
        500_000,
    )

    assert request_count == 1
    assert prompt_tokens == estimate_request_prompt_tokens(request)


def test_validate_batch_requests_rejects_unexpected_model(tmp_path):
    batch_file = write_batch_file(tmp_path, [make_batch_request(model="gpt-5")])

    with pytest.raises(SystemExit) as excinfo:
        validate_batch_requests(
            batch_file,
            "/v1/chat/completions",
            OPENAI_BATCH_MODEL,
            500_000,
        )

    assert "unexpected model 'gpt-5'" in str(excinfo.value)


@pytest.mark.parametrize("reasoning_effort", [None, "low", "medium"])
def test_validate_batch_requests_rejects_unsupported_tool_reasoning_effort(
    tmp_path,
    reasoning_effort,
):
    request = make_batch_request(reasoning_effort=reasoning_effort)
    if reasoning_effort is None:
        del request["body"]["reasoning_effort"]
    batch_file = write_batch_file(tmp_path, [request])

    with pytest.raises(SystemExit) as excinfo:
        validate_batch_requests(
            batch_file,
            "/v1/chat/completions",
            OPENAI_BATCH_MODEL,
            500_000,
        )

    assert "unexpected reasoning_effort" in str(excinfo.value)


def test_validate_batch_requests_rejects_over_budget_batch(tmp_path):
    request = make_batch_request("budget " * 1000)
    batch_file = write_batch_file(tmp_path, [request])

    with pytest.raises(SystemExit) as excinfo:
        validate_batch_requests(
            batch_file,
            "/v1/chat/completions",
            OPENAI_BATCH_MODEL,
            1,
        )

    assert "Estimated batch prompt tokens" in str(excinfo.value)
