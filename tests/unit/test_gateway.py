"""The model gateway: schemas (config, wire shapes, usage, traces), providers, and the service over the bus."""

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import httpx
import pytest
from pydantic import ValidationError

from gateway.providers import (
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatProvider,
    OpenAIProvider,
    ProviderError,
    VLLMProvider,
    build_provider,
)
from gateway.providers.claude import parse_claude_response
from gateway.providers.openai_compat import parse_openai_response, to_openai_messages, to_openai_tools
from gateway.schemas import (
    KINDS,
    CompletionRequest,
    CompletionResult,
    GatewayConfig,
    LlmTrace,
    ProviderConfig,
    ProviderKind,
    ToolCall,
    Usage,
    UsageRecord,
)
from gateway.service import GatewayService
from mycelium_sdk import InMemoryBus, InMemoryKV

REPO = Path(__file__).resolve().parents[2]

REMEMBER_TOOL = {
    "name": "remember",
    "description": "Write a fact to memory.",
    "input_schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]},
}

# ---- config --------------------------------------------------------------------------------------


def test_config_accepts_the_doc_shape_and_infers_kind():
    cfg = GatewayConfig.model_validate(
        {
            "budget_usd_month": 30,
            "planner": {
                "active": "claude",
                "shadow": "local",
                "claude": {"model": "claude-sonnet-5-5", "key_env": "ANTHROPIC_API_KEY", "price_in_per_m": 3},
                "local": {"model": "qwen2.5:14b", "endpoint": "http://ollama:11434/v1"},
            },
        }
    )
    planner = cfg.slots["planner"]
    assert planner.active == "claude" and planner.shadow == "local"
    assert planner.providers["claude"].kind == "claude"
    assert planner.providers["local"].kind == "openai_compat"  # an endpoint and no kind: a generic server
    assert cfg.budget_usd_month == 30


@pytest.mark.parametrize(
    "slot,msg",
    [
        ({"active": "nope", "claude": {"model": "x"}}, "not defined"),
        ({"active": "claude", "shadow": "claude", "claude": {"model": "x"}}, "differ"),
        ({"active": "local", "local": {"model": "x", "kind": "openai_compat"}}, "endpoint"),
        ({"active": "x", "x": {"model": "m", "kind": "bedrock"}}, "kind"),
    ],
)
def test_config_rejects_bad_slots(slot, msg):
    with pytest.raises(ValidationError, match=msg):
        GatewayConfig.model_validate({"planner": slot})


# ---- kinds ---------------------------------------------------------------------------------------


def test_every_kind_has_defaults_and_they_fill_the_config():
    assert set(get_args(ProviderKind)) == set(KINDS)
    ollama = ProviderConfig(kind="ollama", model="qwen2.5:14b")
    assert ollama.endpoint == "http://ollama:11434/v1" and ollama.key_env is None and ollama.protocol == "openai"
    assert ollama.key_state({}) == "not-needed" and ollama.info.local
    openai = ProviderConfig(kind="openai", model="gpt-5-mini")
    assert openai.endpoint == "https://api.openai.com/v1" and openai.key_env == "OPENAI_API_KEY"
    assert openai.key_state({}) == "missing" and openai.key_state({"OPENAI_API_KEY": "k"}) == "ok"
    claude = ProviderConfig(model="claude-sonnet-5-5")
    assert claude.kind == "claude" and claude.key_env == "ANTHROPIC_API_KEY" and claude.endpoint is None
    groq = ProviderConfig(kind="groq", model="llama-3.3-70b", endpoint="http://proxy:8080/v1", key_env="MY_KEY")
    assert groq.endpoint == "http://proxy:8080/v1" and groq.key_env == "MY_KEY"  # explicit values win


