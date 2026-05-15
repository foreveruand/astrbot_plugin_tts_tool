"""AstrBot TTS tool plugin."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
import wave
from collections.abc import Iterable
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
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_skills_path,
)

PLUGIN_NAME = "astrbot_plugin_tts_tool"
PLUGIN_DIR = Path(__file__).resolve().parent
SKILL_NAME = "tts_tool_gemini_prompting"
SKILL_SOURCE_PATH = PLUGIN_DIR / "skills" / SKILL_NAME / "SKILL.md"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash-tts"
DEFAULT_VERTEX_VOICE = "Kore"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini-tts-2025-12-15"
DEFAULT_OPENROUTER_VOICE = "alloy"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PCM_SAMPLE_RATE = 24000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2
VERTEX_MAX_RETRIES = 3
OPENROUTER_RESERVED_FIELDS = {
    "model",
    "input",
    "voice",
    "response_format",
    "speed",
}

NON_RETRYABLE_VERTEX_FINISH_REASONS = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "MODEL_ARMOR",
}


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    *,
    channels: int = PCM_CHANNELS,
    sample_rate: int = PCM_SAMPLE_RATE,
    sample_width: int = PCM_SAMPLE_WIDTH,
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
    if normalized in {"audio/x-wav", "audio/wave", "audio/vnd.wave"}:
        return ".wav"
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


class VertexNoAudioError(RuntimeError):
    """Raised when Vertex returns a response without usable audio data."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def _decode_inline_audio_data(data: bytes | str) -> bytes:
    if isinstance(data, str):
        return base64.b64decode(data)
    return bytes(data)


def _is_pcm_mime_type(mime_type: str) -> bool:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    return normalized in {
        "audio/pcm",
        "audio/l16",
        "audio/raw",
        "application/octet-stream",
    }


def _iter_response_audio_blobs(
    candidate: types.Candidate | None,
) -> Iterable[tuple[bytes, str]]:
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) or []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if inline_data is None or getattr(inline_data, "data", None) is None:
            continue
        mime_type = getattr(inline_data, "mime_type", None) or "audio/pcm"
        yield _decode_inline_audio_data(inline_data.data), mime_type


def _extract_vertex_audio_response(
    response: types.GenerateContentResponse,
) -> tuple[bytes, str]:
    candidates = list(getattr(response, "candidates", None) or [])
    if not candidates:
        raise VertexNoAudioError(
            _format_vertex_no_audio_message(
                response, "Vertex AI returned no candidates"
            ),
            retryable=True,
        )

    audio_chunks: list[bytes] = []
    mime_type = "audio/pcm"
    primary_candidate = candidates[0]

    for chunk, chunk_mime_type in _iter_response_audio_blobs(primary_candidate):
        if not chunk:
            continue
        audio_chunks.append(chunk)
        mime_type = chunk_mime_type or mime_type

    if not audio_chunks:
        finish_reason = str(
            getattr(primary_candidate, "finish_reason", "") or ""
        ).upper()
        retryable = finish_reason not in NON_RETRYABLE_VERTEX_FINISH_REASONS
        raise VertexNoAudioError(
            _format_vertex_no_audio_message(
                response, "Vertex AI response does not contain audio data"
            ),
            retryable=retryable,
        )

    combined_audio = b"".join(audio_chunks)
    if _is_pcm_mime_type(mime_type):
        return _pcm_to_wav_bytes(combined_audio), "audio/wav"
    return combined_audio, mime_type.split(";", 1)[0].strip() or "audio/wav"


def _build_vertex_prompt(
    text: str,
    *,
    instruction: str | None,
    gemini_tone: str | None,
) -> str:
    normalized_text = text.strip()
    normalized_instruction = (instruction or "").strip()
    normalized_tone = (gemini_tone or "").strip()

    if not normalized_instruction and not normalized_tone:
        return normalized_text

    prompt_sections: list[str] = []
    if normalized_tone:
        prompt_sections.append(f"Use this speaking style: {normalized_tone}.")
    if normalized_instruction:
        prompt_sections.append(normalized_instruction.rstrip(".") + ".")
    direction = " ".join(
        section.strip() for section in prompt_sections if section.strip()
    )
    return f"{direction} {normalized_text}".strip()


