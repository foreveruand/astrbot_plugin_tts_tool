# Changelog

## 0.2.2 - 2026-05-15

- Add `general_config.proxy_url` for outbound TTS requests
- Support both `http://host:port` and `socks5://host:port` proxy formats
- Apply the configured proxy to both Vertex AI Gemini TTS and OpenRouter speech requests

## 0.2.1 - 2026-05-15

- Retry transient Vertex no-audio responses up to 3 times before failing
- Add detailed Vertex diagnostics including finish reason, prompt feedback, safety signals, and text preview when no audio is returned
- Simplify Gemini/Vertex prompt composition to better match official speech generation guidance

## 0.2.0 - 2026-05-15

- Convert Gemini PCM responses to playable WAV output and also wrap OpenRouter PCM output into WAV for Telegram compatibility
- Add the `gemini_tone` tool parameter for short Gemini speaking-style guidance
- Concatenate all Gemini audio parts instead of reading only the first inline audio chunk, reducing truncated output risk
- Auto-install and activate the `tts_tool_gemini_prompting` skill in AstrBot `data/skills`
- Update README usage notes for Gemini prompting and PCM playback behavior

## 0.1.2 - 2026-05-11

- Remove `provider`, `model`, and `voice` from the exposed LLM tool arguments
- Force provider, model, and voice selection to come only from plugin configuration
- Keep automatic fallback to the other configured provider when the default provider is unavailable

## 0.1.1 - 2026-05-11

- Add `openrouter_config.extra_body` for attaching extra OpenRouter request parameters
- Support OpenRouter provider fallback style payloads such as `provider`
- Reject reserved field overrides in `extra_body` to keep core tool arguments stable

## 0.1.0 - 2026-05-11

- Initial release of the AstrBot TTS LLM tool plugin
- Add Google Vertex AI Gemini TTS support
- Add OpenRouter `/api/v1/audio/speech` support
- Return generated audio as `mcp.types.AudioContent`
- Support optional auto-send of generated audio to the current conversation
