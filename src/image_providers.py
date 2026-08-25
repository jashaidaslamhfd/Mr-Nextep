"""
image_providers.py
--------------------
SHARED provider registry — dono jagah use hota hai:
  1. src/image_generator.py          (live, per-video scene images)
  2. scripts/generate_fallback_images.py  (one-time 500-image pool builder)

Pehle Pollinations hardcoded tha har jagah, isliye agar Pollinations
rate-limit ho jaye to poora bulk-generation atak jata tha. Ab yahan ek
hi jagah provider list maintain hoti hai — jitne providers yahan add
karoge, dono scripts automatically unhe fallback order mein try karenge.

Har provider function ka signature same hai:
    fn(prompt: str, seed: int, scene_text: str | None) -> (bytes, ext)
        - prompt      : underscore-joined text (Pollinations-style URL prompt)
        - seed        : random int, variety ke liye
        - scene_text  : original human-readable text (APIs jo JSON body
                         lete hain unke liye, jaise HuggingFace/Gemini)
        - Return      : (image_bytes, file_extension e.g. "jpg"/"png")
        - Fail/Quota  : RuntimeError ya RateLimitError raise karo

Naya provider add karne ke liye: neeche TEMPLATE copy karo, apna function
likho, aur PROVIDER_REGISTRY list mein ek entry add kar do. Bas itna hi —
generate_images() aur generate_fallback_images.py mein kuch badalne ki
zaroorat nahi.
"""

import os
import time
import random
import base64
import requests

REQUEST_TIMEOUT = 30

POLLINATIONS_TIMEOUT = 15

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
HF_API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
GEMINI_IMAGE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent"


class RateLimitError(RuntimeError):
    """Provider ka quota/rate-limit khatam ho gaya — turant agle provider pe jump karo."""
    pass


# ---------------------------------------------------------------------------
# 1) POLLINATIONS - flux model (free, no key)
# ---------------------------------------------------------------------------
import urllib.parse

def _pollinations_request(prompt, seed, model):
    encoded_prompt = urllib.parse.quote(str(prompt or ""))
    url = f"{POLLINATIONS_URL}/{encoded_prompt}?width=1080&height=1920&seed={seed}&model={model}&nologo=true"
    last_status = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=POLLINATIONS_TIMEOUT)
            if response.status_code == 200 and len(response.content) > 2000:
                return response.content
            last_status = response.status_code
            if response.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            break
        except requests.exceptions.RequestException as e:
            last_status = str(e)
            break
            
    if last_status == 429:
        raise RateLimitError(f"Pollinations({model}): rate limited")
    raise RuntimeError(f"Pollinations({model}) bad response: {last_status}")


def gen_pollinations_flux(prompt, seed, scene_text=None):
    return _pollinations_request(prompt, seed, "flux"), "jpg"


# ---------------------------------------------------------------------------
# 2) POLLINATIONS - turbo model, fresh seed (free, no key, genuinely
#    different request rather than a duplicate retry of layer 1)
# ---------------------------------------------------------------------------
def gen_pollinations_turbo(prompt, seed, scene_text=None):
    new_seed = random.randint(10000, 99999)
    return _pollinations_request(prompt, new_seed, "turbo"), "jpg"


