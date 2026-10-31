"""Script writer: Gemini (free) with Cloudflare backup."""
import json, os, re, sys, time
import requests


# ---------- 1. SCRIPT (Gemini free tier) ----------
def gemini_models(key):
    """Preferred model first, then other stable text 'flash' models this key can use (names change often)."""
    first = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    names = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key},
                         params={"pageSize": 200}, timeout=60)
        for m in r.json().get("models", []):
            n = m["name"].split("/")[-1]
            if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n \
                    and not any(x in n for x in ("image", "tts", "audio", "live", "robot", "computer", "native",
                                                 "preview", "omni", "exp")):
                names.append(n)
    except Exception as e:
        print("  model list nahi mili:", e)
    names.sort(key=lambda n: ("lite" in n, [-ord(c) for c in n]))
    return [first] + [n for n in names if n != first][:4]


def valid_script(d):
    return isinstance(d, dict) and isinstance(d.get("scenes"), list) and len(d["scenes"]) > 0 \
        and all(isinstance(x, dict) and x.get("voice") and x.get("image_prompt") for x in d["scenes"])


def cloudflare_json(prompt):
    """Backup writer when Gemini is overloaded: Cloudflare Workers AI (same free token as images)."""
    acc, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not (acc and tok):
        return None
    model = os.environ.get("CF_TEXT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}",
                          headers={"Authorization": "Bearer " + tok},
                          json={"messages": [{"role": "system", "content": "You output only valid JSON, nothing else."},
                                             {"role": "user", "content": prompt}],
                                "max_tokens": 6000, "temperature": 0.9}, timeout=180)
        if r.status_code != 200:
            print(f"  Cloudflare text: HTTP {r.status_code} {r.text[:150]!r}"); return None
        resp = (r.json().get("result") or {}).get("response")
        if isinstance(resp, str):
            resp = re.sub(r"^```(?:json)?|```$", "", resp.strip(), flags=re.M).strip()
            resp = json.loads(resp[resp.index("{"): resp.rindex("}") + 1])
        return resp if valid_script(resp) else None
    except Exception as e:
        print("  Cloudflare text error:", e); return None


def gemini_json(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY set karo (free: https://aistudio.google.com/apikey)")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    models = gemini_models(key); skip = set(); last = ""
    for rnd in range(4):                      # busy ho to thoda ruk ke dobara, 4 baar
        for model in models:
            if model in skip:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=75)
            except requests.RequestException as e:
                last = f"{model}: {type(e).__name__}"; print("  Gemini fail ->", last); skip.add(model); continue
            if r.status_code == 200:
                try:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                    data = json.loads(text)
                    if valid_script(data):
                        print(f"  Gemini model: {model}"); return data
                    last = f"{model}: JSON adhura tha"
                except Exception as e:
                    last = f"{model}: bad JSON ({e})"
                print("  ", last); continue
            last = f"{model}: HTTP {r.status_code} {r.text[:120]!r}"
            print("  Gemini fail ->", last)
            if r.status_code not in (429, 500, 503):
                skip.add(model)               # 400/403/404: is model ko chhodo
        if rnd < 3:
            wait = 25 * (rnd + 1); print(f"  Gemini busy, {wait} sec ruk ke dobara try..."); time.sleep(wait)
    print("  Gemini nahi chala, Cloudflare backup writer try kar raha hu...")
    data = cloudflare_json(prompt)
    if data:
        print("  Script Cloudflare (Llama) se bani"); return data
    sys.exit("Script nahi ban payi. Gemini aakhri error: " + last)


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
                          
