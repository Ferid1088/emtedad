"""Failure-loop tests for the OpenRouter benchmark client (§24–26).

Covers: missing key, invalid model, malformed JSON, non-object JSON,
timeout, and 429 retry bound — using a mocked transport where possible so
no real quota is spent. Also asserts the API key never leaks into error
messages (security loop 1/2 groundwork).
"""

import asyncio
import json

import httpx

from benchmarks.qwen.client import (
    OpenRouterBenchmarkClient,
    OpenRouterError,
    OpenRouterRateLimitError,
    load_api_key,
)

KEY = load_api_key() or ""
RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append({"check": name, "ok": ok, "detail": detail[:400]})
    print(("PASS " if ok else "FAIL ") + name + " — " + detail[:200])


def leaked(text: str) -> bool:
    return bool(KEY) and KEY in text


async def test_missing_key() -> None:
    client = OpenRouterBenchmarkClient(api_key="")
    try:
        await client.chat([{"role": "user", "content": "hi"}])
    except OpenRouterError as exc:
        check("missing_key", "not configured" in str(exc), str(exc))
    else:
        check("missing_key", False, "no error raised")


async def test_invalid_model() -> None:
    client = OpenRouterBenchmarkClient()
    try:
        await client.chat(
            [{"role": "user", "content": "hi"}],
            model="qwen/definitely-not-a-real-model-xyz",
            task="failure_test",
            max_tokens=32,
        )
    except OpenRouterError as exc:
        check(
            "invalid_model",
            not leaked(str(exc)),
            f"raised {type(exc).__name__}: {exc}",
        )
    else:
        check("invalid_model", False, "no error raised")


async def test_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    client = OpenRouterBenchmarkClient(
        api_key="test-key", transport=httpx.MockTransport(handler)
    )
    try:
        await client.chat([{"role": "user", "content": "hi"}], task="failure_test")
    except OpenRouterError as exc:
        check("malformed_response", "JSON" in str(exc), str(exc))
    else:
        check("malformed_response", False, "no error raised")


async def test_empty_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"choices": []}).encode())

    client = OpenRouterBenchmarkClient(
        api_key="test-key", transport=httpx.MockTransport(handler)
    )
    try:
        await client.chat([{"role": "user", "content": "hi"}], task="failure_test")
    except OpenRouterError as exc:
        check("empty_choices", "content" in str(exc), str(exc))
    else:
        check("empty_choices", False, "no error raised")


async def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated")

    client = OpenRouterBenchmarkClient(
        api_key="test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.chat([{"role": "user", "content": "hi"}], task="failure_test")
    except OpenRouterError as exc:
        check("timeout", "transport" in str(exc), str(exc))
    else:
        check("timeout", False, "no error raised")


async def test_429_bounded_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="rate limited")

    # Shrink backoff so the test doesn't sleep for real.
    import benchmarks.qwen.client as mod

    original = mod._RATE_LIMIT_BACKOFF_SECONDS
    mod._RATE_LIMIT_BACKOFF_SECONDS = 0.01
    try:
        client = OpenRouterBenchmarkClient(
            api_key="test-key", transport=httpx.MockTransport(handler)
        )
        try:
            await client.chat([{"role": "user", "content": "hi"}], task="failure_test")
        except OpenRouterRateLimitError as exc:
            check(
                "429_bounded_retry",
                calls["n"] == 3,
                f"{calls['n']} attempts then raised: {exc}",
            )
        else:
            check("429_bounded_retry", False, "no error raised")
    finally:
        mod._RATE_LIMIT_BACKOFF_SECONDS = original


async def test_error_key_absent() -> None:
    """A real failed call must not echo the key anywhere."""
    client = OpenRouterBenchmarkClient()
    try:
        await client.chat(
            [{"role": "user", "content": "trigger error"}],
            model="qwen/definitely-not-real-abc",
            task="failure_test",
            max_tokens=16,
        )
    except Exception as exc:
        blob = str(exc) + repr(getattr(exc, "__cause__", ""))
        check(
            "key_absent_from_errors",
            not leaked(blob),
            "key not present in error chain" if not leaked(blob) else "LEAKED",
        )


async def main() -> None:
    await test_missing_key()
    await test_malformed_response()
    await test_empty_choices()
    await test_timeout()
    await test_429_bounded_retry()
    await test_invalid_model()
    await test_error_key_absent()
    out = "docs/audits/qwen_benchmark/failure_loop.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, ensure_ascii=False, indent=1)
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
