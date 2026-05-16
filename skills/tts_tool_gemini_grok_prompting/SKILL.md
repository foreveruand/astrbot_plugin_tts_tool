---
name: tts_tool_gemini_grok_prompting
description: Use when preparing high-quality spoken audio with the `generate_tts_audio` tool on the Gemini/Vertex or xAI Grok provider. Helps convert user intent into transcript text, `gemini_tone`, and provider-aware inline audio tags.
---

# Gemini And Grok TTS Prompting

Use this skill when the user wants natural-sounding speech from `generate_tts_audio` and the plugin is configured to use Gemini/Vertex TTS or xAI Grok TTS.

## What This Skill Does

- Keeps the spoken transcript complete. Do not shorten or paraphrase the user's text unless they explicitly ask.
- Splits prompting into:
  - `text`: the exact words that should be spoken.
  - `gemini_tone`: a short style brief for Gemini/Vertex emotion, pacing, accent, delivery, or character.
  - `instruction`: optional longer director notes when the request needs precise performance control on Gemini/Vertex.
- Adapts inline performance tags to the active provider:
  - Gemini: prefers short English bracket tags such as `[whispers]` or `[excitedly]`.
  - Grok: supports speech tags too, but its tag set is not identical to Gemini. Prefer xAI-documented inline tags like `[pause]` or `[laugh]`, plus wrapping tags like `<whisper>...</whisper>`.

## Gemini Guidance

- Be explicit about tone, speaking rate, emotion, accent, and delivery role.
- You may directly add audio tags inside `text` when the user wants local performance changes or expressive sound cues.
- Keep non-spoken stage cues in English tags when needed, such as `[whispers]`, `[laughs]`, `[sighs]`, `[excitedly]`, `[very fast]`, `[very slow]`, or `[shouting]`.
- Put only spoken content in `text`; use `gemini_tone` or `instruction` for broader performance intent.

## Grok Guidance

- Grok TTS supports two tag styles that differ from Gemini:
  - Inline tags such as `[pause]`, `[long-pause]`, `[laugh]`, or `[sigh]`.
  - Wrapping tags such as `<whisper>...</whisper>`, `<soft>...</soft>`, `<slow>...</slow>`, or `<emphasis>...</emphasis>`.
- Prefer concise Grok tags for emotion, pacing, and emphasis. Do not assume undocumented Gemini-specific tags will behave the same on Grok.
- If a local span should change delivery, wrap only that fragment instead of tagging the whole sentence.
- Keep the spoken text intact and use tags only where they materially affect delivery.

## Gemini Vs Grok

- Gemini commonly uses English square-bracket stage tags directly inside the transcript, for example `[whispers]`, `[shouting]`, `[very slow]`, or `[laughs]`.
- Grok uses two formal tag syntaxes from xAI docs:
  - Inline one-shot tags: `[tag]`
  - Wrapping span tags: `<tag>...</tag>`
- For Grok, do not invent Gemini-style closing bracket tags like `[/whispers]`.
- For Grok, use wrapper tags when a whole phrase should change delivery, and inline tags when you want a single event at a point in time.
- For Gemini, broader acting direction can still go in `gemini_tone` and `instruction`.
- For Grok, fine-grained control should mostly live directly in `text` via speech tags.

## Grok Tag Reference

Use the exact xAI spellings below.

### Inline Tags

- Pauses:
  - `[pause]`
  - `[long-pause]`
  - `[hum-tune]`
- Laughter and crying:
  - `[laugh]`
  - `[chuckle]`
  - `[giggle]`
  - `[cry]`
- Mouth sounds:
  - `[tsk]`
  - `[tongue-click]`
  - `[lip-smack]`
- Breathing:
  - `[breath]`
  - `[inhale]`
  - `[exhale]`
  - `[sigh]`

### Wrapping Tags

