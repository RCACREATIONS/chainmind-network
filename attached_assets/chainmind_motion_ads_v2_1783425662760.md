# ChainMind Motion Ad Generator — Real Implementation Spec (v2)

Built against your actual repos: `chainmind-network` (node) and `chainmind.com.ng` (web/API).
This replaces the earlier standalone-Flask version — it plugs into the job queue you
already have instead of bolting on a separate server.

---

## 0. What already exists (don't touch/duplicate this)

- `jobs` table with `job_type`, `image_params`, `file_ids`, `result_images` JSON columns,
  added safely via `ensure_jobs_columns()` in `api/_helpers.php` (checks
  `INFORMATION_SCHEMA` before each `ALTER TABLE` — idempotent, safe to run every request).
- `api/image-gen.php` — the pattern for queuing a specialized job: checks for a
  capable node online, deducts credits, inserts a `jobs` row with `job_type='image_gen'`.
- `api/node/claim-job.php` — nodes poll this; it's supposed to filter by job type using
  an `X-Node-Capabilities` header, but no node currently sends that header (see below).
- `api/node/submit-result.php` — accepts `result_images` (base64 array), pays out IQ,
  updates node reputation. This is the completion path for every job type.
- `api/upload.php` — general file upload/store, used for chat file attachments. Not
  used for job outputs, so we won't route video through it (see §4 on why).
- `node/central_client.py` — the node's poll loop. `_poll_once()` claims a job,
  `_run_job()` processes it. **Currently `_run_job()` ignores `job_type` entirely and
  always calls `ollama.generate()`** — this is the gap described above.

## 1. Fix capability routing first (small, safe change, unlocks everything else)

This makes `image_gen` route correctly too, as a bonus — no existing behavior changes
for nodes that only do text, they just keep matching `job_type='text'` as before.

**`config.yaml`** — add a capabilities list (node self-declares what it can do):
```yaml
node:
  name: chainmind-node-1
  host: 0.0.0.0
  port: 8000
  api_token:
  capabilities: [text]   # auto-extended at runtime if motion_ads deps are installed
```

**`node/central_client.py`** — detect optional deps once at startup, send capabilities
in both the heartbeat and the claim-job poll:

```python
# near the top of central_client.py, module level
def _detect_capabilities(base: list[str]) -> list[str]:
    caps = list(base)
    try:
        import rembg, moviepy, edge_tts  # noqa: F401
        caps.append("motion_ad")
    except ImportError:
        pass
    return caps
```

In `CentralClient.__init__`, store it:
```python
self.capabilities = _detect_capabilities(self.node_cfg.get("capabilities", ["text"]))
```

In `_send_heartbeat()`, add to `payload`:
```python
payload["capabilities"] = ",".join(self.capabilities)
```

In `_poll_once()`, add the header to the claim-job request:
```python
r = await self._http.get(
    f"{self.base_url}/api/node/claim-job.php",
    headers={"X-Node-Capabilities": ",".join(self.capabilities)},
)
```

**`api/node/heartbeat.php`** — accept and store capabilities (nodes table already has
the column, per `claim-job.php`'s own `UPDATE ... SET capabilities = ?`):
```php
$capabilities = substr(trim($b['capabilities'] ?? ''), 0, 255);
// add to the INSERT ... ON DUPLICATE KEY UPDATE:
//   capabilities = VALUES(capabilities)
```
Add `capabilities` to both the column list and the `VALUES(...)` tuple in the existing
`INSERT INTO nodes (...) VALUES (...) ON DUPLICATE KEY UPDATE ...` statement.

**`node/central_client.py` → `_run_job()`** — dispatch on job_type instead of always
calling ollama. This is the key change; wrap it so nothing about the existing text path
changes:

```python
async def _poll_once(self):
    r = await self._http.get(
        f"{self.base_url}/api/node/claim-job.php",
        headers={"X-Node-Capabilities": ",".join(self.capabilities)},
    )
    # ... existing 402 handling unchanged ...
    data = r.json()
    job = data.get("job")
    if not job:
        return

    job_id = job["id"]
    job_type = job.get("job_type", "text")

    if job_type == "motion_ad":
        await self._run_motion_ad_job(job)   # new method, see §3
    else:
        # existing text-path logic, completely unchanged
        prompt = job.get("prompt", "")
        model  = job.get("model")
        system = job.get("system_prompt", "")
        await self._run_job(job_id, prompt, model, system)
```

No existing job ever hits the new branch, so this is non-breaking by construction.

---

## 2. Free stock images — no API key, ever

Skip Pexels/Pixabay (both require a free key). Use these two, which need **zero
registration**:

1. **Openverse API** — `https://api.openverse.org/v1/images/?q=<query>` — aggregates
   Wikimedia Commons, Flickr Commons, museum archives, etc. Returns license info per
   image (`cc0`, `pdm`, `by`, `by-sa`, ...). No key, generous rate limit for anonymous use.
2. **Wikimedia Commons API** — `https://commons.wikimedia.org/w/api.php` — fallback if
   Openverse has no good match. Also no key.

Prefer `cc0`/`pdm` results (no attribution needed) for ad content; if only an
attribution-required (`by`/`by-sa`) result is available, keep a small credit caption
so you're covered (a couple of words, bottom corner, on-screen for ~1s — cheap insurance,
not a big design compromise).

