"""Image maker: Cloudflare -> Hugging Face -> Pollinations -> Pexels -> placeholder."""
import base64, os, random, time, urllib.parse
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageOps


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
  
