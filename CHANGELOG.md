# Changelog

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