```python
# node/motion_ads/stock_fetch.py
import requests
import os

def search_openverse(query: str, per_page: int = 6) -> list[dict]:
    resp = requests.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "page_size": per_page, "license_type": "commercial"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    # Sort so cc0/pdm (no attribution) come first
    def _rank(r):
        return 0 if r.get("license") in ("cc0", "pdm") else 1
    results.sort(key=_rank)
    return [
        {
            "url": r["url"],
            "license": r.get("license", "unknown"),
            "needs_attribution": r.get("license") not in ("cc0", "pdm"),
            "creator": r.get("creator", ""),
            "source": r.get("foreign_landing_url", ""),
        }
        for r in results
        if r.get("url")
    ]

def search_wikimedia(query: str, per_page: int = 6) -> list[dict]:
    resp = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": per_page,
            "prop": "imageinfo", "iiprop": "url|extmetadata",
        },
        headers={"User-Agent": "ChainMindMotionAds/1.0 (chainmind.com.ng)"},
        timeout=10,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("url"):
            out.append({
                "url": info["url"],
                "license": "wikimedia",
                "needs_attribution": True,
                "creator": "Wikimedia Commons",
                "source": info.get("descriptionurl", ""),
            })
    return out

def download_image(url: str, dest_path: str) -> str:
    resp = requests.get(url, timeout=15, headers={"User-Agent": "ChainMindMotionAds/1.0"})
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path

def fetch_and_prepare_stock_image(query: str, workdir: str) -> dict:
    """
    Returns {"path": <bg-removed PNG path>, "needs_attribution": bool, "creator": str}
    """
    from .bg_remover import remove_background

    results = search_openverse(query) or search_wikimedia(query)
    if not results:
        raise ValueError(f"No free stock image found for query: {query}")

    best = results[0]
    raw_path = os.path.join(workdir, "stock_raw.jpg")
    download_image(best["url"], raw_path)

    clean_path = os.path.join(workdir, "stock_clean.png")
    try:
        remove_background(raw_path, clean_path)
    except Exception:
        clean_path = raw_path  # fall back to un-cut image rather than fail the job

    return {
        "path": clean_path,
        "needs_attribution": best["needs_attribution"],
        "creator": best.get("creator", ""),
    }
```

No caching layer is required for correctness, but add a simple on-disk cache keyed by
query (24h TTL) once this is working, to cut down on repeat network calls for common
product categories.

---

## 3. Sound effects — hosted on your web server, node downloads & caches

You already have a working static-file web server (`chainmind.com.ng`), so host the
sfx library there rather than depending on a third party at generation time — that's
what makes this "full proof" (no external outage/rate-limit can break a render).

**Where to source the actual sound files (one-time, do this yourself):**
Mixkit's free sound effects library (`mixkit.co/free-sound-effects/`) requires no
account or key to download, and its license permits commercial use in projects like
ads. Download a small set per category and upload them yourself — this spec assumes
the files already exist on your server; it doesn't fetch them from Mixkit at runtime.

**Folder layout on `chainmind.com.ng`:**
```
assets/sfx/
  whoosh/       (scene transitions)
    whoosh_1.mp3
    whoosh_2.mp3
  pop/          (text/logo pop-ins)
    pop_1.mp3
  chime/        (CTA reveal / highlight)
    chime_1.mp3
  swipe/        (slide transitions)
    swipe_1.mp3
  impact/       (price/offer reveal)
    impact_1.mp3
```

