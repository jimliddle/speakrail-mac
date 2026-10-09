"""Experimental text-only loader for the pinned Speakrail QAT checkpoint.

No requantisation: compressed-tensors int4 words use unsigned nibble values
offset by 8. MLX affine dequantisation is q * scale + bias, hence bias=-8*scale.
The original pinned, patched checkpoint stays unchanged on disk.
"""
import json
import asyncio
import os
from pathlib import Path
import time

import mlx.core as mx
import mlx.nn as nn
from mlx.utils import tree_unflatten
from mlx_lm.models.gemma4_text import Model, ModelArgs
from mlx_lm.tuner.lora import LoRALinear
from prefix_cache import PrefixCache

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models/speakrail-gemma"


def convert_weights(raw):
    weights = {}
    quantized = []
    prefix = "model.language_model."
    for key, value in raw.items():
        if not key.startswith(prefix):
            continue  # Explicitly text-only: no vision or audio encoder.
        name = "model." + key.removeprefix(prefix)
        if name.endswith(".weight_packed"):
            stem = name.removesuffix(".weight_packed")
            source = key.removesuffix(".weight_packed")
            shape = raw[source + ".weight_shape"].tolist()
            scale = raw[source + ".weight_scale"]
            if value.dtype != mx.int32 or list(value.shape) != [shape[0], shape[1] // 8]:
                raise ValueError(f"Unsupported packed shape/dtype: {key}")
            if list(scale.shape) != [shape[0], shape[1] // 32]:
                raise ValueError(f"Unsupported scale shape: {key}")
            if source + ".weight_zero_point" in raw:
                raise ValueError("This loader accepts only symmetric int4 weights")
            weights[stem + ".weight"] = value.view(mx.uint32)
            weights[stem + ".scales"] = scale
            weights[stem + ".biases"] = -8 * scale
            quantized.append(stem)
        elif name.endswith((".weight_shape", ".weight_scale")):
            continue
        else:
            weights[name] = value
    if not quantized:
        raise ValueError("No packed text weights found")
    return weights, quantized


class SpeakrailModel:
    def __init__(self):
        start = time.perf_counter()
        config = json.loads((MODEL_DIR / "model/config.json").read_text())
        quant = config["quantization_config"]
        qweights = quant["config_groups"]["group_0"]["weights"]
        if (config["model_type"] != "gemma4_unified" or
                quant["format"] != "pack-quantized" or
                (qweights["num_bits"], qweights["group_size"], qweights["symmetric"]) != (4, 32, True)):
            raise ValueError("Unexpected checkpoint configuration")
        raw = mx.load(str(MODEL_DIR / "model/model.safetensors"))
        # Both patched tensors must agree before using tied output embeddings.
        emb = raw["model.language_model.embed_tokens.weight"]
        if not bool(mx.array_equal(emb, raw["lm_head.weight"])):
            raise ValueError("Input/output weights differ; tied embeddings would be wrong")
        rows = mx.load(str(MODEL_DIR / "token_rows.safetensors"))["embed_tokens"]
        if not bool(mx.array_equal(emb[6:28], rows)):
            raise ValueError("Trained token rows were not preserved")
        weights, quantized = convert_weights(raw)
        self.model = Model(ModelArgs.from_dict(config["text_config"]))
        quantized_set = set(quantized)
        nn.quantize(self.model, group_size=32, bits=4,
                    class_predicate=lambda path, module: path in quantized_set)
        self.model.load_weights(list(weights.items()), strict=True)
        self.model.eval()
        mx.eval(self.model.parameters())
        self.quantized_modules = quantized
        del raw, weights, emb
        ac = json.loads((MODEL_DIR / "adapter/adapter_config.json").read_text())
        if ac["use_rslora"] or ac["fan_in_fan_out"] or ac["bias"] != "none":
            raise ValueError("Unsupported LoRA variant")
        self.scale = ac["lora_alpha"] / ac["r"]
        tensors = mx.load(str(MODEL_DIR / "adapter/adapter_model.safetensors"))
        modules = dict(self.model.named_modules())
        replacements = []
        consumed = set()
        self.adapters = []
        for key, a in tensors.items():
            if not key.endswith(".lora_A.weight"):
                continue
            stem = key.removesuffix(".lora_A.weight")
            b_key = stem + ".lora_B.weight"
            b = tensors[b_key]
            path = "model." + stem.removeprefix("base_model.model.model.language_model.")
            linear = modules[path]
            layer = LoRALinear.from_base(linear, r=ac["r"], dropout=0, scale=self.scale)
            if a.T.shape != layer.lora_a.shape or b.T.shape != layer.lora_b.shape:
                raise ValueError(f"LoRA shape mismatch: {path}")
            layer.lora_a, layer.lora_b = a.T, b.T
            replacements.append((path, layer))
            self.adapters.append(layer)
            consumed.update((key, b_key))
        if consumed != set(tensors):
            raise ValueError(f"Unmapped adapter tensors: {set(tensors) - consumed}")
        self.model.update_modules(tree_unflatten(replacements))
        self.model.eval()
        mx.eval(self.model.parameters())
        self.load_seconds = time.perf_counter() - start
        self.audit = {"quantized_modules": len(quantized), "lora_modules": len(self.adapters),
                      "token_rows_exact": True, "tied_head_exact": True,
                      "mlx_enable_tf32": os.environ.get("MLX_ENABLE_TF32", "1 (default)"),
                      "load_seconds": self.load_seconds}
        self.prefix_cache = PrefixCache()

    async def prefill_async(self, ids, name, salt=None):
        hit = self.prefix_cache.get(name, salt, ids)
        if hit:
            cache, logits, offset = hit
        else:
            cache, logits, offset = self.model.make_cache(), None, 0
        for start in range(offset, len(ids), 128):
            self.select(name)
            result = self.model(mx.array([ids[start:start + 128]]), cache=cache)
            logits = result[0, -1].astype(mx.float32)
            mx.eval([c.state for c in cache], logits)
            await asyncio.sleep(0)  # Bounded GPU steps allow cancellation and other requests.
        self.prefix_cache.put(name, salt, ids, cache, logits)
        return logits, cache

    def select(self, name):
        if name not in ("speakrail", "speakrail-base"):
            raise ValueError("Unknown model")
        for layer in self.adapters:
            layer.scale = self.scale if name == "speakrail" else 0.0

    def prefill(self, ids):
        cache = self.model.make_cache()
        for offset in range(0, len(ids), 256):
            logits = self.model(mx.array([ids[offset:offset + 256]]), cache=cache)
            mx.eval([c.state for c in cache], logits)
        return logits[0, -1].astype(mx.float32), cache

    def decision(self, ids, allowed, name="speakrail", bias=None):
        self.select(name)
        start = time.perf_counter()
        logits, _ = self.prefill(ids)
        if bias:
            logits = logits.at[mx.array(list(bias))].add(mx.array(list(bias.values())))
        logprobs = logits - mx.logsumexp(logits)
        selected = logprobs[mx.array(allowed)]
        mx.eval(selected)
        choice = allowed[int(mx.argmax(selected))]
        return choice, dict(zip(allowed, selected.tolist())), (time.perf_counter() - start) * 1000


if __name__ == "__main__":
    model = SpeakrailModel()
    print(json.dumps(model.audit, indent=2), flush=True)
