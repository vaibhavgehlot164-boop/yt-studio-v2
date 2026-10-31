"""YT Auto Studio v2: energetic comedy 3D-cartoon explainer videos. Free tools only."""
import argparse, asyncio, base64, json, os, random, re, sys, time, urllib.parse
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


# ---------- 1. SCRIPT (Gemini free tier) ----------
def gemini_models(key):
    """Preferred model first, then every other text 'flash' model this key can use (names change often)."""
    first = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    names = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=60)
        for m in r.json().get("models", []):
            n = m["name"].split("/")[-1]
            if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n \
                    and not any(x in n for x in ("image", "tts", "audio", "live", "robot", "computer", "native")):
                names.append(n)
    except Exception as e:
        print("  model list nahi mili:", e)
    names.sort(key=lambda n: ("lite" in n, [-ord(c) for c in n]))
    return [first] + [n for n in names if n != first][:5]


def gemini_json(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY set karo (free: https://aistudio.google.com/apikey)")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    last = ""
    for model in gemini_models(key):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=90)
            except requests.RequestException as e:
                last = f"{model}: {type(e).__name__} (90 sec mein jawab nahi aaya)"
                print("  Gemini fail ->", last)
                break      # is model ko chhodo, agla model try karo
            if r.status_code == 200:
                try:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                    data = json.loads(text)
                    print(f"  Gemini model: {model}")
                    return data
                except Exception as e:
                    last = f"{model}: bad JSON ({e})"; print("  ", last); continue
            last = f"{model}: HTTP {r.status_code} {r.text[:200]!r}"
            print("  Gemini fail ->", last)
            if r.status_code in (429, 500, 503):
                time.sleep(10); continue
            break          # 404/400/403: is model ko chhodo, agla try karo
    sys.exit("Gemini kisi model par nahi chala. Aakhri error: " + last)


def write_script(topic, style, lang, fmt, n):
    words = "110-140 words total" if fmt == "short" else "550-700 words total"
    if lang == "english":
        rules = '"voice": natural spoken English line. "caption": the same line (can be shortened).'
    elif lang == "hindi":
        rules = '"voice": Hindi in Devanagari. "caption": the same line in Devanagari.'
    else:
        rules = ('"voice": the line in Hindi written in DEVANAGARI script (English words like space, robot, YouTube also '
                 'in Devanagari spelling) so a Hindi text-to-speech voice pronounces everything correctly. '
                 '"caption": the SAME line in Hinglish using Roman letters (fun, readable on screen).')
    prompt = f"""You are a top Indian YouTube scriptwriter making a HIGH-ENERGY, FUNNY, colorful 3D-cartoon explainer.
Tone: fast, punchy desi comedy: playful exaggeration, relatable jokes, roast-style one-liners, rhetorical questions,
surprise twists, a cliffhanger before each reveal. Original writing only; do not imitate any specific creator or copy any script.
Topic: "{topic}". Style: {style}. Format: {'YouTube Short (vertical, under 50 seconds)' if fmt == 'short' else 'YouTube video 3-4 minutes'}.
Facts must be TRUE and verifiable. Make exactly {n} scenes, {words}. Scene 1 opens with a killer hook (first 3 seconds).
The last scene is a funny outro plus a one-line ask to like and subscribe.
Voice lines are read by text-to-speech: short sentences (max ~12 words), write numbers as words, no emojis, no markdown,
no brackets, no stage directions. {rules}
Return ONLY JSON:
{{"title": str (catchy, under 70 chars),
 "description": str (2-4 lines),
 "tags": [8 strings],
 "main_character": str (ONE recurring funny 3D cartoon character: look, outfit, colors; in English),
 "thumbnail_text": str (max 4 words, punchy, ENGLISH/ROMAN letters, curiosity or shock),
 "thumbnail_prompt": str (English: shocked/excited close-up of the main character, vivid contrasting colors, dramatic background, empty space for text, no text in image),
 "thumbnail_keywords": str (2-3 English words),
 "scenes": [{{"voice": str, "caption": str,
   "image_prompt": str (English; MUST start with the exact main_character description, then the action, funny expression, background, camera angle, bright colorful palette; no text in image),
   "video_prompt": str (English; 5-second camera and character motion for an AI video tool),
   "keywords": str (2-3 English words)}}]}}"""
    return gemini_json(prompt)


# ---------- 2. IMAGES: Cloudflare -> Hugging Face -> Pollinations -> Pexels -> placeholder ----------
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
STYLE = (", 3D Pixar-style animated movie render, vibrant saturated colors, soft studio lighting, "
         "expressive funny cartoon character, ultra detailed, no text, no watermark")
DEAD = set()


def save_fit(data, path, w, h):
    path.write_bytes(data)
    ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS).save(path, quality=92)