**`api/sfx-manifest.php`** — new, public, read-only, no auth needed (these are just
static asset filenames, nothing sensitive):
```php
<?php
require_once __DIR__ . '/_helpers.php';
cors();

$base = __DIR__ . '/../assets/sfx';
$manifest = [];

foreach (scandir($base) as $category) {
    if ($category === '.' || $category === '..') continue;
    $dir = $base . '/' . $category;
    if (!is_dir($dir)) continue;
    $files = [];
    foreach (scandir($dir) as $file) {
        if (str_ends_with($file, '.mp3')) {
            $files[] = [
                'name' => $file,
                'url'  => "https://chainmind.com.ng/assets/sfx/{$category}/{$file}",
            ];
        }
    }
    if ($files) $manifest[$category] = $files;
}

json_ok(['categories' => $manifest]);
```

**Node side — fetch manifest once, cache files locally, never re-download unless missing:**
```python
# node/motion_ads/sfx_fetch.py
import os
import requests
import random

SFX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "sfx_cache")
MANIFEST_URL = "https://chainmind.com.ng/api/sfx-manifest.php"

_manifest_cache = None

def get_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        resp = requests.get(MANIFEST_URL, timeout=10)
        resp.raise_for_status()
        _manifest_cache = resp.json().get("categories", {})
    return _manifest_cache

def get_sfx(category: str) -> str | None:
    """
    Returns a local file path to a sound effect in the given category,
    downloading + caching it if not already present. Returns None if the
    category has no files (pipeline should just skip that sound, not fail).
    """
    manifest = get_manifest()
    options = manifest.get(category, [])
    if not options:
        return None

    choice = random.choice(options)
    os.makedirs(SFX_CACHE_DIR, exist_ok=True)
    local_path = os.path.join(SFX_CACHE_DIR, f"{category}_{choice['name']}")

    if not os.path.exists(local_path):
        resp = requests.get(choice["url"], timeout=15)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)

    return local_path
```

Fully proof against a missing category or a bad manifest fetch — both return `None`
rather than raising, and the animator (below) just skips the audio layer if `None`.

---

## 4. Video output path — direct upload, not base64-in-JSON

Rendered ads will be a few MB — base64 through `submit-result.php`'s JSON body works
for small text/image payloads but is a bad fit here (33% size bloat, large JSON parse
on every poll). Add one small dedicated endpoint instead:

**`api/node/submit-video.php`** (new, follows the same auth pattern as
`submit-result.php`):
```php
<?php
require_once __DIR__ . '/../_helpers.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') json_err('POST only', 405);
validate_node_secret();
$node_id = get_node_id();

$job_id = trim($_POST['job_id'] ?? '');
if (!$job_id) json_err('job_id is required');

$stmt = db()->prepare("SELECT id, claimed_by FROM jobs WHERE id = ?");
$stmt->execute([$job_id]);
$job = $stmt->fetch();
if (!$job) json_err('Job not found', 404);
if ($job['claimed_by'] !== $node_id) json_err('Job belongs to a different node', 403);

if (empty($_FILES['video'])) json_err('video file field is required', 400);
if ($_FILES['video']['size'] > 30 * 1024 * 1024) json_err('Video exceeds 30MB limit', 400);

$dest_dir = __DIR__ . '/../../uploads/generated_ads';
if (!is_dir($dest_dir)) mkdir($dest_dir, 0755, true);

$filename = $job_id . '.mp4';
$dest_path = $dest_dir . '/' . $filename;

if (!move_uploaded_file($_FILES['video']['tmp_name'], $dest_path)) {
    json_err('Failed to save video', 500);
}

$video_url = "https://chainmind.com.ng/uploads/generated_ads/{$filename}";

db()->exec("
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'jobs' AND COLUMN_NAME = 'result_video_url'
") or true;
// (column added via ensure_jobs_columns() — see below, this line is just illustrative)

db()->prepare("UPDATE jobs SET result_video_url = ? WHERE id = ?")
    ->execute([$video_url, $job_id]);

json_ok(['video_url' => $video_url]);
```

Add the column to `ensure_jobs_columns()` in `api/_helpers.php` (same idempotent
pattern already used there):
```php
'result_video_url' => "ALTER TABLE jobs ADD COLUMN result_video_url VARCHAR(500) NULL",
```

