"""YT Auto Studio v2: energetic comedy 3D-cartoon explainer videos. Free tools only."""
import argparse, asyncio, json, os, random, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

if not hasattr(Image, "ANTIALIAS"):          # moviepy 1.0.3 + new Pillow fix
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                            ImageClip, concatenate_videoclips, afx)

# Hindi voice reads Devanagari correctly (fixes the mispronounced words). Override: --voice or env VOICE
VOICES = {"hinglish": "hi-IN-MadhurNeural", "hindi": "hi-IN-MadhurNeural", "english": "en-US-GuyNeural"}
SIZES = {"short": (720, 1280), "long": (1280, 720)}
FONT_DEV = ["/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", "C:/Windows/Fonts/Nirmala.ttf"]
FONT_LAT = ["/usr/share/fonts/truetype/noto/NotoSans-Black.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
CAP_COLORS = ["#FFE600", "#FFFFFF", "#00E5FF", "#FF4D9D", "#7CFF4D"]


def log(msg): print(f"▶ {msg}", flush=True)


from scriptgen import write_script
from imagegen import make_image


# ---------- 3. VOICEOVER (edge-tts, free, energetic settings) ----------
async def tts(text, voice, out):
    await edge_tts.Communicate(text, voice, rate=os.environ.get("TTS_RATE", "+10%"),
                               pitch=os.environ.get("TTS_PITCH", "+2Hz")).save(str(out))


# ---------- 4. CAPTIONS, MOTION, VIDEO ----------
def pick_font(text, size):
    dev = any("\u0900" <= ch <= "\u097F" for ch in text)
    for p in [os.environ.get("FONT", "")] + (FONT_DEV if dev else []) + FONT_LAT:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(text, font, d, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    return lines + ([cur] if cur else [])


def caption_overlay(text, w, h, size, color):
    font = pick_font(text, size)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    lines = wrap(text.upper() if text.isascii() else text, font, d, int(w * 0.88)); lh = int(size * 1.3)
    y = int(h * 0.68) - lh * len(lines) // 2
    for ln in lines:
        x = (w - d.textlength(ln, font=font)) / 2
        d.text((x + 4, y + 5), ln, font=font, fill="black", stroke_width=max(4, size // 8), stroke_fill="black")
        d.text((x, y), ln, font=font, fill=color, stroke_width=max(4, size // 8), stroke_fill="black")
        y += lh
    return np.array(img)


def chunk_words(text, per=3):
    ws = text.split()
    return [" ".join(ws[i:i + per]) for i in range(0, len(ws), per)] or [text]


def build_scene(i, caption, img_path, mp3, W, H):
    audio = AudioFileClip(str(mp3)); dur = audio.duration + 0.2
    base = ImageClip(str(img_path)).set_duration(dur)
    mode = i % 4
    if mode == 0:
        mv = base.resize(lambda t: 1 + 0.10 * t / dur).set_position("center")
    elif mode == 1:
        mv = base.resize(lambda t: 1.10 - 0.10 * t / dur).set_position("center")
    else:
        big = base.resize(1.16); ox = 0.16 * W; oy = -0.08 * H
        mv = big.set_position((lambda t: (-ox * t / dur, oy)) if mode == 2 else (lambda t: (-ox + ox * t / dur, oy)))
    layers = [mv]
    chunks = chunk_words(caption); total = sum(len(c) for c in chunks); t = 0.0
    size = int(min(W, H) * 0.10)
    for k, c in enumerate(chunks):
        cd = audio.duration * len(c) / total
        arr = caption_overlay(c, W, H, size, CAP_COLORS[k % len(CAP_COLORS)])
        layers.append(ImageClip(arr).set_start(t).set_duration(cd)
                      .resize(lambda tt: 1 + 0.18 * max(0.0, 1 - tt / 0.15)).set_position("center"))
        t += cd
    return CompositeVideoClip(layers, size=(W, H)).set_duration(dur).set_audio(audio)


def make_thumbnail(meta, out_dir, seed):
    p = out_dir / "thumbnail.jpg"
    make_image(meta.get("thumbnail_prompt", meta["title"]), p, 1280, 720, seed, meta.get("thumbnail_keywords", ""))
    img = Image.open(p).convert("RGB")
    img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.4)).enhance(1.12)
    img = ImageEnhance.Sharpness(img).enhance(1.4).convert("RGBA")
    grad = Image.new("RGBA", img.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(grad)
    for y in range(300, 720):
        gd.line([(0, y), (1280, y)], fill=(0, 0, 0, int(215 * (y - 300) / 420)))
    img = Image.alpha_composite(img, grad); d = ImageDraw.Draw(img)
    text = str(meta.get("thumbnail_text") or meta["title"]).upper(); ws = text.split()
    lines = [" ".join(ws[:2]), " ".join(ws[2:])] if len(ws) > 2 else [text]
    lines = [l for l in lines if l]
    size = 200
    while size > 60:
        font = pick_font(text, size)
        if max(d.textlength(l, font=font) for l in lines) <= 1160 and size * 1.15 * len(lines) <= 340:
            break
        size -= 10
    lh = int(size * 1.15); y = 700 - lh * len(lines)
    for i, l in enumerate(lines):
        x = (1280 - d.textlength(l, font=font)) / 2
        d.text((x + 8, y + 8), l, font=font, fill="black", stroke_width=16, stroke_fill="black")
        d.text((x, y), l, font=font, fill=["#FFE600", "#FFFFFF"][i % 2], stroke_width=12, stroke_fill="black")
        y += lh
    d.rectangle([0, 0, 1279, 719], outline="#FF2D55", width=14)
    img.convert("RGB").save(p, quality=93)
    return p


# ---------- 5. UPLOAD (optional) ----------
def upload(video, thumb, meta, privacy):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    need = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    if any(not os.environ.get(k) for k in need):
        print("⚠ Upload skip: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN set nahi hain."); return
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
    yt = build("youtube", "v3", credentials=creds)
    tags = [str(t).replace("#", "") for t in meta.get("tags", [])]
    desc = meta.get("description", "") + "\n\n" + " ".join("#" + t.replace(" ", "") for t in tags[:5]) + "\n\nAI-assisted video."
    body = {"snippet": {"title": meta["title"][:100], "description": desc, "tags": tags, "categoryId": "22"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]; print(f"✅ Uploaded: https://youtu.be/{vid} ({privacy})")
    try:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
    except Exception as e:
        print("⚠ Thumbnail set nahi hua (channel verified hona chahiye):", e)


# ---------- MAIN ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--style", default="Facts / Education")
    ap.add_argument("--lang", choices=VOICES, default="hinglish")
    ap.add_argument("--format", choices=SIZES, default="short")
    ap.add_argument("--scenes", type=int, default=0)
    ap.add_argument("--voice", default="")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    a = ap.parse_args()

    W, H = SIZES[a.format]; n = a.scenes or (12 if a.format == "short" else 18)
    voice = a.voice or os.environ.get("VOICE") or VOICES[a.lang]
    out = Path("output") / datetime.now().strftime("%Y%m%d_%H%M%S"); out.mkdir(parents=True, exist_ok=True)

    log("Script likh raha hu (Gemini)...")
    meta = write_script(a.topic, a.style, a.lang, a.format, n)
    scenes = meta["scenes"]
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "script.txt").write_text("\n\n".join(s["voice"] for s in scenes), encoding="utf-8")
    (out / "prompts.md").write_text("\n\n".join(
        f"## Scene {i + 1}\nVoice: {s['voice']}\nCaption: {s.get('caption', '')}\nImage prompt: {s['image_prompt']}\n"
        f"Video prompt (Kling/Veo): {s.get('video_prompt', '')}" for i, s in enumerate(scenes)), encoding="utf-8")
    print("  Title:", meta["title"])

    clips = []
    for i, s in enumerate(scenes):
        log(f"Scene {i + 1}/{len(scenes)}: image + voice")
        img = out / f"scene{i + 1}.jpg"; mp3 = out / f"scene{i + 1}.mp3"
        make_image(s["image_prompt"], img, W, H, random.randint(1, 10**6), s.get("keywords", ""))
        asyncio.run(tts(s["voice"], voice, mp3))
        clips.append(build_scene(i, s.get("caption") or s["voice"], img, mp3, W, H))

    log("Video jod raha hu (thoda time lagega)...")
    final = concatenate_videoclips(clips, method="compose")
    music = Path("music.mp3")
    if music.exists():
        m = AudioFileClip(str(music)).fx(afx.audio_loop, duration=final.duration).volumex(0.08)
        final = final.set_audio(CompositeAudioClip([final.audio, m]))
    video = out / "video.mp4"
    final.write_videofile(str(video), fps=24, codec="libx264", audio_codec="aac", preset="veryfast",
                          threads=2, logger=None)

    log("Thumbnail bana raha hu...")
    thumb = make_thumbnail(meta, out, random.randint(1, 10**6))
    print(f"\n✅ Ready: {video}")
    if a.upload:
        log("YouTube pe upload...")
        upload(video, thumb, meta, a.privacy)


if __name__ == "__main__":
    main()
    
