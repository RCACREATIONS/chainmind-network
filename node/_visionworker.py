"""
_visionworker.py — Vision (LLaVA / Moondream) inference subprocess worker.

Called by vision.py via asyncio subprocess.
Reads a JSON payload from stdin:
  {"prompt": "...", "image_b64": "...", "model_path": "...", "model_id": "...", "max_new_tokens": 512}
Writes {"ok": true, "text": "..."} or {"ok": false, "error": "..."} to stdout.

The image is decoded from base64 in memory — never written to disk.
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

    prompt         = params.get("prompt", "")
    image_b64      = params.get("image_b64", "")
    model_path     = params.get("model_path", "")
    model_id       = params.get("model_id", "")
    max_new_tokens = int(params.get("max_new_tokens", 512))

    if not prompt or not image_b64 or not model_path:
        print(json.dumps({"ok": False, "error": "prompt, image_b64 and model_path required"}))
        sys.exit(1)

    try:
        from PIL import Image
        import torch

        # Decode image from base64 in memory — no disk write
        img_bytes = base64.b64decode(image_b64)
        image     = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32

        is_moondream = "moondream" in model_id.lower()
        is_llava     = "llava" in model_id.lower()

        if is_moondream:
            _run_moondream(model_path, image, prompt, max_new_tokens, device, dtype)
        elif is_llava:
            _run_llava(model_path, image, prompt, max_new_tokens, device, dtype)
        else:
            # Generic: try LLaVA pipeline first, fall back to Moondream
            _run_llava(model_path, image, prompt, max_new_tokens, device, dtype)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


def _run_llava(model_path, image, prompt, max_new_tokens, device, dtype):
    from transformers import LlavaNextProcessor, LlavaNextForConditionalGeneration
    import torch

    processor = LlavaNextProcessor.from_pretrained(model_path)
    model     = LlavaNextForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device)

    conversation = [
        {
            "role":    "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    text_prompt = processor.apply_chat_template(conversation, add_generation_prompt=True)
    inputs = processor(images=image, text=text_prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    answer = processor.decode(output[0], skip_special_tokens=True)
    # Strip the prompt prefix from the output
    if "ASSISTANT:" in answer:
        answer = answer.split("ASSISTANT:")[-1].strip()

    print(json.dumps({"ok": True, "text": answer}))


def _run_moondream(model_path, image, prompt, max_new_tokens, device, dtype):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model     = AutoModelForCausalLM.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device)
    model.eval()

    enc_image = model.encode_image(image)
    answer    = model.answer_question(enc_image, prompt, tokenizer, max_new_tokens=max_new_tokens)

    print(json.dumps({"ok": True, "text": answer}))


if __name__ == "__main__":
    main()
