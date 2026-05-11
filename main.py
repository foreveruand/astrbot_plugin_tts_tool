"""AstrBot TTS tool plugin."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
import wave
from io import BytesIO
from pathlib import Path

import aiohttp
import mcp.types
from google import genai
from google.genai import types
from google.oauth2 import service_account

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

PLUGIN_NAME = "astrbot_plugin_tts_tool"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash-tts"
DEFAULT_VERTEX_VOICE = "Kore"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini-tts-2025-12-15"
DEFAULT_OPENROUTER_VOICE = "alloy"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_RESERVED_FIELDS = {
    "model",
    "input",
    "voice",
    "response_format",
    "speed",
}


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    *,
    channels: int = 1,
    sample_rate: int = 24000,
    sample_width: int = 2,
) -> bytes:
    """Wrap LINEAR16 PCM bytes into a WAV container."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


def _guess_suffix(mime_type: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return ".mp3"
    if normalized in {"audio/ogg", "audio/opus", "audio/ogg; codecs=opus"}:
        return ".ogg"
    return ".wav"


def _normalize_openrouter_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_OPENROUTER_BASE_URL
    if url.endswith("/api/v1"):
        return url
    if url.endswith("/api"):
        return f"{url}/v1"
    return f"{url}/api/v1"


def _extract_error_message(payload_text: str) -> str:
    try:
        payload = json.loads(payload_text)
    except Exception:
        return payload_text.strip() or "Unknown error"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
        if isinstance(error, str):
            return error
        message = payload.get("message")
        if message:
            return str(message)

    return payload_text.strip() or "Unknown error"


def _parse_json_object_config(raw_value: str, field_name: str) -> dict[str, object]:
    text = (raw_value or "").strip()
    if not text:
        return {}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{field_name} must be a JSON object")

    return payload


class VertexTTSAdapter:
    """Google Vertex AI Gemini TTS adapter."""

    def __init__(self, credentials_path: str, project: str, location: str) -> None:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
        )

    async def synthesize(
        self,
        *,
        text: str,
        model: str,
        voice: str,
        instruction: str | None,
        language_code: str | None,
    ) -> tuple[bytes, str]:
        prompt = text.strip()
        if instruction and instruction.strip():
            prompt = f"{instruction.strip()}\n\n{prompt}"

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                languageCode=(language_code or "").strip() or None,
                voiceConfig=types.VoiceConfig(
                    prebuiltVoiceConfig=types.PrebuiltVoiceConfig(voiceName=voice)
                ),
            ),
        )

        def _run_generation() -> bytes:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                raise RuntimeError("Vertex AI returned no candidates")

            parts = getattr(candidates[0].content, "parts", None) or []
            if not parts:
                raise RuntimeError("Vertex AI returned no audio parts")

            inline_data = getattr(parts[0], "inline_data", None)
            if inline_data is None or getattr(inline_data, "data", None) is None:
                raise RuntimeError("Vertex AI response does not contain audio data")

            data = inline_data.data
            if isinstance(data, str):
                return base64.b64decode(data)
            return bytes(data)

        pcm_data = await asyncio.to_thread(_run_generation)
        return _pcm_to_wav_bytes(pcm_data), "audio/wav"


