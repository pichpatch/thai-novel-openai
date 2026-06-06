#!/usr/bin/env python3
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
INTRO_DIR = ROOT / "assets" / "intro"
IMAGE_DIR = ROOT / "assets" / "images"
BACKGROUND_PATH = ROOT / "assets" / "background" / "ambient_loop.wav"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def run(cmd):
    print("+", " ".join(str(x) for x in cmd))
    subprocess.run([str(x) for x in cmd], check=True)


def require_tool(name):
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def font(size):
    candidates = [
        "/System/Library/Fonts/Supplemental/SukhumvitSet.ttc",
        "/System/Library/Fonts/ThonburiUI.ttc",
        "/System/Library/Fonts/Supplemental/Thonburi.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def parse_frontmatter(text):
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end].strip()
            body = text[end + 4 :].lstrip()
            for line in raw.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"')
    return meta, body


def episode_number(md_path):
    m = re.search(r"ep_(\d+)", md_path.stem, re.I)
    if not m:
        m = re.search(r"ตอนที่\s*(\d+)", md_path.stem, re.I)
    if not m:
        m = re.search(r"(\d+)", md_path.stem)
    return int(m.group(1)) if m else 1


def markdown_heading(body, level):
    hashes = "#" * level
    for line in body.splitlines():
        m = re.match(rf"^\s*{hashes}\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def title_from_body(body):
    title = markdown_heading(body, 1)
    if title:
        return title
    return "ชื่อตอน"


def episode_title_from_body(body):
    title = markdown_heading(body, 2)
    if title:
        title = re.sub(r"^ตอนที่\s*\d+\s*[-—:]*\s*", "", title).strip()
        return title or "ชื่อตอน"
    return title_from_body(body)


def clean_markdown(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "\n\n---SCENE---\n\n", text, flags=re.M)
    return text.strip()


def split_scenes(body, cfg):
    body = re.sub(r"(?m)^\s*#{1,2}\s+.+\s*$", "", body).strip()
    by_heading = re.split(r"(?im)^\s*##+\s+(?:scene|ฉาก)\s*\d*.*$", body)
    if len(by_heading) > 1:
        chunks = [clean_markdown(x) for x in by_heading if clean_markdown(x)]
        return chunks

    cleaned = clean_markdown(body)
    rough = [x.strip() for x in cleaned.split("---SCENE---") if x.strip()]
    if len(rough) > 1:
        return rough

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    scenes = []
    current = ""
    max_chars = int(cfg["scene_max_chars"])
    min_chars = int(cfg["scene_min_chars"])
    for p in paragraphs:
        next_text = f"{current}\n\n{p}".strip() if current else p
        if current and len(next_text) > max_chars and len(current) >= min_chars:
            scenes.append(current)
            current = p
        else:
            current = next_text
    if current:
        scenes.append(current)
    return scenes


def make_plan(md_path):
    cfg = load_config()
    text = md_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    ep_no = episode_number(md_path)
    ep_id = f"ep_{ep_no:02d}"
    ep_name = meta.get("ep_name") or episode_title_from_body(body)
    novel_name = meta.get("novel_name") or markdown_heading(body, 1) or cfg["novel_name"]
    scenes = split_scenes(body, cfg)
    if not scenes:
        raise SystemExit(f"No readable scene text found in {md_path}")

    plan = {
        "episode_id": ep_id,
        "episode_number": ep_no,
        "episode_name": ep_name,
        "novel_name": novel_name,
        "title_text": f"เรื่อง {novel_name} ตอนที่ {ep_no} {ep_name}",
        "scenes": [],
    }
    for idx, scene_text in enumerate(scenes, 1):
        excerpt = re.sub(r"\s+", " ", scene_text).strip()[:420]
        prompt = (
            f"{cfg['image_style']}. Scene {idx} from Thai audiobook episode "
            f"'{ep_name}'. Visualize this moment: {excerpt}"
        )
        plan["scenes"].append(
            {
                "index": idx,
                "text": scene_text,
                "image": f"assets/images/{ep_id}_scene_{idx:03d}.png",
                "audio": f"output/{ep_id}/audio/scene_{idx:03d}.mp3",
                "prompt": prompt,
            }
        )
    return plan


def save_plan(md_path):
    plan = make_plan(md_path)
    out_dir = OUTPUT_DIR / plan["episode_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scene_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [f"# Image prompts for {plan['episode_id']}", ""]
    for scene in plan["scenes"]:
        lines += [
            f"## {plan['episode_id']}_scene_{scene['index']:03d}.png",
            scene["prompt"],
            "",
        ]
    (out_dir / "image_prompts.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Created {out_dir / 'scene_plan.json'}")
    print(f"Created {out_dir / 'image_prompts.md'}")
    return plan


def find_intro_image():
    for name in ["intro.png", "intro.jpg", "intro.jpeg"]:
        path = INTRO_DIR / name
        if path.exists():
            return path
    raise SystemExit("Missing intro image. Put intro.png or intro.jpg in assets/intro")


def draw_wrapped(draw, xy, text, image_font, fill, max_width, line_gap=12, anchor="mm"):
    words = list(text)
    lines = []
    line = ""
    for ch in words:
        test = line + ch
        bbox = draw.textbbox((0, 0), test, font=image_font)
        if bbox[2] - bbox[0] > max_width and line:
            lines.append(line)
            line = ch
        else:
            line = test
    if line:
        lines.append(line)
    line_h = image_font.size + line_gap
    total_h = line_h * len(lines)
    x, y = xy
    start_y = y - total_h / 2
    for i, line in enumerate(lines):
        draw.text((x, start_y + i * line_h), line, font=image_font, fill=fill, anchor=anchor)


def draw_centered_line(draw, xy, text, image_font, fill, stroke_fill="#000000", stroke_width=3):
    x, y = xy
    draw.text(
        (x, y),
        text,
        font=image_font,
        fill=fill,
        anchor="mm",
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def make_title_card(plan, dest, cfg):
    w, h = cfg["resolution"]
    img = Image.new("RGB", (w, h), "#171717")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, w, 18), fill="#b51d24")
    draw.rectangle((0, h - 18, w, h), fill="#b51d24")

    story_font = font(70)
    episode_font = font(88)
    name_font = font(104)
    muted = "#d8c8a5"
    white = "#ffffff"

    draw_centered_line(draw, (w // 2, 300), f"เรื่อง {plan['novel_name']}", story_font, muted, stroke_width=2)
    draw_centered_line(draw, (w // 2, 470), f"ตอนที่ {plan['episode_number']}", episode_font, white, stroke_width=4)
    draw_wrapped(
        draw,
        (w // 2, 650),
        plan["episode_name"],
        name_font,
        white,
        int(w * 0.82),
        20,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def make_placeholder(scene, dest, cfg):
    w, h = cfg["resolution"]
    img = Image.new("RGB", (w, h), "#242424")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, w, 18), fill="#a5161d")
    text = f"IMAGE NEEDED\n{Path(scene['image']).name}"
    draw_wrapped(draw, (w // 2, h // 2), text, font(62), "#ffffff", int(w * 0.72), 16)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def make_video_still(image_path, audio_path, dest, cfg, duration=None):
    vf = (
        f"scale={cfg['resolution'][0]}:{cfg['resolution'][1]}:"
        "force_original_aspect_ratio=increase,crop="
        f"{cfg['resolution'][0]}:{cfg['resolution'][1]},setsar=1"
    )
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", image_path]
    if audio_path:
        duration = ffprobe_duration(audio_path)
        cmd += ["-i", audio_path, "-t", f"{duration:.3f}"]
    elif duration:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration),
            "-shortest",
        ]
    cmd += [
        "-vf",
        vf,
        "-r",
        str(cfg["fps"]),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]
    if audio_path:
        cmd += [
            "-af",
            "aresample=async=1:first_pts=0",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "192k",
        ]
    elif duration:
        cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd.append(dest)
    run(cmd)


def tts(text, dest, cfg):
    if shutil.which("edge-tts") is None:
        raise SystemExit("edge-tts is not installed. Run: pip install -r requirements.txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "edge-tts",
            "--voice",
            cfg["voice"],
            "--rate",
            cfg["rate"],
            "--volume",
            cfg["volume"],
            "--text",
            text,
            "--write-media",
            dest,
        ]
    )


def ffprobe_duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def pad_audio_to_duration(src, dest, seconds):
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-af",
            f"apad,atrim=0:{seconds}",
            "-c:a",
            "mp3",
            dest,
        ]
    )


def trim_audio_tail(src, dest, seconds):
    if float(seconds) <= 0:
        shutil.copy(src, dest)
        return
    duration = ffprobe_duration(src)
    target_duration = max(0.1, duration - float(seconds))
    if target_duration >= duration:
        shutil.copy(src, dest)
        return
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-af",
            f"atrim=0:{target_duration},asetpts=PTS-STARTPTS",
            "-c:a",
            "mp3",
            dest,
        ]
    )


