import json
import os

import tiktoken


OPENAI_BATCH_MODEL = "gpt-5.6-luna"
OPENAI_BATCH_REASONING_EFFORT = "none"
OPENAI_BATCH_INPUT_PRICE_PER_MILLION = 0.10
OPENAI_BATCH_OUTPUT_PRICE_PER_MILLION = 0.60
DEFAULT_MAX_BATCH_PROMPT_TOKENS = int(
    os.environ.get("OPENAI_MAX_BATCH_PROMPT_TOKENS", "500000")
)
TOKENIZER_FALLBACK = "o200k_base"
TOKEN_ESTIMATE_PADDING = 512


def calculate_batch_cost(prompt_tokens, completion_tokens):
    return (
        prompt_tokens * OPENAI_BATCH_INPUT_PRICE_PER_MILLION
        + completion_tokens * OPENAI_BATCH_OUTPUT_PRICE_PER_MILLION
    ) / 1_000_000


def encoding_for_model(model):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(TOKENIZER_FALLBACK)


def estimate_request_prompt_tokens(batch_request):
    body = batch_request.get("body") or {}
    model = body.get("model") or OPENAI_BATCH_MODEL
    prompt_payload = {
        "messages": body.get("messages", []),
        "tools": body.get("tools", []),
        "tool_choice": body.get("tool_choice"),
    }
    serialized = json.dumps(
        prompt_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(encoding_for_model(model).encode(serialized)) + TOKEN_ESTIMATE_PADDING


def validate_batch_requests(
    batch_file_path,
    expected_endpoint,
    expected_model,
    max_batch_prompt_tokens,
):
    """Validate endpoint, model, and estimated prompt-token budget."""

    problems = []
    estimated_prompt_tokens = 0
    request_count = 0

    with open(batch_file_path) as batch_file:
        for line_number, line in enumerate(batch_file, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                problems.append(
                    f"Line {line_number}: could not decode JSON ({exc})"
                )
                continue

            url = payload.get("url")
            if not url:
                problems.append(
                    f"Line {line_number}: missing URL in payload {payload!r}"
                )
                continue

            if url != expected_endpoint:
                problems.append(
                    f"Line {line_number}: unexpected endpoint '{url}' for custom_id"
                    f" {payload.get('custom_id')!r}. Expected {expected_endpoint!r}."
                )

            body = payload.get("body") or {}
            model = body.get("model")
            if model != expected_model:
                problems.append(
                    f"Line {line_number}: unexpected model {model!r} for custom_id"
                    f" {payload.get('custom_id')!r}. Expected {expected_model!r}."
                )

            if (
                model == OPENAI_BATCH_MODEL
                and body.get("tools")
                and body.get("reasoning_effort")
                != OPENAI_BATCH_REASONING_EFFORT
            ):
                problems.append(
                    f"Line {line_number}: unexpected reasoning_effort"
                    f" {body.get('reasoning_effort')!r} for function tools with"
                    f" {OPENAI_BATCH_MODEL!r}. Expected"
                    f" {OPENAI_BATCH_REASONING_EFFORT!r}."
                )

            request_tokens = estimate_request_prompt_tokens(payload)
            request_count += 1
            estimated_prompt_tokens += request_tokens

            if request_tokens > max_batch_prompt_tokens:
                problems.append(
                    f"Line {line_number}: estimated prompt tokens {request_tokens:,}"
                    f" exceed the batch limit {max_batch_prompt_tokens:,} for"
                    f" custom_id {payload.get('custom_id')!r}."
                )

    if estimated_prompt_tokens > max_batch_prompt_tokens:
        problems.append(
            f"Estimated batch prompt tokens {estimated_prompt_tokens:,} exceed"
            f" the limit {max_batch_prompt_tokens:,}."
        )

    if problems:
        problem_report = "\n".join(problems)
        raise SystemExit(
            "Refusing to submit batch file because validation failed:\n"
            f"{problem_report}"
        )

    return request_count, estimated_prompt_tokens
