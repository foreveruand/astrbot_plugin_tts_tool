# astrbot_plugin_tts_tool

一个面向 AstrBot 的 TTS 插件，注册了可供 LLM 直接调用的工具 `generate_tts_audio`。

当前支持三条语音生成链路：

- Google Vertex AI Gemini TTS
- xAI Grok TTS `/v1/tts`
- OpenRouter `/api/v1/audio/speech`

## 功能特点

- 统一的 `LLM_TOOL` 接口，`provider`、`model`、`voice` 仅由插件配置决定
- 支持 Vertex AI 的 Gemini TTS 模型，如 `gemini-2.5-flash-tts`
- 支持 xAI 原生 Grok TTS 接口与自定义 voice
- 支持 OpenRouter 的 TTS 接口和语音模型
- 自动将 Gemini / Grok 相关提示 skill 安装到 AstrBot 的 `data/skills/tts_tool_gemini_grok_prompting/`
- 可选自动把生成好的音频直接发送到当前会话
- 自动将 Gemini 与 PCM 原始音频封装为可播放的 `.wav`，避免 Telegram 无法播放裸 PCM
- 工具返回 `mcp.types.AudioContent`，便于上层 Agent 继续消费

## 安装

将此目录放到 AstrBot 的 `data/plugins/` 下，然后在控制台启用插件并填写配置。

本插件不额外引入新依赖，依赖 AstrBot 主仓库现有的：

- `google-genai`
- `httpx[socks]`

## 配置说明

### 1. 通用配置

- `default_provider`: 默认提供商，`vertex`、`xai` 或 `openrouter`
- `timeout`: 外部接口超时秒数
- `proxy_url`: 可选代理地址，支持 `http://host:port` 与 `socks5://host:port`
- `max_chars`: 单次最大文本长度
- `send_audio_to_user`: 工具成功后是否自动向当前会话发送语音

说明：

- `proxy_url` 会同时作用于 Vertex AI、xAI 与 OpenRouter 请求
- 当前仅支持 `http` 和 `socks5` 两种代理 scheme
- 需填写完整地址和端口，例如 `http://127.0.0.1:7890`、`socks5://127.0.0.1:1080`

### 2. Vertex AI 配置

需要填写：

- `enabled = true`
- 上传 `credentials` 服务账号 JSON 文件
- `project`
- `location`

推荐默认值：

- `model = gemini-2.5-flash-tts`
- `voice = Kore`
- `safety_threshold = BLOCK_MEDIUM_AND_ABOVE`
- `safety_method = PROBABILITY`

说明：

- 插件当前通过 `google-genai` SDK 以 `vertexai=True` 调用 Vertex AI
- 可通过 `safety_threshold` 调整 Gemini 安全过滤强度，支持 `BLOCK_LOW_AND_ABOVE`、`BLOCK_MEDIUM_AND_ABOVE`、`BLOCK_ONLY_HIGH`、`BLOCK_NONE`、`OFF`
- 可通过 `safety_method` 选择 `PROBABILITY` 或 `SEVERITY`
- 当前安全过滤配置会统一应用到 `harassment`、`hate speech`、`sexually explicit`、`dangerous content` 四类文本内容
- Vertex 返回的 PCM 音频会在插件内封装为 `.wav` 文件发送和返回
- 插件启用时会自动安装并激活 skill：`tts_tool_gemini_grok_prompting`
- 当 Vertex 偶发返回无音频结果时，插件会自动重试最多 3 次，并在失败日志中附带 `response_id`、候选数量、`finish_reason`、`prompt_feedback`、prompt/candidate safety 等诊断信息

### 3. xAI 配置

需要填写：

- `api_key`

可选配置：

- `base_url`，默认 `https://api.x.ai/v1`
- `voice_id`
- `language`
- `codec`
- `sample_rate`
- `bit_rate`

推荐默认值：

