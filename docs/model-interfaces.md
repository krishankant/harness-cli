# Model interfaces: OpenAI vs Anthropic

Week 1 asks you to read the Claude and OpenAI tool-use docs side by side and write down every place they differ. This page is that list, written out. It covers three wire formats:

- **Anthropic Messages API** (`POST /v1/messages`). harnessy's `AnthropicModel` uses it.
- **OpenAI Chat Completions** (`POST /v1/chat/completions`). harnessy's `OpenAIModel` uses it, and so does any OpenAI-compatible server such as Ollama.
- **OpenAI Responses API** (`POST /v1/responses`). This is OpenAI's newer API, and OpenAI recommends it for new projects. harnessy doesn't use it yet; see [section 10](#10-why-harnessy-uses-chat-completions).

A short Gemini note is at the end.

The examples are raw JSON, as it goes over the wire. The SDKs wrap these shapes, but they don't change them.

## 1. The differences at a glance

| | Anthropic Messages | OpenAI Chat Completions | OpenAI Responses |
| --- | --- | --- | --- |
| **Conversation field** | `messages` | `messages` | `input` (a string or a list of items) |
| **System prompt** | Top-level `system` | A message with `role: "system"` (or `"developer"`) | Top-level `instructions` |
| **Roles** | `user`, `assistant` | `system`/`developer`, `user`, `assistant`, `tool` | Items: `message` (with a role), `function_call`, `function_call_output`, `reasoning`, … |
| **Message content** | A string, or a list of typed blocks | A string, or a list of parts | A list of typed items |
| **Max output** | `max_tokens` (**required**) | `max_completion_tokens` (optional) | `max_output_tokens` (optional) |
| **Tool definition** | `{name, description, input_schema}` | `{type: "function", function: {name, description, parameters}}` | `{type: "function", name, description, parameters, strict}` |
| **A tool call** | A `tool_use` block inside the assistant `content` | An entry in `message.tool_calls`, beside `content` | Its own `function_call` item in `output` |
| **Call arguments** | `input`: a JSON **object** | `function.arguments`: a JSON **string** | `arguments`: a JSON **string** |
| **Call id** | `id` (`toolu_…`) | `id` (`call_…`) | `call_id` (`call_…`), plus a separate item `id` (`fc_…`) |
| **A tool result** | A `tool_result` block in a **user** message | A message with `role: "tool"`, one per call | A `function_call_output` item |
| **Error flag on results** | `is_error: true` | None (say so in the text) | None (say so in the text) |
| **Why it stopped** | `stop_reason` | `choices[0].finish_reason` | `status` plus `incomplete_details.reason`, and whether `output` has a `function_call` |
| **Tokens** | `usage.input_tokens` / `output_tokens` | `usage.prompt_tokens` / `completion_tokens` | `usage.input_tokens` / `output_tokens` |
| **State** | Stateless: you send the whole history | Stateless: you send the whole history | Either. Send the history, or chain turns with `previous_response_id` |
| **Reasoning you must send back** | `thinking` blocks (with a `signature`) in the assistant content | None is returned | `reasoning` items (or `encrypted_content` when `store: false`) |
| **Streaming** | Typed events (`content_block_delta`, …) | `chat.completion.chunk` objects with a `delta` | Typed events (`response.output_text.delta`, …) |

The rest of this page explains each row with examples.

## 2. One full tool round trip, three ways

The task: "What's the weather in Paris?" The model calls `get_weather`, the harness runs it, and the model answers. Every provider needs three requests' worth of content: the user's question, the model's tool call, and your tool result.

### Anthropic Messages

**Request 1:**

```json
{
  "model": "claude-opus-5",
  "max_tokens": 1024,
  "system": "You are a concise assistant.",
  "tools": [
    {
      "name": "get_weather",
      "description": "Get the current weather for a city. Call this whenever the user asks about weather.",
      "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"]
      }
    }
  ],
  "messages": [
    {"role": "user", "content": "What's the weather in Paris?"}
  ]
}
```

**Response 1:** the tool call is a block inside `content`, next to any text.

```json
{
  "id": "msg_01...",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Let me check."},
    {"type": "tool_use", "id": "toolu_01A", "name": "get_weather", "input": {"city": "Paris"}}
  ],
  "stop_reason": "tool_use",
  "usage": {"input_tokens": 412, "output_tokens": 58}
}
```

**Request 2:** send the assistant `content` back **unchanged**, then a **user** message holding the result.

```json
"messages": [
  {"role": "user", "content": "What's the weather in Paris?"},
  {"role": "assistant", "content": [
    {"type": "text", "text": "Let me check."},
    {"type": "tool_use", "id": "toolu_01A", "name": "get_weather", "input": {"city": "Paris"}}
  ]},
  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01A", "content": "18°C, light rain"}
  ]}
]
```

### OpenAI Chat Completions

**Request 1:** the system prompt is just the first message.

```json
{
  "model": "<your model>",
  "messages": [
    {"role": "system", "content": "You are a concise assistant."},
    {"role": "user", "content": "What's the weather in Paris?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city. Call this whenever the user asks about weather.",
        "parameters": {
          "type": "object",
          "properties": {"city": {"type": "string"}},
          "required": ["city"]
        }
      }
    }
  ]
}
```

**Response 1:** the calls sit in `tool_calls`, beside `content`. `arguments` is a **string** you have to parse.

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {"id": "call_abc", "type": "function",
         "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}}
      ]
    },
    "finish_reason": "tool_calls"
  }],
  "usage": {"prompt_tokens": 98, "completion_tokens": 17, "total_tokens": 115}
}
```

**Request 2:** send the assistant message back, then **one `tool` message per call**. A user message doesn't carry results here.

```json
"messages": [
  {"role": "system", "content": "You are a concise assistant."},
  {"role": "user", "content": "What's the weather in Paris?"},
  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_abc", "type": "function",
     "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_abc", "content": "18°C, light rain"}
]
```

### OpenAI Responses

**Request 1:** the system prompt is `instructions`, and the tool definition is flat, with no nested `function` object.

```json
{
  "model": "<your model>",
  "instructions": "You are a concise assistant.",
  "input": [{"role": "user", "content": "What's the weather in Paris?"}],
  "tools": [
    {
      "type": "function",
      "name": "get_weather",
      "description": "Get the current weather for a city. Call this whenever the user asks about weather.",
      "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": false
      },
      "strict": true
    }
  ]
}
```

**Response 1:** `output` is a list of items. A tool call is an item of its own, not part of a message.

```json
{
  "id": "resp_...",
  "object": "response",
  "status": "completed",
  "output": [
    {"type": "reasoning", "id": "rs_...", "summary": []},
    {"type": "function_call", "id": "fc_...", "call_id": "call_abc",
     "name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}
  ],
  "usage": {"input_tokens": 98, "output_tokens": 17, "total_tokens": 115}
}
```

**Request 2:** there are two ways to send the result.

```json
{
  "model": "<your model>",
  "previous_response_id": "resp_...",
  "input": [
    {"type": "function_call_output", "call_id": "call_abc", "output": "18°C, light rain"}
  ]
}
```

- **The way shown above** lets the server keep the history, so you send only the new item.
- **The stateless way:** send `store: false`, and put the whole history in `input`. That means the user message, the `reasoning` item, the `function_call` item and the `function_call_output` item.

## 3. Messages and roles

**Anthropic** has two roles: `user` and `assistant`.
- Everything the harness says goes in a `user` message. That includes a tool result, which is a block in a user message.
- `system` is a top-level field, never a message. It's a string, or a list of text blocks if you want to put `cache_control` on part of it.
- Content is a string or a list of blocks: `text`, `image`, `document`, `tool_use`, `tool_result`, `thinking` and others.

**Chat Completions** puts everything in one list of messages.
- **The system prompt** is a message with `role: "system"`. Newer OpenAI models also accept `role: "developer"` for the same purpose.
- **Tool results** get their own role, `tool`.
- **Content** is a string or a list of parts (`{"type": "text", ...}`, `{"type": "image_url", ...}`).
- **An assistant message that only calls tools** has `content: null`.

**Responses** replaces messages with **items**.
- A `message` item still has a role.
- Tool calls, tool outputs, reasoning and built-in tool activity are each their own item type.
- `input` can also be a plain string for a one-shot question.
- **What harnessy would have to change:** a turn is no longer "one message with some calls attached"; it's a list of items. harnessy's `Message` type would map to several items.

## 4. Tool definitions

| | Anthropic | Chat Completions | Responses |
| --- | --- | --- | --- |
| Schema field | `input_schema` | `function.parameters` | `parameters` |
| Wrapper | None | `{"type": "function", "function": {...}}` | `{"type": "function", ...}` (flat) |
| Strict schema | `"strict": true` on the tool | `"strict": true` inside `function` | `"strict": true` (the default) |

All three take a JSON Schema for the arguments, so harnessy's `ToolSpec.parameters` passes through unchanged (`to_anthropic_tools` and `to_openai_tools` in `solutions/harnessy/models/`).

**Strict mode** means the model's arguments are guaranteed to match the schema.
- OpenAI requires `additionalProperties: false`, and every property listed in `required`. An optional field becomes `"type": ["string", "null"]`.
- Anthropic's strict mode also needs `additionalProperties: false`, and doesn't support some constraints, such as `minimum` and `maxLength`.
- Without strict mode, both providers *usually* send valid arguments but don't promise it. That's why harnessy's registry validates every call (week 3).

**Built-in tools** run on the provider's servers instead of in your harness.
- **Anthropic:** web search, web fetch and code execution. They show up as `server_tool_use` blocks and their result blocks.
- **Responses:** `web_search`, `file_search`, `code_interpreter` and others. They show up as their own item types.
- **Chat Completions** has almost none.
- harnessy only uses tools it runs itself, so it ignores all of these.

## 5. Tool calls and tool results

The differences that bite when you write an adapter:

1. **Arguments: object vs string.**
   - Anthropic's `input` is already an object.
   - OpenAI's `arguments` is a string of JSON, and it can be invalid JSON. Parse it defensively. harnessy's `_parse_arguments` keeps unparseable text as `{"_raw": ...}`, so the registry rejects the call with an error the model can read, instead of crashing the loop.
2. **Where results go.**
   - Anthropic: all results for one turn go in **one** user message, as `tool_result` blocks. They must come before any text in that message.
   - Chat Completions: **one `tool` message per call**, immediately after the assistant message that made the calls.
   - Responses: one `function_call_output` item per call.
3. **Linking by id.**
   - Anthropic: `tool_use.id` → `tool_result.tool_use_id`.
   - Chat Completions: `tool_calls[].id` → `tool_call_id`.
   - Responses: `function_call.call_id` → `function_call_output.call_id`. The `fc_…` item `id` is a different id; don't use it for linking.
   - Every call needs exactly one result. A missing result is a 400 on both providers.
4. **Errors.**
   - Anthropic has `is_error: true` on a `tool_result`.
   - OpenAI has no flag, so harnessy prefixes the content with `ERROR:` (`to_openai_messages`). Either way, a failed tool is a *result* the model sees, never an exception (week 3).
5. **Several calls in one turn.**
   - Both providers may ask for several tools at once.
   - **Turning it off:** Anthropic uses `tool_choice: {"type": "auto", "disable_parallel_tool_use": true}`; OpenAI uses `parallel_tool_calls: false`.
6. **Result content.**
   - Anthropic's `tool_result.content` can be a string or a list of blocks, including images.
   - OpenAI's `tool` message content is text. Responses' `output` is a string, or a list of content parts on newer models.

### `tool_choice`

| Meaning | Anthropic | Chat Completions / Responses |
| --- | --- | --- |
| Model decides (default) | `{"type": "auto"}` | `"auto"` |
| Must call some tool | `{"type": "any"}` | `"required"` |
| Must call this tool | `{"type": "tool", "name": "get_weather"}` | Chat: `{"type": "function", "function": {"name": "get_weather"}}`; Responses: `{"type": "function", "name": "get_weather"}` |
| No tools | `{"type": "none"}` | `"none"` |

Some of the newest Claude models (Opus 5.5, Fable 5.1) reject forced tool use (`any` and `tool`) with a 400. On those, use `auto` and say in the prompt which tool you expect.

## 6. Why the model stopped

harnessy maps every provider onto five values: `end_turn`, `tool_use`, `max_tokens`, `refused` and `error`.

| harnessy | Anthropic `stop_reason` | Chat `finish_reason` | Responses |
| --- | --- | --- | --- |
| `end_turn` | `end_turn`, `stop_sequence` | `stop` | `status: "completed"` with no `function_call` items |
| `tool_use` | `tool_use` | `tool_calls` | `status: "completed"` and at least one `function_call` item |
| `max_tokens` | `max_tokens` | `length` | `status: "incomplete"`, `incomplete_details.reason: "max_output_tokens"` |
| `refused` | `refusal` | `content_filter` | `incomplete_details.reason: "content_filter"` |
| `error` | anything else | anything else | `status: "failed"` (with `error`) |

Things that don't fit the table:
- **Anthropic `pause_turn`.** When Anthropic's *server* tools run a long loop, the response stops with `pause_turn`. You resume it by sending the conversation back as it is. harnessy doesn't use server tools, so it maps this to `error`.
- **OpenAI's `refusal` field.** A refusal can also arrive as `message.refusal` (Chat) or a `refusal` content part (Responses), with an ordinary `stop`/`completed`. Check for it if you use structured outputs.
- **Responses has no stop reason for tool calls.** You find out from the item types in `output`.

## 7. Reasoning ("thinking") across turns

Reasoning models think before they answer. In a tool loop, that thinking has to survive between the call and the result, or the model loses its plan.

**Anthropic.**
- The assistant `content` can include `thinking` blocks, each with a `signature`. On current models the visible text may be empty unless you ask for `display: "summarized"`.
- **You must send them back unchanged** in the assistant turn that holds the `tool_use`. The API checks the signature, so you can't edit them or make your own.
- This is why harnessy keeps `ProviderRaw` on every assistant message: `to_anthropic_messages` sends `m.raw.content` back as it came, instead of rebuilding it from `text` and `tool_calls`.
- **Thinking settings:**
  - Current models use `thinking: {"type": "adaptive"}`. On Claude Opus 5 that's also the default when you leave it out.
  - The old `{"type": "enabled", "budget_tokens": N}` is rejected on the newest models.

**Chat Completions.**
- OpenAI's reasoning models think, but Chat Completions doesn't return the reasoning, so there's nothing to send back.
- The reasoning is lost between turns, and the model re-reasons from the visible history. You still pay for it: `usage.completion_tokens_details.reasoning_tokens`.
- `reasoning_effort` (`"low"`, `"medium"`, `"high"`, …) sets how hard it thinks.

**Responses.**
- The output includes `reasoning` items, and you keep them across turns in one of two ways:
  - with `previous_response_id`, the server keeps them for you;
  - when you send the history yourself with `store: false`, request `include: ["reasoning.encrypted_content"]` and send the encrypted items back.
- The effort setting moves to `reasoning: {"effort": "medium"}`.

## 8. Tokens, caching and cost

| | Anthropic | Chat Completions | Responses |
| --- | --- | --- | --- |
| Input | `usage.input_tokens` | `usage.prompt_tokens` | `usage.input_tokens` |
| Output | `usage.output_tokens` | `usage.completion_tokens` | `usage.output_tokens` |
| Cache reads | `usage.cache_read_input_tokens` | `usage.prompt_tokens_details.cached_tokens` | `usage.input_tokens_details.cached_tokens` |
| Cache writes | `usage.cache_creation_input_tokens` | (not reported) | (not reported) |
| Reasoning | Counted in `output_tokens` | `usage.completion_tokens_details.reasoning_tokens` | `usage.output_tokens_details.reasoning_tokens` |

**Caching** works differently.
- **OpenAI** caches long prompt prefixes automatically. You get a discount on the cached part and change nothing in the request.
- **Anthropic** caches what you mark with `cache_control: {"type": "ephemeral"}`, on a tool, on the system prompt or on a message block. Writing to the cache costs a little more than normal input; reading it costs much less.
- **What a harness should do:** keep the start of the prompt stable (the system prompt, then the tools, then the history), so the prefix stays the same from one call to the next. harnessy's `ContextManager` (week 4) does that.

**Anthropic's input count doesn't include cached tokens.** `input_tokens` covers only the uncached input. To get the true prompt size, add `cache_read_input_tokens` and `cache_creation_input_tokens`. OpenAI's `prompt_tokens` already includes the cached part.

## 9. Streaming

**Anthropic** sends typed server-sent events:

```
message_start → content_block_start → content_block_delta … → content_block_stop → … → message_delta → message_stop
```

- **`content_block_delta`** carries a `text_delta`, an `input_json_delta` (a fragment of a tool's arguments) or a `thinking_delta`.
- **`message_delta`** carries the `stop_reason` and the final usage.
- **The SDK** puts these back together for you: `stream.get_final_message()`.

**Chat Completions** sends `chat.completion.chunk` objects.
- Each chunk has `choices[0].delta`, which can hold some `content` or fragments of `tool_calls`.
- **Tool calls** arrive in pieces keyed by `index`. The first piece has the `id` and `name`, and later pieces add to `function.arguments`.
- **Usage** arrives in one last chunk with empty `choices`, and only if you ask with `stream_options: {"include_usage": true}`.
- Putting these back together is your job: that's week 7's `merge_openai_chunks`.

**Responses** sends typed events:
- `response.created`
- `response.output_item.added`
- `response.output_text.delta`
- `response.function_call_arguments.delta` and `.done`
- `response.output_item.done`
- `response.completed`

Each event names the item it belongs to, so you don't have to rebuild anything by `index`.

## 10. Why harnessy uses Chat Completions

The OpenAI adapter speaks Chat Completions, not Responses, for three reasons:

1. **It's the shared format.** Ollama, vLLM, LM Studio, OpenRouter and most other local or hosted servers accept Chat Completions at `/v1/chat/completions`. One adapter covers all of them through `OPENAI_BASE_URL`, which is what week 1's Ollama path relies on.
2. **It's stateless,** like Anthropic's API. The harness owns the history, so tracing, compaction and evals (weeks 4 and 5) see everything.
3. **It's easier to learn from.** One message with optional tool calls lines up well with harnessy's `Message`.

**The cost** is that reasoning isn't carried between turns on OpenAI reasoning models, and built-in tools aren't available.

A Responses adapter is a good stretch exercise. It would:
- emit a `function_call` and a `function_call_output` item per call;
- keep the `reasoning` items in `ProviderRaw` (the same way Anthropic thinking blocks are kept);
- decide `tool_use` from the item types in `output`.

Nothing outside `models/` would change.

## 11. Gemini, briefly

Google's `generateContent` API is a third shape, closer to Anthropic's than OpenAI's:

- **Messages:**
  - The conversation is `contents`, a list of `{role, parts}` objects. The roles are `user` and `model`, not `assistant`.
  - The system prompt is a top-level `systemInstruction`.
- **Tools:** `tools: [{"functionDeclarations": [{name, description, parameters}]}]`.
- **Tool calls:**
  - A call is a part, `{"functionCall": {"name": ..., "args": {...}}}`. Like Anthropic, the arguments are an object.
  - The result goes back as a `user` part, `{"functionResponse": {"name": ..., "response": {...}}}`.
  - Results are matched by **name** (newer versions also add ids). The result is a JSON object, not a string.
- **Forcing tools:** `toolConfig.functionCallingConfig.mode` is `AUTO`, `ANY` or `NONE`.
- **Stop and usage:**
  - Why it stopped: `candidates[0].finishReason` (`STOP`, `MAX_TOKENS`, `SAFETY`, …).
  - Tokens: `usageMetadata.promptTokenCount` and `candidatesTokenCount`.
- **Reasoning:** thinking models return signatures that must be sent back unchanged, the same rule as Anthropic's thinking blocks.
- **The shortcut:** Gemini also offers an OpenAI-compatible endpoint, so harnessy's OpenAI adapter can talk to it through `OPENAI_BASE_URL`.

## Sources

- Anthropic: [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works), [Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons), [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- OpenAI: [Function calling](https://developers.openai.com/api/docs/guides/function-calling), [Migrating to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses), [Streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- Gemini: [Function calling](https://ai.google.dev/gemini-api/docs/function-calling), [Thinking](https://ai.google.dev/gemini-api/docs/thinking)
- Ollama: [/api/chat](https://docs.ollama.com/api/chat), [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- In this repo: `solutions/harnessy/models/anthropic.py`, `openai.py`, `openai_stream.py`, and `harnessy/types.py`
