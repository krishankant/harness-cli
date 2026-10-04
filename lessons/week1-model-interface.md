# Week 1: One interface for every model

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**You're done when:**

1. `uv run pytest tests/week1` passes (42 tests), and
2. `uv run python -m scripts.week1_compare` shows the same `ModelResponse` shape for both providers.

## 1. Read first

| Read | Look for |
| --- | --- |
| [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (Anthropic) | The difference between a *workflow* and an *agent*, and the advice to start with the simplest thing that works. |
| [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works) (Claude docs) and [Function calling](https://platform.openai.com/docs/guides/function-calling) (OpenAI docs) | Read them side by side. Write down every place the two formats differ. You'll need that list for section 3. |
| [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) (Ollama) | How a local model can pretend to be OpenAI. This is why one OpenAI adapter covers Ollama too. |
| [`docs/model-interfaces.md`](../docs/model-interfaces.md) (this repo) | The two formats side by side: one tool round trip in Anthropic Messages, OpenAI Chat Completions and OpenAI Responses, plus stop reasons, usage fields, reasoning and streaming. Check your own list of differences against it. |

## 2. What you're building this week

A harness talks to models. Every provider has its own message format, and if those formats leak into your loop, your tools or your evals, you're tied to one provider for good.

So harnessy draws one line. Everything inside the harness speaks **harnessy types**. Each provider gets an **adapter** that translates to and from its own format, and the adapter is the only code that knows that format exists.

```
 loop, tools, evals ──► harnessy types ──► adapter ──► provider API
                    ◄──               ◄──          ◄──
```

This week you write the translation code for two adapters.

The same boundary as a diagram. Only the adapters know a provider's format exists:

```mermaid
flowchart LR
  subgraph H["inside the harness: harnessy types only"]
    L["loop · tools · evals"]
  end
  subgraph AD["adapters: this week"]
    AA["AnthropicModel"]
    OA["OpenAIModel"]
  end
  L -- "Message · ToolSpec" --> AA
  L -- "Message · ToolSpec" --> OA
  AA -- "ModelResponse" --> L
  OA -- "ModelResponse" --> L
  AA <--> AP["Anthropic Messages API"]
  OA <--> OP["OpenAI Chat Completions<br/>(or Ollama via base_url)"]
```

## 3. Why a neutral format: what the adapters hide

| | Anthropic Messages API | OpenAI Chat Completions |
| --- | --- | --- |
| System prompt | Separate `system` field | First message, `{"role": "system"}` |
| Tool definition | `{name, description, input_schema}` | `{"type": "function", "function": {name, description, parameters}}` |
| Tool call from the model | `tool_use` content block, `input` is an **object** | `tool_calls` entry, `arguments` is a **JSON string** |
| Tool result back to the model | `tool_result` blocks inside **one user turn**, with an `is_error` flag | **One `tool` message per result**, with no error flag |
| "I want to call tools" | `stop_reason: "tool_use"` | `finish_reason: "tool_calls"` |
| "I'm finished" | `end_turn` (or `stop_sequence`) | `stop` |
| Ran out of output tokens | `max_tokens` | `length` |
| Refused | `refusal` | `content_filter` |
| Token counts | `usage.input_tokens` / `output_tokens` | `usage.prompt_tokens` / `completion_tokens` |

Every row is something your loop would otherwise need an `if provider == ...` for.

## 4. Tour of the given code

Read these files before writing anything. They're short.

**`harnessy/types.py`**

- `Message` is one turn. A user turn carries text and/or `tool_results`; an assistant turn carries text and/or `tool_calls`.
- **The system prompt is not a message.** It's passed on its own to `complete()`. Anthropic wants it separate and OpenAI wants it first, and only the adapter should care which.
- Everything is a **frozen dataclass**, and sequences are **tuples**. A conversation is a history; nothing should edit a past turn by accident. This matters more than it looks (see section 5).
- `ToolResult.is_error` exists because failures are results, not exceptions. The model reads the error and can fix its next call. You'll lean on this hard in week 2.
- `StopReason` is harnessy's own small vocabulary: `end_turn`, `tool_use`, `max_tokens`, `refused`, `error`.

**`harnessy/models/base.py`**

`Model` is a `Protocol` with one method, `complete(messages, tools, system) -> ModelResponse`. Anything with that method *is* a model. There's no base class to inherit. The loop in week 2 will accept a real provider, a local model or a fake scripted model in exactly the same way.

**The `complete()` methods in both adapters are given.** They make the network call and hand a plain dict to the functions you write. That split is on purpose: translation is pure data-in, data-out, so it's easy to test without a network.

How the types in `types.py` fit together:

```mermaid
classDiagram
  direction LR
  class Message {
    +role
    +text
    +tool_calls
    +tool_results
    +raw
  }
  class ToolCall {
    +id
    +name
    +arguments
  }
  class ToolResult {
    +tool_call_id
    +content
    +is_error
  }
  class ProviderRaw {
    +provider
    +content
  }
  class ModelResponse {
    +message
    +stop_reason
    +usage
  }
  class Usage {
    +input_tokens
    +output_tokens
    +total()
  }
  class ToolSpec {
    +name
    +description
    +parameters
  }
  Message "1" o-- "*" ToolCall : assistant turn
  Message "1" o-- "*" ToolResult : user turn
  Message "1" o-- "0..1" ProviderRaw : replayed verbatim
  ModelResponse --> Message
  ModelResponse --> Usage
  ToolResult ..> ToolCall : answers by id
```

*The full version, with what later weeks add, is Fig 2 in [docs/architecture.md](../docs/architecture.md#fig-2-core-types).*

## 5. The opaque-state problem

This is the most important idea this week.

Current Claude models (the default here is `claude-opus-5`) **think before answering**. The response contains `thinking` blocks next to the text and tool calls. By default the thinking text is empty, but the block carries a `signature`. When you send the conversation back for the next turn, **those blocks must go back exactly as they came**. The API checks this. The response can also contain `fallback` blocks, which mark where a declined request was re-run on another model (the adapter turns on server-side fallbacks for Opus 5). The API treats those as markers it ignores, so they could be dropped, but keeping them in `raw` means the turn goes back exactly as it came, with no special cases.

harnessy's neutral `Message` has no field for "Anthropic thinking block", and it shouldn't. So:

- `Message.raw = ProviderRaw(provider, content)` stores the provider's own content for that assistant turn.
- **The adapter that produced it replays it verbatim.** The Anthropic adapter sends `raw.content` back unchanged when `raw.provider == "anthropic"`.
- **Any other adapter ignores it** and rebuilds from `text` + `tool_calls`. That's how a conversation can start on Claude and continue on OpenAI.
- **Histories are append-only.** Never edit or drop an earlier turn in place. When you build context compaction in week 4, you'll summarize by *appending*, not by rewriting old turns, for exactly this reason.

The OpenAI Chat Completions format has no opaque state like this, so the OpenAI adapter always rebuilds. It still stores `raw` for debugging.

What happens to `raw` on the next turn, for each adapter:

```mermaid
sequenceDiagram
  participant L as Loop
  participant A as AnthropicModel
  participant O as OpenAIModel
  participant API as Provider API
  L->>A: complete(history)
  A->>API: request
  API-->>A: content: thinking + text + tool_use
  A-->>L: Message(text, tool_calls, raw=ProviderRaw("anthropic", content))
  Note over L: the history keeps that Message unchanged
  L->>A: complete(history + results)
  A->>API: replays raw.content verbatim (the API checks the thinking blocks)
  L->>O: complete(same history)
  O->>API: ignores raw, rebuilds from text + tool_calls
```

## 6. Exercises

Each exercise is a function that currently raises `NotImplementedError`. Its docstring says exactly what it must do. Run one test group at a time:

```bash
uv run pytest tests/week1/test_anthropic_adapter.py -k stop_reason
```

**Anthropic (`harnessy/models/anthropic.py`)**

| # | Function | Tests (`-k`) | Hint |
| --- | --- | --- | --- |
| 1a | `map_anthropic_stop_reason` | `stop_reason` | The `_STOP_REASONS` table is already there. Unknown and `None` both become `"error"`. |
| 1b | `to_anthropic_tools` | `tools_use_input_schema` | One dict per tool. The schema key is `input_schema`. |
| 1c | `to_anthropic_messages` | `user_text or assistant or another_provider or come_first` | Check `raw` first. Tool results must come **before** any text in a user turn. |
| 1d | `from_anthropic_response` | `parse` | Join text blocks with no separator. Skip `thinking`/`fallback` blocks for text, but keep *all* content in `raw`. |

**OpenAI (`harnessy/models/openai.py`)**

| # | Function | Tests (`-k`) | Hint |
| --- | --- | --- | --- |
| 2a | `map_openai_finish_reason` | `finish_reason` | Same idea as 1a. |
| 2b | `to_openai_tools` | `wrapped_as_functions` | Wrap each tool as `{"type": "function", "function": {...}}`. |
| 2c | `to_openai_messages` | `system or assistant or tool_result or anthropic_raw` | `json.dumps` the arguments. An assistant turn with only tool calls has `content: None`. Each tool result is its own message. |
| 2d | `from_openai_response` | `parse or bad_or_non_object` | `arguments` is a string you must `json.loads`. If that fails, or gives a list, keep `{"_raw": <string>}`. Never raise on bad model output. |

Once 1a–1d pass, the two `test_complete_*` Anthropic tests pass too. They use a fake client to check that `complete()` leaves out `tools` when there are none, and sends fallbacks only for models that support them.

## 7. Try it live

1. `cp .env.example .env`, then set `ANTHROPIC_API_KEY` (or run `ant auth login` and leave it commented out), plus `OPENAI_API_KEY` and `OPENAI_MODEL` (any current OpenAI model that supports tool calling).
2. Run `uv run python -m scripts.week1_compare`.

You should see two blocks, one per provider. Each has `turn 1` with `stop=tool_use` and an `add` call, then `turn 2` with `stop=end_turn` and the answer 42. The *shape* of both is identical. That's the whole point of this week.

The script stops the conversation by hand after two turns. Next week you replace that hand-written sequence with a loop.

**Stretch: Ollama.** Install [Ollama](https://docs.ollama.com/api/openai-compatibility), pull a small model that supports tools, and set `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama` and `OPENAI_MODEL=<that model>`. Run the script again with no code changes. Write down what behaved differently.

## 8. Check yourself

- Compare with the reference: `HARNESSY_IMPL=solutions uv run pytest tests/week1` runs the same tests against `solutions/`.
- See the difference: `diff harnessy/models/anthropic.py solutions/harnessy/models/anthropic.py`.
- Try it only *after* your own version passes. Two correct solutions can look different.

## 9. Notes for `NOTES.md`

1. Which difference between the two APIs surprised you most, and where would it have leaked into your loop without the adapter?
2. `from_openai_response` turns invalid JSON into `{"_raw": ...}` instead of raising. What will the loop do with that next week, and why is that better than an exception?
3. If a third provider arrived tomorrow, which files would change? (The answer should be: one new file.)