def _format_vertex_no_audio_message(
    response: types.GenerateContentResponse,
    base_message: str,
) -> str:
    candidates = list(getattr(response, "candidates", None) or [])
    primary_candidate = candidates[0] if candidates else None

    finish_reason = getattr(primary_candidate, "finish_reason", None)
    finish_message = getattr(primary_candidate, "finish_message", None)
    prompt_feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(prompt_feedback, "block_reason", None)
    block_reason_message = getattr(prompt_feedback, "block_reason_message", None)
    usage_metadata = getattr(response, "usage_metadata", None)
    model_version = getattr(response, "model_version", None)

    text_parts: list[str] = []
    for part in (
        getattr(getattr(primary_candidate, "content", None), "parts", None) or []
    ):
        text = getattr(part, "text", None)
        if text:
            text_parts.append(str(text).strip())

    safety_flags: list[str] = []
    for rating in getattr(primary_candidate, "safety_ratings", None) or []:
        category = getattr(rating, "category", None)
        probability = getattr(rating, "probability", None)
        blocked = getattr(rating, "blocked", None)
        if category or probability or blocked:
            safety_flags.append(
                f"{category or 'unknown'}:{probability or 'unknown'}:blocked={bool(blocked)}"
            )

    details: list[str] = [base_message]
    if model_version:
        details.append(f"model_version={model_version}")
    if finish_reason:
        details.append(f"finish_reason={finish_reason}")
    if finish_message:
        details.append(f"finish_message={finish_message}")
    if block_reason:
        details.append(f"prompt_block_reason={block_reason}")
    if block_reason_message:
        details.append(f"prompt_block_message={block_reason_message}")
    if safety_flags:
        details.append(f"safety={';'.join(safety_flags)}")
    if text_parts:
        preview = " ".join(text_parts).replace("\n", " ").strip()
        details.append(f"text_preview={preview[:160]}")
    if usage_metadata:
        prompt_tokens = getattr(usage_metadata, "prompt_token_count", None)
        candidate_tokens = getattr(usage_metadata, "candidates_token_count", None)
        total_tokens = getattr(usage_metadata, "total_token_count", None)
        if any(
            value is not None
            for value in (prompt_tokens, candidate_tokens, total_tokens)
        ):
            details.append(
                "usage="
                f"prompt:{prompt_tokens},candidate:{candidate_tokens},total:{total_tokens}"
            )
    return "; ".join(details)


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
        gemini_tone: str | None,
        language_code: str | None,
    ) -> tuple[bytes, str]:
        prompt = _build_vertex_prompt(
            text,
            instruction=instruction,
            gemini_tone=gemini_tone,
        )

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                languageCode=(language_code or "").strip() or None,
                voiceConfig=types.VoiceConfig(
                    prebuiltVoiceConfig=types.PrebuiltVoiceConfig(voiceName=voice)
                ),
            ),
        )

        def _run_generation() -> tuple[bytes, str]:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return _extract_vertex_audio_response(response)

        last_error: Exception | None = None
        for attempt in range(1, VERTEX_MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(_run_generation)
            except VertexNoAudioError as exc:
                last_error = exc
                if not exc.retryable or attempt >= VERTEX_MAX_RETRIES:
                    raise
                logger.warning(
                    "[tts_tool] Vertex returned no audio on attempt %s/%s: %s",
                    attempt,
                    VERTEX_MAX_RETRIES,
                    exc,
                )
                await asyncio.sleep(min(0.5 * attempt, 1.5))

        raise RuntimeError(f"Vertex AI synthesis failed: {last_error}")


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
                if self.response_format == "pcm" or _is_pcm_mime_type(mime_type):
                    return _pcm_to_wav_bytes(audio_bytes), "audio/wav"
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
        try:
            self._install_or_update_skill()
        except Exception as exc:
            logger.warning("[tts_tool] Failed to install skill: %s", exc, exc_info=True)
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

    def _install_or_update_skill(self) -> None:
        if not SKILL_SOURCE_PATH.is_file():
            logger.warning(
                "[tts_tool] Skill source file not found: %s", SKILL_SOURCE_PATH
            )
            return

        skill_dir = Path(get_astrbot_skills_path()) / SKILL_NAME
        skill_dir.mkdir(parents=True, exist_ok=True)
        target_path = skill_dir / "SKILL.md"
        skill_content = SKILL_SOURCE_PATH.read_text(encoding="utf-8")
        current_content = ""
        if target_path.exists():
            current_content = target_path.read_text(encoding="utf-8")

        if current_content != skill_content:
            target_path.write_text(skill_content, encoding="utf-8")

        SkillManager().set_skill_active(SKILL_NAME, True)
        logger.info("[tts_tool] Installed skill: %s", SKILL_NAME)

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

    def _resolve_tool_provider(self) -> str:
        default_provider = self._general_config("default_provider", "vertex")

        if self._is_provider_configured(default_provider):
            return default_provider

        fallback_provider = "openrouter" if default_provider == "vertex" else "vertex"
        if self._is_provider_configured(fallback_provider):
            logger.info(
                "[tts_tool] Default provider %s not configured; fallback to %s",
                default_provider,
                fallback_provider,
            )
            return fallback_provider

        return default_provider

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
        instruction: str | None = None,
        gemini_tone: str | None = None,
        language_code: str | None = None,
        speed: float | None = None,
    ) -> str | mcp.types.CallToolResult:
        """将文本转换为语音音频，供 LLM 生成可发送给用户的 TTS 结果。

        Args:
            text(string): 要朗读的文本内容。
            instruction(string): 可选。用于控制语气、风格、节奏等朗读方式。当前主要对 Vertex AI 明确生效。
            gemini_tone(string): 可选。Gemini/Vertex 专用的语气与风格提示，例如 calm documentary narration、excited livestream host、soft whispery bedtime story。
            language_code(string): 可选。Vertex AI 的语言代码，例如 en-US、zh-CN。
            speed(number): 可选。当默认提供商为 OpenRouter 时可用于控制播放速度；不支持的模型会忽略。
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

        resolved_provider = self._resolve_tool_provider()
        if resolved_provider == "vertex":
            if not self._is_provider_configured("vertex"):
                return "错误：未配置可用的 Vertex AI 凭证或项目 ID。"
            resolved_model = self._vertex_config("model", DEFAULT_VERTEX_MODEL).strip()
            resolved_voice = self._vertex_config("voice", DEFAULT_VERTEX_VOICE).strip()
        elif resolved_provider == "openrouter":
            if not self._is_provider_configured("openrouter"):
                return "错误：未配置 OpenRouter API Key。"
            resolved_model = self._openrouter_config(
                "model", DEFAULT_OPENROUTER_MODEL
            ).strip()
            resolved_voice = self._openrouter_config(
                "voice", DEFAULT_OPENROUTER_VOICE
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
                    gemini_tone=gemini_tone,
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