def is_img(r):
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("image")


def try_cloudflare(prompt, kw, w, h, seed):
    acc, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not (acc and tok):
        return None
    model = os.environ.get("CF_MODEL", "@cf/bytedance/stable-diffusion-xl-lightning")
    gw, gh = (w // 8) * 8, (h // 8) * 8
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}",
                      headers={"Authorization": "Bearer " + tok},
                      json={"prompt": prompt + STYLE, "width": gw, "height": gh, "num_steps": 8}, timeout=180)
    ct = r.headers.get("content-type", "")
    if r.status_code == 200 and ct.startswith("image"):
        return r.content
    if r.status_code == 200 and "json" in ct:
        b64 = (r.json().get("result") or {}).get("image")
        if b64:
            return base64.b64decode(b64)
    print(f"  Cloudflare: HTTP {r.status_code} {r.text[:150]!r}")
    if r.status_code in (400, 401, 403, 404):
        DEAD.add("cloudflare")
    return None


def try_huggingface(prompt, kw, w, h, seed):
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        return None
    r = requests.post("https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
                      headers={"Authorization": "Bearer " + tok},
                      json={"inputs": prompt + STYLE, "parameters": {"width": w, "height": h}}, timeout=180)
    if is_img(r):
        return r.content
    print(f"  HuggingFace: HTTP {r.status_code} {r.text[:100]!r}")
    if r.status_code in (401, 402, 403):
        DEAD.add("huggingface")
    return None


def try_pollinations(prompt, kw, w, h, seed):
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt + STYLE)
           + f"?width={w}&height={h}&nologo=true&seed={seed}")
    headers = dict(UA)
    if os.environ.get("POLLINATIONS_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["POLLINATIONS_KEY"]
    r = requests.get(url, headers=headers, timeout=90)
    if is_img(r):
        return r.content
    print(f"  Pollinations: HTTP {r.status_code} {r.text[:100]!r}")
    if r.status_code in (401, 403, 429):
        DEAD.add("pollinations")
    return None


def try_pexels(prompt, kw, w, h, seed):
    key = os.environ.get("PEXELS_KEY")
    if not key:
        return None
    query = kw or " ".join(prompt.split()[:3])
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                     params={"query": query, "per_page": 15, "orientation": "portrait" if h > w else "landscape"}, timeout=60)
    if r.status_code != 200:
        print(f"  Pexels: HTTP {r.status_code} {r.text[:100]!r}")
        if r.status_code in (401, 403):
            DEAD.add("pexels")
        return None
    photos = r.json().get("photos", [])
    if not photos:
        return None
    pic = random.Random(seed).choice(photos)["src"]
    img = requests.get(pic.get("large2x") or pic["original"], timeout=90)
    return img.content if is_img(img) else None


PROVIDERS = [("cloudflare", try_cloudflare), ("huggingface", try_huggingface),
             ("pollinations", try_pollinations), ("pexels", try_pexels)]


def make_image(prompt, path, w, h, seed, kw=""):
    for attempt in range(2):
        for name, fn in PROVIDERS:
            if name in DEAD:
                continue
            try:
                data = fn(prompt, kw, w, h, seed)
                if data:
                    save_fit(data, path, w, h)
                    print(f"  image: {name} OK")
                    return
            except Exception as e:
                print(f"  {name} error:", e)
        time.sleep(3)
    print("  ⚠ image fail, placeholder use kar raha hu")
    rnd = random.Random(seed)
    top, bot = [tuple(rnd.randint(20, 120) for _ in range(3)) for _ in range(2)]
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for c in range(3):
        arr[:, :, c] = np.linspace(top[c], bot[c], h)[:, None]
    Image.fromarray(arr).save(path, quality=92)


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