def test_build_provider_picks_the_class_per_kind():
    env = {"OPENAI_API_KEY": "k1", "ANTHROPIC_API_KEY": "k2"}
    c = build_provider("c", ProviderConfig(kind="claude", model="m", endpoint="http://proxy/anthropic"), env)
    assert isinstance(c, ClaudeProvider) and c.api_key == "k2" and c.base_url == "http://proxy/anthropic"
    o = build_provider("o", ProviderConfig(kind="openai", model="m"), env)
    assert isinstance(o, OpenAIProvider) and o.api_key == "k1" and o.require_key
    assert isinstance(build_provider("l", ProviderConfig(kind="ollama", model="m"), env), OllamaProvider)
    assert isinstance(build_provider("v", ProviderConfig(kind="vllm", model="m"), env), VLLMProvider)
    g = build_provider("g", ProviderConfig(kind="groq", model="m", headers={"X-Title": "mycelium"}), env)
    assert type(g) is OpenAICompatProvider and g.endpoint == "https://api.groq.com/openai/v1"
    assert g.require_key and g.api_key is None and g.headers == {"X-Title": "mycelium"}


async def test_openai_kind_sends_max_completion_tokens_headers_and_extra_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIProvider(
        "openai",
        "gpt-5-mini",
        "https://api.openai.com/v1",
        api_key="k",
        http=http,
        headers={"X-Title": "mycelium"},
        extra_body={"reasoning_effort": "low"},
    )
    r = await p.complete(CompletionRequest(messages=[{"role": "user", "content": "hi"}], max_tokens=64))
    assert r.text == "hi"
    assert seen["body"]["max_completion_tokens"] == 64 and "max_tokens" not in seen["body"]
    assert seen["body"]["reasoning_effort"] == "low"
    assert seen["headers"]["x-title"] == "mycelium" and seen["headers"]["authorization"] == "Bearer k"


async def test_cloud_kind_without_key_fails_before_any_request_and_local_kinds_need_none():
    p = OpenAIProvider("openai", "gpt-5-mini", "https://api.openai.com/v1", api_key=None, require_key=True)
    with pytest.raises(ProviderError, match="no API key"):
        await p.complete(CompletionRequest(messages=[{"role": "user", "content": "x"}]))
    local = OllamaProvider("ollama", "qwen2.5:14b", "http://ollama:11434/v1")
    assert local.require_key is False and local.timeout == 300.0  # first call loads the model


def test_tool_calls_win_over_a_stop_finish_reason():  # Ollama reports finish_reason=stop with tool calls
    data = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "c", "function": {"name": "recall", "arguments": "{}"}}],
                },
            }
        ]
    }
    assert parse_openai_response(data, "m").stop_reason == "tool_use"


def test_cost_from_prices():
    p = ProviderConfig(model="m", price_in_per_m=3.0, price_out_per_m=15.0)
    assert p.cost(1_000_000, 0) == 3.0
    assert p.cost(1000, 1000) == 0.018
    assert ProviderConfig(model="m").cost(10**6, 10**6) == 0.0  # local: free


def test_shipped_providers_yaml_loads():
    cfg = GatewayConfig.from_yaml(REPO / "services/gateway/providers.yaml", env={})
    planner = cfg.slots["planner"]
    assert planner.active in planner.providers and cfg.budget_usd_month
    assert {p.kind for p in planner.providers.values()} == {"claude", "openai", "ollama", "vllm"}
    assert all(p.key_env or not p.info.needs_key for p in planner.providers.values())  # a key name, or none needed


# ---- usage counter and traces --------------------------------------------------------------------


def test_usage_record_adds_a_call_and_checks_the_budget():
    rec = UsageRecord().add(0.0045, Usage(input_tokens=1000, output_tokens=100))
    assert rec == UsageRecord(usd=0.0045, calls=1, input_tokens=1000, output_tokens=100)
    assert rec.over(0.004) and not rec.over(10.0) and not rec.over(None)
    assert UsageRecord.model_validate({"usd": 10.0, "calls": 5}).output_tokens == 0  # older records: defaults