- `voice_id = eve`
- `language = auto`
- `codec = mp3`
- `sample_rate = 24000`
- `bit_rate = 128000`

说明：

- 插件按 xAI 文档调用 `POST /v1/tts`
- 请求字段使用 xAI 原生格式：`text`、`voice_id`、`language`、`output_format`
- 工具调用时若传入 `language_code`，会优先覆盖 `xai_config.language`
- 当前 schema 只暴露 `mp3` 与 `wav` 两种常用 `codec`，避免把不常见编码直接暴露给上层 LLM
- `voice_id` 可以是 xAI 内置 voice，也可以是自定义 voice id

### 4. OpenRouter 配置

需要填写：

- `api_key`

可选配置：

- `base_url`，默认 `https://openrouter.ai/api/v1`
- `model`
- `voice`
- `response_format`
- `http_referer`
- `x_title`
- `extra_body`

推荐默认值：

- `model = openai/gpt-4o-mini-tts-2025-12-15`
- `voice = alloy`
- `response_format = mp3`

`extra_body` 用于附加 OpenRouter 扩展字段，请填写 JSON object。例如配置 provider fallback：

```json
{
  "provider": {
    "order": ["openai", "azure"],
    "allow_fallbacks": true
  }
}
```

说明：

- 该字段会原样并入 OpenRouter 的请求体
- 仅适合放 OpenRouter 扩展参数，如 `provider`
- 不能覆盖这些核心字段：`model`、`input`、`voice`、`response_format`、`speed`
- 当 `response_format = pcm` 时，插件会自动将返回结果封装为 `.wav` 再发送给 Telegram / AstrBot

## LLM Tool

工具名：

```text
generate_tts_audio
```

参数：

- `text`: 要朗读的文本
- `instruction`: 控制语气、风格、节奏，当前主要用于 Vertex，可写更长的导演说明
- `gemini_tone`: Gemini / Vertex 专用的简短语气提示，例如 `calm documentary narrator`
- `language_code`: Vertex 或 xAI 的语言代码，如 `en-US`、`zh-CN`、`zh`、`auto`
- `speed`: 当默认提供商为 OpenRouter 时可用于控制播放速度

说明：

- LLM 不能在工具调用时选择 `provider`
- LLM 不能在工具调用时选择 `model`
- LLM 不能在工具调用时选择 `voice`
- 这些都必须由插件配置预先决定
- 当默认提供商为 Vertex/Gemini 或 xAI/Grok 时，推荐配合自动安装的 `tts_tool_gemini_grok_prompting` skill 一起使用

## 使用建议

- 想要更自然的朗读风格时，优先使用 Vertex，并优先传入 `gemini_tone`
- 想使用 xAI Grok 官方 TTS 接口或自定义 voice 时，使用 xAI provider
- 当需要复杂的停顿、情绪或强调控制时，再额外传入 `instruction`
- 想直接兼容 OpenAI 风格的音频接口时，使用 OpenRouter
- OpenRouter 若使用 `pcm`，插件会自动封装为 `.wav`；若无需原始 PCM，生产环境仍建议优先 `mp3`
- Grok 也支持音频标签，但写法与 Gemini 不完全一致：xAI 文档里既有 `[pause]` 这类插入型标签，也有 `<whisper>...</whisper>` 这类包裹标签

## 已知限制

- 当前工具接口按最小可用范围实现，聚焦单段文本转单段语音
- `instruction` 对 OpenRouter 不做统一语义映射，因为不同底层提供商支持差异较大
- `instruction` 与 `gemini_tone` 目前不对 xAI 做额外结构化映射，Grok 的细粒度控制建议直接写进 `text` 的音频标签中
- 当前未实现多说话人对话式 TTS 参数封装
- 若某些第三方 OpenRouter 模型返回的 PCM 采样参数与 OpenAI 兼容约定不一致，生成出的 `.wav` 仍可能需要改回 `mp3` 以确保兼容