def trim_trailing_silence(src, dest, cfg):
    if not cfg.get("trim_trailing_silence", True):
        shutil.copy(src, dest)
        return
    stop_duration = float(cfg.get("trailing_silence_duration", 0.35))
    threshold = str(cfg.get("trailing_silence_threshold", "-45dB"))
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-af",
            (
                "silenceremove="
                "stop_periods=1:"
                f"stop_duration={stop_duration}:"
                f"stop_threshold={threshold}"
            ),
            "-c:a",
            "mp3",
            dest,
        ]
    )


def concat_videos(parts, dest):
    list_path = dest.parent / "concat.txt"
    list_path.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "192k",
            dest,
        ]
    )


def mix_background(video, dest, cfg):
    if not BACKGROUND_PATH.exists():
        shutil.copy(video, dest)
        print("No background track found; final video has narration only.")
        return
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-stream_loop",
            "-1",
            "-i",
            BACKGROUND_PATH,
            "-filter_complex",
            (
                f"[0:a]volume={cfg['narration_volume']}[narr];"
                f"[1:a]volume={cfg['background_volume']}[bg];"
                "[narr][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
            ),
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            dest,
        ]
    )


def generate_background():
    require_tool("ffmpeg")
    BACKGROUND_PATH.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=329.63:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:sample_rate=44100:amplitude=0.08",
            "-filter_complex",
            "[0:a]volume=0.08[a0];[1:a]volume=0.04[a1];[2:a]lowpass=f=900,volume=0.12[a2];"
            "[a0][a1][a2]amix=inputs=3:duration=longest,afade=t=in:st=0:d=5,afade=t=out:st=55:d=5[a]",
            "-map",
            "[a]",
            "-t",
            "60",
            BACKGROUND_PATH,
        ]
    )
    print(f"Created {BACKGROUND_PATH}")