- Volume and intensity:
  - `<soft>...</soft>`
  - `<whisper>...</whisper>`
  - `<loud>...</loud>`
  - `<build-intensity>...</build-intensity>`
  - `<decrease-intensity>...</decrease-intensity>`
- Pitch and speed:
  - `<higher-pitch>...</higher-pitch>`
  - `<lower-pitch>...</lower-pitch>`
  - `<slow>...</slow>`
  - `<fast>...</fast>`
- Vocal style:
  - `<sing-song>...</sing-song>`
  - `<singing>...</singing>`
  - `<laugh-speak>...</laugh-speak>`
  - `<emphasis>...</emphasis>`

## How To Choose Grok Tags

- Use `[pause]` or `[long-pause]` when the user asks for suspense, dramatic timing, or a beat before the next phrase.
- Use `[laugh]`, `[chuckle]`, `[giggle]`, or `[cry]` when the user wants an audible reaction, not just a mood.
- Use `<whisper>...</whisper>` or `<soft>...</soft>` for quiet confidential delivery across a phrase.
- Use `<slow>...</slow>` or `<fast>...</fast>` when the pacing change should persist for a whole span.
- Use `<emphasis>...</emphasis>` for a phrase that needs stress or punch.
- Use `<higher-pitch>...</higher-pitch>` or `<lower-pitch>...</lower-pitch>` when the requested effect is vocal color rather than emotion.
- Use `<build-intensity>...</build-intensity>` when the user wants a ramp-up.
- Prefer one or two meaningful tags over dense tag spam.
- Wrapping tags usually sound more natural around full phrases than around a single short word.
- Combine tags only when the user clearly wants stacked effects, for example `<slow><soft>晚安，睡个好觉。</soft></slow>`.

## Audio Tag Examples

- Gemini local emphasis in Chinese text:
  - `text="[excitedly] 大家好，欢迎来到今晚的直播。"`
- Gemini mixed delivery:
  - `text="[whispers] 先别出声。 [shouting] 现在快跑！"`
- Grok inline expression:
  - `text="先别出声。[pause] 现在继续往前走。"`
- Grok local pacing or emotion:
  - `text="请先听我说完，<soft><slow>这不是一个好消息。</slow></soft>"`
- Grok laugh cue:
  - `text="我本来很有把握的。[laugh] 结果第一步就错了。"`
- Grok emphasis on one phrase:
  - `text="这次更新里，<emphasis>只有这一条必须立刻处理。</emphasis>"`
- Grok whisper plus pause:
  - `text="我只说一次。 <whisper>别告诉任何人。</whisper> [long-pause] 记住了吗？"`

## Decision Rules

- If the user only wants a normal read-aloud:
  - Put the full content in `text`.
  - Leave `instruction` empty.
  - Use a short `gemini_tone` only if the active provider is Gemini/Vertex and the user asked for a clear style.
- If the user wants a specific Gemini delivery:
  - Put the transcript in `text`.
  - Put the concise style target in `gemini_tone`.
  - Put extra constraints in `instruction`, such as pauses, emphasis, pronunciation hints, or audience framing.
- If the request targets Grok:
  - Express local delivery changes mainly through Grok-compatible inline tags or wrapping tags in `text`.
  - Avoid relying on `gemini_tone` for Grok-specific behavior.
  - Prefer exact xAI-documented tags over improvised synonyms.
- If the request is multilingual:
  - Keep spoken text in the target language.
  - Keep Gemini stage/performance tags in English.
  - For Grok, prefer the exact tag spelling shown in xAI documentation examples.

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

Gemini-oriented tool call shape:

```text
text="[whispers] 我刚发现一个秘密。 [shouting] 现在所有人都知道了！"
gemini_tone="dramatic storyteller"
instruction=""
```

Grok-oriented tool call shape:

```text
text="<whisper>我刚发现一个秘密。</whisper> [pause] 现在所有人都知道了！"
gemini_tone=""
instruction=""
```