def test_llm_trace_is_an_envelope_without_content():
    t = LlmTrace(cause="ev1", slot="planner", provider="claude", ok=True, cost_usd=0.01)
    assert t.source == "gateway" and t.hops == 0 and re.fullmatch(r"[0-9a-f]{21}", t.id)
    d = t.model_dump(mode="json")
    assert d["cause"] == "ev1" and d["usage"] is None and d["tool_calls"] == []
    assert not {"text", "system", "messages"} & set(d)
    with pytest.raises(ValidationError):
        LlmTrace(slot="planner", provider="claude", ok=True, latency_ms=-1)


# ---- wire formats --------------------------------------------------------------------------------


def test_request_validation():
    with pytest.raises(ValidationError, match="role"):
        CompletionRequest(messages=[{"role": "system", "content": "x"}])
    with pytest.raises(ValidationError, match="input_schema"):
        CompletionRequest(messages=[{"role": "user", "content": "x"}], tools=[{"name": "t"}])
    req = CompletionRequest(messages=[{"role": "user", "content": "hi"}], tools=[REMEMBER_TOOL])
    assert req.slot == "planner" and req.max_tokens is None


def test_parse_claude_response_text_and_tool_use():
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Saving that."),
            SimpleNamespace(type="tool_use", id="toolu_1", name="remember", input={"note": "mei"}),
        ],
        stop_reason="tool_use",
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )
    r = parse_claude_response(resp, "fallback")
    assert r.text == "Saving that."
    assert r.tool_calls == [ToolCall(id="toolu_1", name="remember", input={"note": "mei"})]
    assert r.stop_reason == "tool_use" and r.model == "claude-sonnet-5-5"
    assert r.usage == Usage(input_tokens=120, output_tokens=30)


