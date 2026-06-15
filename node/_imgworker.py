"""
_imgworker.py — Image generation subprocess worker.

Called by image_gen.py via asyncio subprocess.
Reads a JSON payload from stdin, generates an image using diffusers,
writes {"ok": true, "b64": "<base64 PNG>"} to stdout.

The image is NEVER written to disk — it lives only in memory
and is returned as base64 to the caller.
"""

from __future__ import annotations

import base64
import io
import json
import sys


def main():
    try:
        raw    = sys.stdin.read()
        params = json.loads(raw)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"Bad input: {e}"}))
        sys.exit(1)

    prompt          = params.get("prompt", "")
    model_path      = params.get("model_path", "")
    negative_prompt = params.get("negative_prompt", "")
    width           = int(params.get("width",  512))
    height          = int(params.get("height", 512))
    steps           = int(params.get("steps",  20))
    guidance_scale  = float(params.get("guidance_scale", 7.5))
    seed            = int(params.get("seed", -1))

    if not prompt or not model_path:
        print(json.dumps({"ok": False, "error": "prompt and model_path required"}))
        sys.exit(1)

    try:
        import torch
        from pathlib import Path

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32

        model_dir = Path(model_path)
        model_name_lower = model_dir.name.lower()
        is_xl = "xl" in model_name_lower or "sdxl" in model_name_lower

        if is_xl:
            from diffusers import DiffusionPipeline
            pipe = DiffusionPipeline.from_pretrained(
                str(model_dir),
                torch_dtype=dtype,
                use_safetensors=True,
                variant="fp16" if device == "cuda" else None,
            )
        else:
            from diffusers import StableDiffusionPipeline
            pipe = StableDiffusionPipeline.from_pretrained(
                str(model_dir),
                torch_dtype=dtype,
                use_safetensors=True,
            )

        pipe = pipe.to(device)

        if device == "cpu":
            pipe.enable_attention_slicing()
        else:
            pipe.enable_model_cpu_offload()

        generator = None
        if seed >= 0:
            generator = torch.Generator(device=device).manual_seed(seed)

        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
        )

        # Encode PNG in memory — never touch disk
        buf = io.BytesIO()
        result.images[0].save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        print(json.dumps({"ok": True, "b64": b64}))

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
