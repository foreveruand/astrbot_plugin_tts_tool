---
name: tts_tool_gemini_prompting
description: Use when preparing high-quality spoken audio with the `generate_tts_audio` tool on the Gemini/Vertex provider. Helps convert user intent into transcript text, `gemini_tone`, and longer `instruction` notes based on Gemini speech prompting guidance.
---

# Gemini TTS Prompting

Use this skill when the user wants natural-sounding speech from `generate_tts_audio` and the plugin is configured to use Gemini/Vertex TTS.

## What This Skill Does

- Keeps the spoken transcript complete. Do not shorten or paraphrase the user's text unless they explicitly ask.
- Splits prompting into:
  - `text`: the exact words that should be spoken.
  - `gemini_tone`: a short style brief for emotion, pacing, accent, delivery, or character.
  - `instruction`: optional longer director notes when the request needs precise performance control.
- Follows Gemini speech prompting guidance:
  - Be explicit about tone, speaking rate, emotion, accent, and delivery role.
  - You may directly add audio tags inside `text` when the user wants local performance changes or expressive sound cues.
  - Keep non-spoken stage cues in English tags when needed, such as `[whispers]`, `[laughs]`, `[sighs]`, `[excitedly]`, `[very fast]`, `[very slow]`, or `[shouting]`.
  - Put only spoken content in `text`; use `gemini_tone` or `instruction` for performance intent.

## Audio Tags

- Gemini supports inline audio tags inside the spoken transcript.
- Use audio tags in `text` when only part of the line should change delivery, speed, emotion, or loudness.
- Even if the spoken transcript is Chinese or another non-English language, keep the audio tags themselves in English for best results.
- Audio tags can also introduce non-verbal sounds when useful, such as `[laughs]`, `[sighs]`, `[gasp]`, or `[cough]`.
- Keep tags short and readable. Do not overload every sentence with tags unless the user explicitly wants a highly theatrical performance.

## Audio Tag Examples

- Local emphasis in Chinese text:
  - `text="[excitedly] 大家好，欢迎来到今晚的直播。"`
- Speed control:
  - `text="[very slow] 请仔细听下面这段安全提醒。"`
- Mixed delivery in one sentence:
  - `text="[whispers] 先别出声。 [shouting] 现在快跑！"`
- Non-verbal cue:
  - `text="我本来很有信心的，[sighs] 但计划还是失败了。"`
- Creative character cue:
  - `text="[like dracula] 欢迎来到今晚的故事时间。"`

## Decision Rules

- If the user only wants a normal read-aloud:
  - Put the full content in `text`.
  - Leave `instruction` empty.
  - Use a short `gemini_tone` only if the user asked for a clear style, such as `warm customer support`, `serious news anchor`, or `gentle bedtime story`.
- If the user wants a specific delivery:
  - Put the transcript in `text`.
  - Put the concise style target in `gemini_tone`.
  - Put extra constraints in `instruction`, such as pauses, emphasis, pronunciation hints, or audience framing.
- If the user asks for sound effects or expressive cues:
  - Keep the cues inline in `text` with English bracket tags if they should affect the spoken performance.
  - Prefer tags when the effect applies only to a word, phrase, or sentence fragment.
- If the request is multilingual:
  - Keep spoken text in the target language.
  - Keep stage/performance tags in English.

## Good `gemini_tone` Examples

- `calm documentary narrator`
- `friendly Mandarin podcast host with steady pacing`
- `excited game streamer, fast tempo, high energy`
- `soft bedtime storytelling voice, slow pace, warm emotion`
- `professional bilingual product demo, crisp articulation`

## Good `instruction` Examples

- `Start with a confident tone, then slow down on the safety disclaimer.`
- `Pause slightly after each bullet point and emphasize all dates clearly.`
- `Sound reassuring and practical, not theatrical.`
- `Read the quoted sentence with extra emphasis, then return to a neutral tone.`

## Tool Usage Pattern

```text
generate_tts_audio(
  text="...",
  gemini_tone="...",
  instruction="..."
)
```

## Example Mapping

User request:
`把这段公告读得像冷静专业的新闻播报，并把日期读清楚。`

Tool call shape:

```text
text="这里放完整公告正文"
gemini_tone="calm professional news anchor"
instruction="Read all dates and times clearly. Use steady pacing and avoid dramatic emotion."
```

User request:
`前半句小声说，后半句突然喊出来。`

Tool call shape:

```text
text="[whispers] 我刚发现一个秘密。 [shouting] 现在所有人都知道了！"
gemini_tone="dramatic storyteller"
instruction=""
```