def test_openai_conversion_round_trip_of_tool_turns():
    messages = [
        {"role": "user", "content": "remember mei"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "id": "call_1", "name": "remember", "input": {"note": "mei"}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok": true}'}]},
    ]
    out = to_openai_messages("You are Main.", messages)
    assert out[0] == {"role": "system", "content": "You are Main."}
    assert out[1] == {"role": "user", "content": "remember mei"}
    assert out[2]["role"] == "assistant" and out[2]["content"] == "ok"
    assert out[2]["tool_calls"][0]["function"] == {"name": "remember", "arguments": '{"note": "mei"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}
    assert to_openai_tools([REMEMBER_TOOL])[0]["function"]["parameters"] == REMEMBER_TOOL["input_schema"]


def test_parse_openai_response_with_tool_calls():
    data = {
        "model": "qwen2.5:14b",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "call_9", "function": {"name": "remember", "arguments": '{"note": "mei"}'}},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }
    r = parse_openai_response(data, "x")
    assert r.text == "" and r.stop_reason == "tool_use" and r.model == "qwen2.5:14b"
    assert r.tool_calls[0].input == {"note": "mei"}
    assert r.usage.input_tokens == 50 and r.usage.output_tokens == 10
    with pytest.raises(ProviderError):
        parse_openai_response({"choices": []}, "x")


async def test_openai_provider_posts_to_chat_completions():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAICompatProvider("local", "qwen2.5:14b", "http://ollama:11434/v1/", api_key="k", http=http)
    r = await p.complete(CompletionRequest(system="S", messages=[{"role": "user", "content": "hi"}], max_tokens=64))
    assert r.text == "hello" and r.stop_reason == "end_turn"
    assert seen["url"] == "http://ollama:11434/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "S"}
    assert seen["body"]["max_tokens"] == 64 and seen["body"]["model"] == "qwen2.5:14b"
    assert seen["auth"] == "Bearer k"


class FakeMessages:
    def __init__(self, resp):
        self.resp = resp
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


async def test_claude_provider_passes_system_and_tools():
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hi")],
        stop_reason="end_turn",
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = SimpleNamespace(messages=FakeMessages(resp))
    p = ClaudeProvider("claude", "claude-sonnet-5-5", api_key="k", max_tokens=777, client=client)
    r = await p.complete(
        CompletionRequest(system="S", messages=[{"role": "user", "content": "x"}], tools=[REMEMBER_TOOL])
    )
    assert r.text == "hi"
    assert client.messages.kwargs["system"] == "S"
    assert client.messages.kwargs["tools"] == [REMEMBER_TOOL]
    assert client.messages.kwargs["max_tokens"] == 777


async def test_claude_provider_without_key_fails_clearly():
    p = ClaudeProvider("claude", "claude-sonnet-5-5", api_key=None)
    with pytest.raises(ProviderError, match="no API key"):
        await p.complete(CompletionRequest(messages=[{"role": "user", "content": "x"}]))


# ---- service -------------------------------------------------------------------------------------


class ScriptedProvider:
    """Returns the next scripted result on each call; records what it was asked."""

    def __init__(self, name, model, results):
        self.name = name
        self.model = model
        self.results = list(results)
        self.requests = []

    async def complete(self, req):
        self.requests.append(req)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _config(shadow=None, budget=10.0):
    return GatewayConfig.model_validate(
        {
            "budget_usd_month": budget,
            "planner": {
                "active": "claude",
                "shadow": shadow,
                "claude": {"model": "claude-sonnet-5-5", "price_in_per_m": 3.0, "price_out_per_m": 15.0},
                "local": {"model": "qwen", "endpoint": "http://ollama:11434/v1"},
            },
        }
    )


def _result(text="hello", tool_calls=(), tokens=(1000, 100)):
    return CompletionResult(
        text=text,
        tool_calls=list(tool_calls),
        stop_reason="tool_use" if tool_calls else "end_turn",
        model="claude-sonnet-5-5",
        usage=Usage(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


async def _service(active_results, shadow=None, shadow_results=(), budget=10.0, kv=None):
    bus = InMemoryBus()
    kv = kv or InMemoryKV()
    providers = {
        ("planner", "claude"): ScriptedProvider("claude", "claude-sonnet-5-5", active_results),
        ("planner", "local"): ScriptedProvider("local", "qwen", shadow_results),
    }
    svc = GatewayService(
        bus, _config(shadow, budget), kv, providers=providers, now=lambda: datetime(2026, 10, 23, tzinfo=UTC)
    )
    await svc.start()
    return svc


async def test_complete_replies_traces_and_counts_usage():
    svc = await _service([_result(tool_calls=[ToolCall(id="t1", name="remember", input={"note": "mei"})])])
    reply = await svc.bus.request(
        "rpc.llm.complete",
        {"slot": "planner", "messages": [{"role": "user", "content": "hi"}], "tools": [REMEMBER_TOOL], "cause": "ev1"},
    )
    assert reply["ok"] and reply["provider"] == "claude" and reply["model"] == "claude-sonnet-5-5"
    assert reply["tool_calls"] == [{"id": "t1", "name": "remember", "input": {"note": "mei"}}]
    assert reply["stop_reason"] == "tool_use"
    assert reply["cost_usd"] == 0.0045  # 1000 in * 3 + 100 out * 15, per million

    traces = svc.bus.events("trace.llm")
    assert len(traces) == 1
    t = traces[0][1]
    assert t["cause"] == "ev1" and t["hops"] == 1 and t["ok"] and t["slot"] == "planner" and t["cost_usd"] == 0.0045
    assert t["tool_calls"] == ["remember"] and t["tools_offered"] == ["remember"]
    assert "text" not in t  # content never goes in trace.llm

    usage = await svc.bus.request("rpc.llm.usage", {})
    assert usage["month"] == "2026-10" and usage["calls"] == 1 and usage["usd"] == 0.0045
    assert usage["input_tokens"] == 1000 and usage["budget_usd_month"] == 10.0


async def test_budget_exceeded_fails_fast_and_traces():
    kv = InMemoryKV()
    await kv.put("usage/2026-10", {"usd": 10.0, "calls": 5})
    svc = await _service([_result()], kv=kv)
    reply = await svc.bus.request("rpc.llm.complete", {"messages": [{"role": "user", "content": "hi"}]})
    assert not reply["ok"] and "budget exceeded" in reply["error"]
    assert svc.providers[("planner", "claude")].requests == []  # the provider was never called
    assert svc.bus.events("trace.llm")[0][1]["ok"] is False


async def test_provider_error_is_a_clean_reply():
    svc = await _service([ProviderError("claude: AuthenticationError: bad key")])
    reply = await svc.bus.request("rpc.llm.complete", {"messages": [{"role": "user", "content": "hi"}]})
    assert reply == {"ok": False, "error": "claude: AuthenticationError: bad key"}
    assert svc.bus.events("trace.llm")[0][1]["error"].startswith("claude:")


async def test_bad_requests_are_rejected_with_field_paths():
    svc = await _service([_result()])
    reply = await svc.bus.request("rpc.llm.complete", {"messages": []})
    assert not reply["ok"] and reply["error"].startswith("messages:")
    reply = await svc.bus.request("rpc.llm.complete", {"slot": "coder", "messages": [{"role": "user", "content": "x"}]})
    assert not reply["ok"] and "unknown slot 'coder'" in reply["error"]


async def test_shadow_runs_after_the_reply_and_is_billed_and_traced():
    svc = await _service([_result("A")], shadow="local", shadow_results=[_result("B", tokens=(50, 5))])
    reply = await svc.bus.request(
        "rpc.llm.complete", {"messages": [{"role": "user", "content": "hi"}], "cause": "e", "hops": 1}
    )
    assert reply["ok"] and reply["text"] == "A" and reply["provider"] == "claude"
    await svc.drain()
    shadow = svc.bus.events("trace.llm.shadow")
    assert len(shadow) == 1
    s = shadow[0][1]
    assert s["shadow"]["provider"] == "local" and s["shadow"]["text"] == "B" and s["agree"] is True
    assert s["cause"] == "e" and s["hops"] == 2
    llm = [t for _, t in svc.bus.events("trace.llm")]
    assert [(t["provider"], t["shadow"]) for t in llm] == [("claude", False), ("local", True)]
    assert all(t["hops"] == 2 for t in llm)
    usage = await svc.bus.request("rpc.llm.usage", {})
    assert usage["calls"] == 2 and usage["input_tokens"] == 1050 and usage["usd"] == 0.0045  # local is free


class SlowProvider:
    def __init__(self, name="claude", model="m", delay=0.2):
        self.name, self.model, self.delay = name, model, delay

    async def complete(self, req):
        await asyncio.sleep(self.delay)
        return _result()


async def test_the_callers_timeout_is_enforced_before_the_vendor_call_is_billed():
    svc = await _service([])
    svc.providers[("planner", "claude")] = SlowProvider(delay=0.2)
    reply = await svc.bus.request(
        "rpc.llm.complete", {"messages": [{"role": "user", "content": "hi"}], "timeout": 0.05}
    )
    assert not reply["ok"] and reply["error"] == "claude: timed out after 0.05s"
    t = svc.bus.events("trace.llm")[0][1]
    assert t["ok"] is False and "timed out" in t["error"] and t["hops"] == 0  # no cause: a root trace
    assert (await svc.bus.request("rpc.llm.usage", {}))["calls"] == 0


async def test_requests_are_served_concurrently():
    svc = await _service([])
    svc.providers[("planner", "claude")] = SlowProvider(delay=0.1)
    t0 = time.monotonic()
    replies = await asyncio.gather(
        *(svc.bus.request("rpc.llm.complete", {"messages": [{"role": "user", "content": str(i)}]}) for i in range(3))
    )
    assert all(r["ok"] for r in replies) and time.monotonic() - t0 < 0.25  # not 3 x 0.1 in a row
    assert (await svc.bus.request("rpc.llm.usage", {}))["calls"] == 3  # the counter survived concurrent updates


# ---- forced tool (structured output) ---------------------------------------------------------------


async def test_tool_choice_forces_the_tool_on_both_wire_shapes():
    with pytest.raises(ValidationError, match="tool_choice"):
        CompletionRequest(messages=[{"role": "user", "content": "x"}], tools=[REMEMBER_TOOL], tool_choice="other")
    req = CompletionRequest(messages=[{"role": "user", "content": "x"}], tools=[REMEMBER_TOOL], tool_choice="remember")

    resp = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id="t", name="remember", input={"note": "mei"})],
        stop_reason="tool_use",
        model="m",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = SimpleNamespace(messages=FakeMessages(resp))
    await ClaudeProvider("claude", "m", api_key="k", client=client).complete(req)
    assert client.messages.kwargs["tool_choice"] == {"type": "tool", "name": "remember"}

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await OpenAICompatProvider("local", "m", "http://ollama:11434/v1", http=http).complete(req)
    assert seen["body"]["tool_choice"] == {"type": "function", "function": {"name": "remember"}}


def test_shipped_yaml_has_the_consolidate_slot_on_a_cheap_model():
    cfg = GatewayConfig.from_yaml(REPO / "services/gateway/providers.yaml", env={})
    slot = cfg.slots["consolidate"]
    assert slot.active == "claude" and slot.providers["claude"].max_tokens >= 4096
    assert slot.providers["claude"].price_in_per_m < cfg.slots["planner"].providers["claude"].price_in_per_m


def test_from_yaml_fills_env_placeholders_with_defaults(tmp_path):
    from gateway.schemas.config import expand_env

    assert expand_env("a=${X:-dflt} b=${Y} c=${Z:-}", {"Y": "set"}) == "a=dflt b=set c="
    assert expand_env("${X:-dflt}", {"X": ""}) == "dflt"  # compose passes empty for unset .env keys
    y = tmp_path / "p.yaml"
    y.write_text(
        "planner:\n  active: ${PLANNER_PROVIDER:-claude}\n  claude: {model: m}\n"
        "  vllm: {kind: vllm, endpoint: ${VLLM_ENDPOINT:-http://vllm:8000/v1}, model: ${VLLM_MODEL:-Qwen/Q}}\n"
    )
    cfg = GatewayConfig.from_yaml(y, env={})
    assert cfg.slots["planner"].active == "claude" and cfg.slots["planner"].providers["vllm"].model == "Qwen/Q"
    cfg = GatewayConfig.from_yaml(y, env={"PLANNER_PROVIDER": "vllm", "VLLM_ENDPOINT": "http://192.168.0.107:8000/v1"})
    assert cfg.slots["planner"].active == "vllm"
    assert cfg.slots["planner"].providers["vllm"].endpoint == "http://192.168.0.107:8000/v1"


async def test_a_model_that_rejects_a_forced_tool_is_asked_once_more_without_forcing():
    svc = await _service(
        [
            ProviderError("claude: BadRequestError: tool_choice type 'tool' is not supported for this model"),
            _result(tool_calls=[ToolCall(id="t1", name="remember", input={"note": "mei"})]),
        ]
    )
    reply = await svc.bus.request(
        "rpc.llm.complete",
        {"messages": [{"role": "user", "content": "hi"}], "tools": [REMEMBER_TOOL], "tool_choice": "remember"},
    )
    assert reply["ok"] and reply["tool_calls"][0]["name"] == "remember"
    requests = svc.providers[("planner", "claude")].requests
    assert requests[0].tool_choice == "remember" and requests[1].tool_choice is None
    assert len(svc.bus.events("trace.llm")) == 1  # the retry is the call that counts
