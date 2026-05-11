# astrbot_plugin_tts_tool

一个面向 AstrBot 的 TTS 插件，注册了可供 LLM 直接调用的工具 `generate_tts_audio`。

当前支持两条语音生成链路：

- Google Vertex AI Gemini TTS
- OpenRouter `/api/v1/audio/speech`

## 功能特点

- 统一的 `LLM_TOOL` 接口，`provider`、`model`、`voice` 仅由插件配置决定
- 支持 Vertex AI 的 Gemini TTS 模型，如 `gemini-2.5-flash-tts`
- 支持 OpenRouter 的 TTS 接口和语音模型
- 可选自动把生成好的音频直接发送到当前会话
- 工具返回 `mcp.types.AudioContent`，便于上层 Agent 继续消费

## 安装

将此目录放到 AstrBot 的 `data/plugins/` 下，然后在控制台启用插件并填写配置。

本插件不额外引入新依赖，依赖 AstrBot 主仓库现有的：

- `google-genai`
- `aiohttp`

## 配置说明

### 1. 通用配置

- `default_provider`: 默认提供商，`vertex` 或 `openrouter`
- `timeout`: 外部接口超时秒数
- `max_chars`: 单次最大文本长度
- `send_audio_to_user`: 工具成功后是否自动向当前会话发送语音

### 2. Vertex AI 配置

需要填写：

- `enabled = true`
- 上传 `credentials` 服务账号 JSON 文件
- `project`
- `location`

推荐默认值：

- `model = gemini-2.5-flash-tts`
- `voice = Kore`

说明：

- 插件当前通过 `google-genai` SDK 以 `vertexai=True` 调用 Vertex AI
- Vertex 返回的音频在插件内封装为 `.wav` 文件发送和返回

### 3. OpenRouter 配置

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

## LLM Tool

工具名：

```text
generate_tts_audio
```

参数：

- `text`: 要朗读的文本
- `instruction`: 控制语气、风格、节奏，当前主要用于 Vertex
- `language_code`: Vertex 的语言代码，如 `en-US`
- `speed`: 当默认提供商为 OpenRouter 时可用于控制播放速度

说明：

- LLM 不能在工具调用时选择 `provider`
- LLM 不能在工具调用时选择 `model`
- LLM 不能在工具调用时选择 `voice`
- 这些都必须由插件配置预先决定

## 使用建议

- 想要更自然的朗读风格时，优先使用 Vertex，并传入 `instruction`
- 想直接兼容 OpenAI 风格的音频接口时，使用 OpenRouter
- OpenRouter 若使用 `pcm`，不同模型返回的原始音频参数可能并不一致，生产环境建议优先 `mp3`

## 已知限制

- 当前工具接口按最小可用范围实现，聚焦单段文本转单段语音
- `instruction` 对 OpenRouter 不做统一语义映射，因为不同底层提供商支持差异较大
- 当前未实现多说话人对话式 TTS 参数封装