class OpenRouterTTSAdapter:
    """OpenRouter speech adapter."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int,
        referer: str = "",
        title: str = "",
        response_format: str = "mp3",
    ) -> None:
        self.api_key = api_key
        self.base_url = _normalize_openrouter_base_url(base_url)
        self.timeout = timeout
        self.referer = referer.strip()
        self.title = title.strip()
        self.response_format = (response_format or "mp3").strip().lower() or "mp3"

    async def synthesize(
        self,
        *,
        text: str,
        model: str,
        voice: str,
        speed: float | None,
        extra_body: dict[str, object] | None = None,
    ) -> tuple[bytes, str]:
        payload: dict[str, object] = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": self.response_format,
        }
        if speed is not None:
            payload["speed"] = speed
        if extra_body:
            payload.update(extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        endpoint = f"{self.base_url}/audio/speech"

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    error_text = await resp.text()
                    raise RuntimeError(
                        f"OpenRouter API error ({resp.status}): "
                        f"{_extract_error_message(error_text)}"
                    )

                audio_bytes = await resp.read()
                if not audio_bytes:
                    raise RuntimeError("OpenRouter returned an empty audio response")

                mime_type = resp.headers.get("Content-Type", "audio/mpeg")
                return audio_bytes, mime_type


class Main(Star):
    """Expose a unified TTS LLM tool."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.context = context
        self.config = config

    async def initialize(self) -> None:
        tool_mgr = self.context.get_llm_tool_manager()
        tool = tool_mgr.get_func("generate_tts_audio")
        if tool:
            desc = self._tool_config("tool_description", "").strip()
            if desc:
                tool.description = desc
        logger.info("[tts_tool] Plugin initialized")

    async def terminate(self) -> None:
        logger.info("[tts_tool] Plugin terminated")

    def _config_get(self, section: str, key: str, default=None):
        section_data = self.config.get(section, {})
        if isinstance(section_data, dict) and key in section_data:
            return section_data.get(key, default)
        return default

    def _tool_config(self, key: str, default=None):
        return self._config_get("tool_config", key, default)

    def _general_config(self, key: str, default=None):
        return self._config_get("general_config", key, default)

    def _vertex_config(self, key: str, default=None):
        return self._config_get("vertex_config", key, default)

    def _openrouter_config(self, key: str, default=None):
        return self._config_get("openrouter_config", key, default)

    def _get_plugin_data_dir(self) -> Path:
        return Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME

    def _resolve_plugin_data_file(self, file_path: str | None) -> Path | None:
        if not file_path:
            return None

        candidate = Path(file_path)
        if candidate.is_absolute():
            return candidate
        return (self._get_plugin_data_dir() / candidate).resolve(strict=False)

    def _get_output_dir(self) -> Path:
        output_dir = self._get_plugin_data_dir() / "generated_audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _is_provider_configured(self, provider: str) -> bool:
        if provider == "vertex":
            credentials_files = self._vertex_config("credentials", [])
            credentials_path = self._resolve_plugin_data_file(
                credentials_files[0] if credentials_files else None
            )
            return bool(
                self._vertex_config("enabled", False)
                and credentials_path
                and credentials_path.is_file()
                and self._vertex_config("project", "").strip()
            )

        if provider == "openrouter":
            return bool(self._openrouter_config("api_key", "").strip())

        return False

    def _resolve_tool_provider(self, requested_provider: str | None) -> str:
        default_provider = self._general_config("default_provider", "vertex")
        normalized = (requested_provider or "").strip().lower()
        if normalized not in {"vertex", "openrouter"}:
            normalized = default_provider

        if self._is_provider_configured(normalized):
            return normalized

        if self._is_provider_configured(default_provider):
            logger.info(
                "[tts_tool] Requested provider %s not configured; fallback to %s",
                normalized,
                default_provider,
            )
            return default_provider

        return normalized

    def _get_vertex_adapter(self) -> VertexTTSAdapter:
        credentials_files = self._vertex_config("credentials", [])
        credentials_path = self._resolve_plugin_data_file(
            credentials_files[0] if credentials_files else None
        )
        if not credentials_path or not credentials_path.is_file():
            raise ValueError("Vertex AI service account JSON file is not configured")

        project = self._vertex_config("project", "").strip()
        if not project:
            raise ValueError("Vertex AI project is not configured")

        return VertexTTSAdapter(
            credentials_path=str(credentials_path),
            project=project,
            location=self._vertex_config("location", "us-central1"),
        )

    def _get_openrouter_adapter(self) -> OpenRouterTTSAdapter:
        api_key = self._openrouter_config("api_key", "").strip()
        if not api_key:
            raise ValueError("OpenRouter API key is not configured")

        return OpenRouterTTSAdapter(
            api_key=api_key,
            base_url=self._openrouter_config("base_url", DEFAULT_OPENROUTER_BASE_URL),
            timeout=self._general_config("timeout", 120),
            referer=self._openrouter_config("http_referer", ""),
            title=self._openrouter_config("x_title", ""),
            response_format=self._openrouter_config("response_format", "mp3"),
        )

    def _build_output_path(self, mime_type: str) -> Path:
        suffix = _guess_suffix(mime_type)
        return self._get_output_dir() / f"tts_{uuid.uuid4().hex}{suffix}"

    async def _send_audio_output(
        self, event: AstrMessageEvent, output_path: Path, original_text: str
    ) -> None:
        record = Comp.Record.fromFileSystem(str(output_path), text=original_text)
        await event.send(event.chain_result([record]))

    @filter.llm_tool(name="generate_tts_audio")
    async def generate_tts_audio(
        self,
        event: AstrMessageEvent,
        text: str,
        provider: str | None = None,
        voice: str | None = None,
        model: str | None = None,
        instruction: str | None = None,
        language_code: str | None = None,
        speed: float | None = None,
    ) -> str | mcp.types.CallToolResult:
        """将文本转换为语音音频，供 LLM 生成可发送给用户的 TTS 结果。

        Args:
            text(string): 要朗读的文本内容。
            provider(string): 可选。使用的提供商，可选 vertex 或 openrouter。
            voice(string): 可选。音色名称。Vertex 默认 Kore，OpenRouter 默认 alloy。
            model(string): 可选。模型名称。Vertex 默认 gemini-2.5-flash-tts，OpenRouter 默认 openai/gpt-4o-mini-tts-2025-12-15。
            instruction(string): 可选。仅对 Vertex AI 明确生效，用于控制语气、风格、节奏等朗读方式。
            language_code(string): 可选。Vertex AI 的语言代码，例如 en-US、zh-CN。
            speed(number): 可选。OpenRouter 的播放速度倍率；不支持的模型会忽略。
        """
        only_admin = self._tool_config("only_admin", True)
        if only_admin and not event.is_admin:
            return "Permission denied: this TTS tool is restricted to admins."

        normalized_text = (text or "").strip()
        if not normalized_text:
            return "错误：text 不能为空。"

        max_chars = int(self._general_config("max_chars", 4000))
        if len(normalized_text) > max_chars:
            return f"错误：文本长度超过限制，当前最多支持 {max_chars} 个字符。"

        resolved_provider = self._resolve_tool_provider(provider)
        if resolved_provider == "vertex":
            if not self._is_provider_configured("vertex"):
                return "错误：未配置可用的 Vertex AI 凭证或项目 ID。"
            resolved_model = (
                model or self._vertex_config("model", DEFAULT_VERTEX_MODEL)
            ).strip()
            resolved_voice = (
                voice or self._vertex_config("voice", DEFAULT_VERTEX_VOICE)
            ).strip()
        elif resolved_provider == "openrouter":
            if not self._is_provider_configured("openrouter"):
                return "错误：未配置 OpenRouter API Key。"
            resolved_model = (
                model or self._openrouter_config("model", DEFAULT_OPENROUTER_MODEL)
            ).strip()
            resolved_voice = (
                voice or self._openrouter_config("voice", DEFAULT_OPENROUTER_VOICE)
            ).strip()
        else:
            return f"错误：不支持的 provider: {resolved_provider}"

        try:
            if resolved_provider == "vertex":
                adapter = self._get_vertex_adapter()
                audio_bytes, mime_type = await adapter.synthesize(
                    text=normalized_text,
                    model=resolved_model,
                    voice=resolved_voice,
                    instruction=instruction,
                    language_code=language_code,
                )
            else:
                adapter = self._get_openrouter_adapter()
                extra_body = _parse_json_object_config(
                    self._openrouter_config("extra_body", ""),
                    "openrouter_config.extra_body",
                )
                conflicting_keys = OPENROUTER_RESERVED_FIELDS.intersection(extra_body)
                if conflicting_keys:
                    joined_keys = ", ".join(sorted(conflicting_keys))
                    raise ValueError(
                        "openrouter_config.extra_body contains reserved fields: "
                        f"{joined_keys}"
                    )
                audio_bytes, mime_type = await adapter.synthesize(
                    text=normalized_text,
                    model=resolved_model,
                    voice=resolved_voice,
                    speed=speed,
                    extra_body=extra_body,
                )

            output_path = self._build_output_path(mime_type)
            output_path.write_bytes(audio_bytes)

            if self._general_config("send_audio_to_user", True):
                await self._send_audio_output(event, output_path, normalized_text)

            return mcp.types.CallToolResult(
                content=[
                    mcp.types.TextContent(
                        type="text",
                        text=(
                            f"TTS generation succeeded. provider={resolved_provider}, "
                            f"model={resolved_model}, voice={resolved_voice}, "
                            f"path={output_path}"
                        ),
                    ),
                    mcp.types.AudioContent(
                        type="audio",
                        data=base64.b64encode(audio_bytes).decode("utf-8"),
                        mimeType=mime_type.split(";", 1)[0].strip(),
                    ),
                ]
            )
        except Exception as exc:
            logger.error("[tts_tool] synthesis failed: %s", exc, exc_info=True)
            return f"语音生成失败：{exc}"