Update `api/job.php` to return it (one extra field, fully backward compatible):
```php
// add 'result_video_url' to the SELECT column list and to the json_ok(...) array
```

Node still calls `submit-result.php` afterward with `status=done` so the existing IQ
payout / reputation logic fires unchanged — the video upload and the result submission
are two small steps, not a replacement for the existing completion flow.

---

## 5. The ad-copy generation call — use the node's own local model, not an HTTP round-trip

Since this runs *inside* the node process, call the node's own `OllamaClient` directly
instead of hitting `chainmind.com.ng`'s public API from itself:

```python
# node/motion_ads/script_gen.py
import json

async def generate_ad_script(ollama_client, model: str, business_name: str,
                              product: str, offer: str, tone: str) -> dict:
    prompt = f"""Generate ad copy for a short promotional video. Return ONLY valid JSON,
no markdown, no preamble. Format:
{{"hook": "...", "body": "...", "cta": "...", "image_query": "...", "sfx_moments": ["whoosh","pop","chime"]}}

Business: {business_name}
Product/offer: {product} - {offer}
Tone: {tone}
"""
    resp = await ollama_client.generate(model=model, prompt=prompt)
    content = resp.get("response", "").strip().strip("```json").strip("```")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "hook": f"{business_name} has something for you",
            "body": f"{product} — {offer}",
            "cta": "Order now",
            "image_query": product,
            "sfx_moments": ["whoosh", "pop", "chime"],
        }
```

`sfx_moments` lets the LLM pick which of your 5 categories fits each scene, so the
sound design varies per ad instead of being hardcoded.

---

## 6. Animator — Ken Burns + text + sfx layered onto the voiceover track

Same moviepy approach as before, extended to mix sfx at scene-transition points:

```python
# node/motion_ads/animator.py
from moviepy.editor import (
    ImageClip, CompositeVideoClip, TextClip, AudioFileClip,
    CompositeAudioClip, concatenate_videoclips
)

def build_ad_video(
    image_paths: list[str], hook: str, body: str, cta: str,
    brand_color: str, logo_path: str | None, voiceover_path: str | None,
    sfx_paths: dict,  # {"scene1": path|None, "scene2": path|None, "scene3": path|None}
    output_path: str, size=(1080, 1920),
):
    scene_duration = 3.5
    clips, audio_layers = [], []
    t_cursor = 0.0

    def _scene(image_path, text, zoom_start, zoom_end, sfx_key):
        nonlocal t_cursor
        bg = (ImageClip(image_path)
              .set_duration(scene_duration)
              .resize(height=size[1])
              .resize(lambda t: zoom_start + (zoom_end - zoom_start) * (t / scene_duration))
              .set_position("center"))
        txt = (TextClip(text, fontsize=70, color="white", font="Arial-Bold",
                         size=(size[0] - 100, None), method="caption")
               .set_duration(scene_duration).set_position(("center", 0.75), relative=True))
        sfx = sfx_paths.get(sfx_key)
        if sfx:
            audio_layers.append(AudioFileClip(sfx).set_start(t_cursor).volumex(0.6))
        t_cursor += scene_duration
        return CompositeVideoClip([bg, txt], size=size).set_duration(scene_duration)

    clips.append(_scene(image_paths[0], hook, 1.0, 1.15, "scene1"))
    img2 = image_paths[1] if len(image_paths) > 1 else image_paths[0]
    clips.append(_scene(img2, body, 1.15, 1.0, "scene2"))

    # CTA scene on brand color
    from PIL import Image
    import numpy as np
    solid = Image.new("RGB", size, brand_color)
    layers = [ImageClip(np.array(solid)).set_duration(scene_duration)]
    if logo_path:
        layers.append(ImageClip(logo_path).set_duration(scene_duration)
                       .resize(width=size[0] // 3).set_position(("center", 0.35), relative=True))
    layers.append(TextClip(cta, fontsize=70, color="white", font="Arial-Bold",
                            size=(size[0] - 100, None), method="caption")
                  .set_duration(scene_duration).set_position(("center", 0.7), relative=True))
    if sfx_paths.get("scene3"):
        audio_layers.append(AudioFileClip(sfx_paths["scene3"]).set_start(t_cursor).volumex(0.6))
    clips.append(CompositeVideoClip(layers, size=size).set_duration(scene_duration))

    final = concatenate_videoclips(clips, method="compose")

    audio_tracks = list(audio_layers)
    if voiceover_path:
        audio_tracks.append(AudioFileClip(voiceover_path).volumex(1.0))
    if audio_tracks:
        final = final.set_audio(CompositeAudioClip(audio_tracks))

    final.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")
    return output_path
```