def build(md_path, allow_placeholders):
    require_tool("ffmpeg")
    require_tool("ffprobe")
    cfg = load_config()
    plan = save_plan(md_path)
    out_dir = OUTPUT_DIR / plan["episode_id"]
    audio_dir = out_dir / "audio"
    part_dir = out_dir / "parts"
    part_dir.mkdir(parents=True, exist_ok=True)

    intro_seconds = int(cfg.get("intro_seconds", 10))
    intro_audio_raw = audio_dir / "intro_raw.mp3"
    intro_audio = audio_dir / f"intro_{intro_seconds}s.mp3"
    tts(cfg["intro_text"], intro_audio_raw, cfg)
    pad_audio_to_duration(intro_audio_raw, intro_audio, intro_seconds)
    intro_video = part_dir / "000_intro.mp4"
    make_video_still(find_intro_image(), intro_audio, intro_video, cfg)

    title_card = out_dir / "title_card.png"
    make_title_card(plan, title_card, cfg)
    title_audio_raw = audio_dir / "title_raw.mp3"
    title_audio = audio_dir / "title.mp3"
    tts(plan["title_text"], title_audio_raw, cfg)
    min_title_seconds = int(cfg.get("title_seconds", 5))
    if ffprobe_duration(title_audio_raw) < min_title_seconds:
        pad_audio_to_duration(title_audio_raw, title_audio, min_title_seconds)
    else:
        shutil.copy(title_audio_raw, title_audio)
    title_video = part_dir / "001_title.mp4"
    make_video_still(title_card, title_audio, title_video, cfg)

    parts = [intro_video, title_video]
    for scene in plan["scenes"]:
        idx = scene["index"]
        audio_path = ROOT / scene["audio"]
        raw_audio_path = audio_path.with_name(f"{audio_path.stem}_raw{audio_path.suffix}")
        image_path = ROOT / scene["image"]
        tts(scene["text"], raw_audio_path, cfg)
        silence_trimmed_audio_path = audio_path.with_name(
            f"{audio_path.stem}_silence_trimmed{audio_path.suffix}"
        )
        trim_trailing_silence(raw_audio_path, silence_trimmed_audio_path, cfg)
        trim_audio_tail(
            silence_trimmed_audio_path,
            audio_path,
            float(cfg.get("scene_tail_trim_seconds", 0)),
        )
        if not image_path.exists():
            if not allow_placeholders:
                raise SystemExit(
                    f"Missing image: {image_path}\n"
                    f"Generate it from {out_dir / 'image_prompts.md'} or rerun with --allow-placeholders."
                )
            make_placeholder(scene, image_path, cfg)
        scene_video = part_dir / f"{idx + 1:03d}_scene_{idx:03d}.mp4"
        make_video_still(image_path, audio_path, scene_video, cfg)
        parts.append(scene_video)

    no_bg = out_dir / f"{plan['episode_id']}_no_bg.mp4"
    final = out_dir / f"{plan['episode_id']}.mp4"
    concat_videos(parts, no_bg)
    mix_background(no_bg, final, cfg)
    print(f"Done: {final}")


def main():
    parser = argparse.ArgumentParser(description="Build Thai audiobook YouTube videos.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_cmd = sub.add_parser("plan", help="Create scene plan and image prompts.")
    plan_cmd.add_argument("episode", type=Path)

    build_cmd = sub.add_parser("build", help="Build one episode video.")
    build_cmd.add_argument("episode", type=Path)
    build_cmd.add_argument("--allow-placeholders", action="store_true")

    sub.add_parser("build-all", help="Build all data/ep_*.md files.")
    sub.add_parser("bg", help="Generate a reusable background sound.")

    args = parser.parse_args()
    if args.command == "plan":
        save_plan(args.episode)
    elif args.command == "build":
        build(args.episode, args.allow_placeholders)
    elif args.command == "build-all":
        for md_path in sorted(DATA_DIR.glob("ep_*.md")):
            build(md_path, allow_placeholders=False)
    elif args.command == "bg":
        generate_background()


if __name__ == "__main__":
    main()
