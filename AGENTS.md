# Codex Notes

When the user says "please generate video", use this project:

```bash
cd /Users/whaikung/Documents/thai-novel-openai
. .venv/bin/activate
```

Current video settings are saved in `config.json`:

- Intro text: `ยินดีต้อนรับเข้าสู่ T-H-A-I Channel ขอให้สนุกกับการรับฟังนะครับ`
- Intro duration: 6 seconds
- Thai TTS voice: `th-TH-NiwatNeural`
- No subtitles
- Spoken title card before narration
- Scene audio must not be tail-trimmed. Keep `scene_tail_trim_seconds` at `0`.
- Keep `trim_trailing_silence` false unless the implementation is changed to avoid cutting at normal narration pauses.
- Scene video duration should be based on the exact TTS audio duration to avoid silent image holds after speech.

For one episode:

```bash
python3 scripts/audiobook_video.py build "data/ep_01.md"
```

For many episodes:

```bash
python3 scripts/audiobook_video.py build-all
```

Before building, make sure scene images exist in `assets/images` using this pattern:

```text
assets/images/ep_01_scene_001.png
assets/images/ep_01_scene_002.png
...
```

If images are missing, first run:

```bash
python3 scripts/audiobook_video.py plan "data/ep_01.md"
```

Then generate images from `output/ep_01/image_prompts.md` and save them into `assets/images`.