---

## 7. Full pipeline + node dispatch method

```python
# node/motion_ads/pipeline.py
import os, uuid
from .bg_remover import remove_background
from .stock_fetch import fetch_and_prepare_stock_image
from .script_gen import generate_ad_script
from .voiceover import generate_voiceover
from .sfx_fetch import get_sfx
from .animator import build_ad_video

async def run_pipeline(ollama_client, model: str, params: dict, user_image_paths: list[str] | None) -> str:
    job_id = params.get("job_id", str(uuid.uuid4()))
    workdir = f"data/motion_ads/{job_id}"
    os.makedirs(workdir, exist_ok=True)

    copy = await generate_ad_script(
        ollama_client, model,
        params["business_name"], params["product"], params["offer"], params.get("tone", "friendly"),
    )

    image_paths, attributions = [], []
    if user_image_paths:
        for i, path in enumerate(user_image_paths):
            clean = os.path.join(workdir, f"user_clean_{i}.png")
            try:
                remove_background(path, clean)
            except Exception:
                clean = path
            image_paths.append(clean)
    else:
        stock = fetch_and_prepare_stock_image(copy["image_query"], workdir)
        image_paths.append(stock["path"])
        if stock["needs_attribution"]:
            attributions.append(stock["creator"])

    voice_path = os.path.join(workdir, "voiceover.mp3")
    generate_voiceover(f"{copy['hook']}. {copy['body']}. {copy['cta']}.", voice_path)

    moments = copy.get("sfx_moments", ["whoosh", "pop", "chime"])
    sfx_paths = {
        "scene1": get_sfx(moments[0] if len(moments) > 0 else "whoosh"),
        "scene2": get_sfx(moments[1] if len(moments) > 1 else "pop"),
        "scene3": get_sfx(moments[2] if len(moments) > 2 else "chime"),
    }

    output_path = os.path.join(workdir, "ad.mp4")
    build_ad_video(
        image_paths=image_paths, hook=copy["hook"], body=copy["body"], cta=copy["cta"],
        brand_color=params.get("brand_color", "#7C3AED"),
        logo_path=params.get("logo_path"), voiceover_path=voice_path,
        sfx_paths=sfx_paths, output_path=output_path,
    )
    return output_path
```

**`node/central_client.py`** — the dispatch method referenced in §1:
```python
async def _run_motion_ad_job(self, job: dict):
    import httpx
    from motion_ads.pipeline import run_pipeline  # local import: only touched if capability detected

    job_id = job["id"]
    params = job.get("image_params") or {}
    params["job_id"] = job_id
    file_ids = job.get("file_ids") or []

    user_image_paths = None  # resolve from file_ids via your existing upload storage if provided

    try:
        models = await self.ollama.list_local_models()
        model = models[0]["name"] if models else "tinyllama"

        output_path = await run_pipeline(self.ollama, model, params, user_image_paths)

        with open(output_path, "rb") as f:
            upload_resp = await self._http.post(
                f"{self.base_url}/api/node/submit-video.php",
                data={"job_id": job_id},
                files={"video": ("ad.mp4", f, "video/mp4")},
            )
        upload_resp.raise_for_status()

        await self._http.post(f"{self.base_url}/api/node/submit-result.php", json={
            "job_id": job_id, "status": "done",
            "result": upload_resp.json().get("video_url", ""),
            "tokens_in": 0, "tokens_out": 0, "duration_ms": 0,
        })
        self._jobs_done += 1
        log.info(f"Motion ad job {job_id[:8]}… done")

    except Exception as e:
        log.error(f"Motion ad job {job_id[:8]}… failed: {e}")
        await self._http.post(f"{self.base_url}/api/node/submit-result.php", json={
            "job_id": job_id, "status": "error", "result": str(e),
        })
```

---

## 8. Web endpoint to queue a motion-ad job — `api/motion-ad.php`

Copy of the `image-gen.php` pattern, adapted:

```php
<?php
require_once __DIR__ . '/_helpers.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') json_err('POST only', 405);

session_start();
$api_key_id = null; $source = 'webchat';
$key_header = $_SERVER['HTTP_X_API_KEY'] ?? '';
if ($key_header) {
    $keyRow = validate_api_key();
    $source = 'api';
    $api_key_id = (int)$keyRow['id'];
}

ensure_jobs_columns();

sweep_offline_nodes();
$capable = (int)db()->query("
    SELECT COUNT(*) FROM nodes WHERE status='online' AND capabilities LIKE '%motion_ad%'
")->fetchColumn();
if ($capable === 0) {
    json_err('No motion-ad-capable nodes online right now. Try again shortly.', 503);
}

$b = require_json_body();
$business_name = trim($b['business_name'] ?? '');
$product       = trim($b['product'] ?? '');
$offer         = trim($b['offer'] ?? '');
$tone          = trim($b['tone'] ?? 'friendly');
$brand_color   = trim($b['brand_color'] ?? '#7C3AED');
$file_ids      = $b['file_ids'] ?? [];   // from /api/upload.php if user supplied product photos

if (!$business_name || !$product) json_err('business_name and product are required', 400);

require_once __DIR__ . '/billing/credits.php';
$ad_cost = 25;  // motion ad costs more compute than a single image_gen call
if ($api_key_id) {
    $balance = credits_get($api_key_id);
    if ($balance < $ad_cost) {
        json_err("Insufficient credits. Balance: {$balance}, required: {$ad_cost}.", 402);
    }
}

$job_id = uuid4();
$image_params = json_encode([
    'business_name' => $business_name, 'product' => $product, 'offer' => $offer,
    'tone' => $tone, 'brand_color' => $brand_color,
]);

db()->prepare("
    INSERT INTO jobs (id, prompt, model, system_prompt, status, source, api_key_id,
                       job_type, image_params, file_ids, created_at)
    VALUES (?, '', '', '', 'pending', ?, ?, 'motion_ad', ?, ?, NOW())
")->execute([$job_id, $source, $api_key_id, $image_params, json_encode($file_ids)]);

if ($api_key_id) credits_deduct($api_key_id, $job_id, $ad_cost);

json_ok([
    'job_id' => $job_id, 'status' => 'pending',
    'poll_url' => "/api/job.php?id={$job_id}",
    'message' => 'Motion ad queued. Poll poll_url — result_video_url will contain the MP4 link once done.',
    'credits_used' => $ad_cost,
]);
```

`claim-job.php` already handles new job types cleanly — just extend its capability
check the same way `image_gen`/`vision`/`file_qa` are checked:
```php
$has_motion_ad = in_array('motion_ad', $node_caps, true);
if ($has_motion_ad) $allowed_types[] = "'motion_ad'";
```

---

## 9. Why this is safe for what you already have

- Every new DB column goes through the existing `ensure_jobs_columns()` idempotent
  migration helper — no manual `ALTER TABLE`, no risk of duplicate-column errors.
- `job_type` dispatch in `central_client.py` only branches into new code for
  `job_type == "motion_ad"`; every existing text job takes the exact same code path
  as before.
- Nodes without `rembg`/`moviepy`/`edge-tts` installed never advertise `motion_ad`
  capability (`_detect_capabilities()` fails the import silently and just doesn't add
  it) — they keep doing text-only work, untouched.
- The capability-routing fix is additive: an empty `capabilities` list still falls
  back to `"1=1"` server-side exactly as it does today, so nodes you haven't upgraded
  yet keep working exactly as they do now.
- Stock images and sound effects both fail soft (return `None`/fallback image) rather
  than raising, so a bad network call never takes down a job or the node process.
- Video goes through its own upload endpoint, not through the same JSON path as text
  results, so existing polling/result-size assumptions for text and image jobs are
  untouched.

## 10. What you need to do manually (not code)

1. `pip install rembg onnxruntime moviepy pillow edge-tts` on any node you want to
   handle motion ads (not all of them need to — only ones with spare CPU headroom).
2. Source and upload an initial batch of sound effects into `assets/sfx/{category}/`
   on the web server (Mixkit's free library, no login needed, is the quickest source).
3. Run the DB migration once (or just let `ensure_jobs_columns()` handle it on first
   request — it will).
4. Decide per-node whether to enable this — since it's CPU-bound (Ken Burns render +
   bg removal), a node on shared/low-spec hosting will be slow at it; your planned
   RackNerd VPS is a better home for this specific job type once migrated.