# ---------------------------------------------------------------------------
# 3) HUGGING FACE Inference API (needs HF_API_KEY env var)
# ---------------------------------------------------------------------------
def gen_huggingface(prompt, seed, scene_text=None):
    hf_key = os.environ.get("HF_API_KEY")
    if not hf_key:
        raise RuntimeError("HF_API_KEY not set")
    text = scene_text or prompt.replace("_", " ")
    headers = {"Authorization": f"Bearer {hf_key}"}
    response = requests.post(HF_API_URL, headers=headers, json={"inputs": text}, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RateLimitError("HuggingFace: rate limited")
    if response.status_code == 200 and response.headers.get("content-type", "").startswith("image"):
        return response.content, "jpg"
    raise RuntimeError(f"HuggingFace bad response: {response.status_code} {response.text[:150]}")


# ---------------------------------------------------------------------------
# 4) GOOGLE GEMINI image generation (needs GEMINI_API_KEY env var,
#    free ~50 requests/day via Google AI Studio, no card needed)
# ---------------------------------------------------------------------------
def gen_gemini(prompt, seed, scene_text=None):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    text = scene_text or prompt.replace("_", " ")
    payload = {
        "contents": [{"parts": [{"text": f"Generate a photorealistic vertical image: {text}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    url = f"{GEMINI_IMAGE_URL}?key={gemini_key}"
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RateLimitError("Gemini: quota exceeded")
    if response.status_code != 200:
        raise RuntimeError(f"Gemini bad response: {response.status_code} {response.text[:150]}")

    data = response.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"]), "png"
    raise RuntimeError("Gemini response contained no image data")


def gen_deepai(prompt, seed, scene_text=None):
    api_key = os.environ.get("DEEPAI_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPAI_API_KEY not set")
    text = scene_text or prompt.replace("_", " ")
    resp = requests.post(
        "https://api.deepai.org/api/text2img",
        data={"text": text},
        headers={"api-key": api_key},
        timeout=60,
    )
    if resp.status_code == 429:
        raise RateLimitError("DeepAI: rate limited")
    if resp.status_code != 200:
        raise RuntimeError(f"DeepAI bad response: {resp.status_code} {resp.text[:150]}")
    data = resp.json()
    img_url = data.get("output_url")
    if not img_url:
        raise RuntimeError(f"DeepAI: no output_url in response: {data}")
    img_resp = requests.get(img_url, timeout=30)
    return img_resp.content, "jpg"


_HORDE_ANON_KEY = "0000000000"

# Run-scoped flag: a secret AI_HORDE_API_KEY that returns 401 InvalidAPIKey
# (expired/typo'ed) is silently downgraded to the anonymous key once, instead
# of failing every AI-Horde scene with the same spammy error for the whole
# run. Detected InvalidAPIKey responses always fall back to anonymous.
_horde_key_invalidated = [False]


def gen_ai_horde(prompt, seed, scene_text=None):
    import logging as _logging
    _hplogger = _logging.getLogger("image_providers")
    text = (scene_text or prompt.replace("_", " "))[:1000]
    headers = {"apikey": os.environ.get("AI_HORDE_API_KEY", _HORDE_ANON_KEY)}

    def _horde_was_invalid(resp):
        """Detect the 401 InvalidAPIKey response from an invalid secret key."""
        if resp.status_code != 401:
            return False
        try:
            payload = resp.json()
        except Exception:
            return False
        return payload.get("rc") == "InvalidAPIKey" or "InvalidAPIKey" in payload.get("message", "")

    size_tiers = [(768, 1344), (640, 1152), (576, 1024), (448, 768), (384, 640), (320, 512)]

    submit = None
    last_size_err = None
    for width, height in size_tiers:
        submit = requests.post(
            "https://aihorde.net/api/v2/generate/async",
            json={
                "prompt": text,
                "params": {
                    "width": width, "height": height, "steps": 30, "n": 1,
                    "sampler_name": "k_euler_a",
                    "cfg_scale": 7,
                },
                "negative_prompt": "blurry, soft focus, low resolution, dull, dark, grainy, distorted, watermark, text, logo",
                "nsfw": False,
                "censor_nsfw": True,
            },
            headers=headers,
            timeout=20,
        )
        if submit.status_code == 429:
            raise RateLimitError("AI Horde: rate limited")
        if submit.status_code == 403:
            # This size tier is over the current demand cap - shrink and retry.
            last_size_err = f"{width}x{height} rejected: {submit.text[:150]}"
            continue
        if _horde_was_invalid(submit):
            # 2026-08-15: the repo secret AI_HORDE_API_KEY is set but invalid
            # (401 InvalidAPIKey - expired or typo). Retry this tier once with
            # the anonymous key and keep going for the whole run.
            if headers["apikey"] != _HORDE_ANON_KEY:
                _hplogger.warning(
                    "AI Horde: secret key invalid (%s) — retrying with "
                    "anonymous key for the rest of this run", submit.text[:120],
                )
                headers = {"apikey": _HORDE_ANON_KEY}
                _horde_key_invalidated[0] = True
                continue
            raise RuntimeError(f"AI Horde submit bad response: {submit.status_code} {submit.text[:150]}")
        if submit.status_code not in (200, 202):
            raise RuntimeError(f"AI Horde submit bad response: {submit.status_code} {submit.text[:150]}")
        break
    else:
        raise RuntimeError(f"AI Horde: all size tiers over demand cap - {last_size_err}")

    job_id = submit.json().get("id")
    if not job_id:
        raise RuntimeError(f"AI Horde: no job id in response: {submit.json()}")

    # Anonymous key = lowest queue priority, so this can take a while. Poll
    # for up to ~60s (12 x 5s); if it's not done by then, give up and let
    # the next provider in the chain take over rather than blocking.
    max_wait_seconds = int(os.environ.get("AI_HORDE_MAX_WAIT", "300"))
    poll_interval = 5
    for _ in range(max(1, max_wait_seconds // poll_interval)):
        time.sleep(poll_interval)
        check = requests.get(f"https://aihorde.net/api/v2/generate/check/{job_id}", timeout=15).json()
        if check.get("done"):
            break
        if check.get("faulted"):
            raise RuntimeError("AI Horde: job faulted")
    else:
        try:
            requests.delete(
                f"https://aihorde.net/api/v2/generate/status/{job_id}",
                headers=headers, timeout=15,
            )
        except Exception:
            pass
        raise RuntimeError(f"AI Horde: timed out after {max_wait_seconds} seconds")

    status = requests.get(f"https://aihorde.net/api/v2/generate/status/{job_id}", timeout=15).json()
    generations = status.get("generations", [])
    if not generations:
        raise RuntimeError("AI Horde: no generations returned")
    img_url = generations[0].get("img")
    if not img_url:
        raise RuntimeError("AI Horde: generation had no image URL")
    img_resp = requests.get(img_url, timeout=30)
    return img_resp.content, "webp"


# ---------------------------------------------------------------------------
# 7) MODELSLAB (needs MODELSLAB_API_KEY, free tier ~100 calls/day, no card)
#    10,000+ models (Flux, SDXL, SD3.5) via one REST endpoint.
# ---------------------------------------------------------------------------
def gen_modelslab(prompt, seed, scene_text=None):
    api_key = os.environ.get("MODELSLAB_API_KEY")
    if not api_key:
        raise RuntimeError("MODELSLAB_API_KEY not set")
    text = scene_text or prompt.replace("_", " ")
    payload = {
        "key": api_key,
        "prompt": text,
        "negative_prompt": "blurry, low quality, watermark",
        "width": "1024",
        "height": "1024",
        "samples": "1",
        "safety_checker": "no",
    }
    resp = requests.post("https://modelslab.com/api/v6/images/text2img", json=payload, timeout=60)
    if resp.status_code == 429:
        raise RateLimitError("ModelsLab: rate limited")
    if resp.status_code != 200:
        raise RuntimeError(f"ModelsLab bad response: {resp.status_code}")
    data = resp.json()
    if data.get("status") not in ("success", "processing"):
        raise RuntimeError(f"ModelsLab error: {data.get('message', data)}")
    images = data.get("output") or data.get("images") or []
    if not images:
        raise RuntimeError("ModelsLab: no image URL returned (may need to poll fetch_result)")
    img_resp = requests.get(images[0], timeout=60)
    return img_resp.content, "jpg"


# ---------------------------------------------------------------------------
# 8) REPLICATE (needs REPLICATE_API_TOKEN, free trial credits on signup)
#    Uses black-forest-labs/flux-schnell, polls until prediction completes.
# ---------------------------------------------------------------------------
def gen_replicate(prompt, seed, scene_text=None):
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")
    text = scene_text or prompt.replace("_", " ")
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    resp = requests.post(
        "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
        headers=headers,
        json={"input": {"prompt": text}},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RateLimitError("Replicate: rate limited")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Replicate bad response: {resp.status_code} {resp.text[:150]}")

    prediction = resp.json()
    get_url = prediction.get("urls", {}).get("get")
    if not get_url:
        raise RuntimeError("Replicate: no polling URL in response")

    for _ in range(20):  # poll up to ~20s
        time.sleep(1)
        poll = requests.get(get_url, headers=headers, timeout=15).json()
        status = poll.get("status")
        if status == "succeeded":
            output = poll.get("output")
            img_url = output[0] if isinstance(output, list) else output
            if not img_url:
                raise RuntimeError("Replicate: succeeded but no output URL")
            img_resp = requests.get(img_url, timeout=30)
            return img_resp.content, "jpg"
        if status == "failed":
            raise RuntimeError(f"Replicate: prediction failed - {poll.get('error')}")
    raise RuntimeError("Replicate: timed out waiting for prediction")


# ---------------------------------------------------------------------------
# TEMPLATE — naya provider add karne ke liye ye copy karein
# ---------------------------------------------------------------------------
def gen_TEMPLATE(prompt, seed, scene_text=None):
    """
    1. os.environ.get("YOUR_KEY_NAME") se key uthao (agar chahiye)
    2. Provider ko request bhejo
    3. Rate-limit/quota mile to RateLimitError raise karo
    4. Koi aur error ho to RuntimeError raise karo
    5. Success par (image_bytes, "jpg"/"png") return karo
    """
    raise NotImplementedError("Ye sirf template hai — PROVIDER_REGISTRY mein register mat karo jab tak likha na ho")


PROVIDER_REGISTRY = [
    {"name": "AI-Horde",           "env_keys": [],                       "generate": gen_ai_horde},
    {"name": "Pollinations-flux",  "env_keys": [],                       "generate": gen_pollinations_flux},
    {"name": "Pollinations-turbo", "env_keys": [],                       "generate": gen_pollinations_turbo},
    {"name": "HuggingFace",        "env_keys": ["HF_API_KEY"],           "generate": gen_huggingface},
    {"name": "Gemini",             "env_keys": ["GEMINI_API_KEY"],       "generate": gen_gemini},
    {"name": "DeepAI",             "env_keys": ["DEEPAI_API_KEY"],       "generate": gen_deepai},
    {"name": "ModelsLab",          "env_keys": ["MODELSLAB_API_KEY"],    "generate": gen_modelslab},
    {"name": "Replicate",          "env_keys": ["REPLICATE_API_TOKEN"],  "generate": gen_replicate},

]


def available_providers():
    """Sirf wo providers return karta hai jinke required env vars set hain
    (no-key providers hamesha available hote hain)."""
    return [p for p in PROVIDER_REGISTRY if all(os.environ.get(k) for k in p["env_keys"])]
              


POLLINATIONS_VIDEO_URL = "https://gen.pollinations.ai/video"
POLLINATIONS_VIDEO_TIMEOUT = int(os.environ.get("POLLINATIONS_VIDEO_TIMEOUT", "90"))


def gen_pollinations_video(prompt: str, scene_text: str, image_path: str = None,
                           model: str = None, duration: str = None):
    """Generate a vertical AI motion clip from text (+ optional source image).
    Returns (bytes, ext) or raises RuntimeError / RateLimitError."""
    import logging as _logging
    _vlogger = _logging.getLogger("image_providers")
    key = os.environ.get("POLLINATIONS_KEY", "")
    if not key:
        raise RuntimeError("POLLINATIONS_KEY not set - AI video layer skipped")
    model = model or os.environ.get("AI_VIDEO_MODEL", "seedance-2.5")
    duration = duration or os.environ.get("AI_VIDEO_DURATION", "4")
    params = {
        "model": model,
        "aspectRatio": os.environ.get("AI_VIDEO_ASPECT", "9:16"),
        "duration": duration,
        "key": key,
    }
    # seedance-2.5 accepts first/last reference frames -> true image-to-video:
    # the rendered scene image becomes frame 1, so the clip visually matches
    # the caption exactly.
    if image_path and os.path.isfile(image_path):
        try:
            with open(image_path, "rb") as fh:
                upload = requests.post(
                    "https://media.pollinations.ai/upload",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (os.path.basename(image_path), fh, "image/jpeg")},
                    timeout=30,
                )
            if upload.status_code == 200:
                data = upload.json()
                media_id = data.get("id")
                if media_id:
                    params["image[0]"] = (
                        str(media_id) if str(media_id).startswith("http")
                        else f"https://media.pollinations.ai/{media_id}"
                    )
                elif data.get("url"):
                    params["image[0]"] = data["url"]
        except Exception as exc:  # media upload is optional - never block the run
            _vlogger.warning(
                "AI-video: reference image upload failed (%s) - text-to-video fallback",
                exc,
            )
    url = f"{POLLINATIONS_VIDEO_URL}/{prompt}"
    resp = requests.get(url, params=params, timeout=POLLINATIONS_VIDEO_TIMEOUT)
    if resp.status_code == 401:
        raise RateLimitError("Pollinations-video: key rejected/missing")
    if resp.status_code == 402:
        raise RateLimitError("Pollinations-video: free Pollen budget exhausted")
    if resp.status_code == 429:
        raise RateLimitError("Pollinations-video: rate limited")
    if resp.status_code == 503:
        raise RuntimeError("Pollinations-video: service busy")
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Pollinations-video bad response: {resp.status_code} {resp.text[:150]}"
        )
    content = resp.content
    if len(content) < 50_000:
        raise RuntimeError("Pollinations-video: response too small")
    if not (b"ftyp" in content[:64] or b"moov" in content[:64]):
        raise RuntimeError("Pollinations-video: response is not a valid MP4")
    return content, "mp4"
