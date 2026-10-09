"""Numerical cross-check of the text architecture against Transformers."""
import json
import os
import unittest

# M5 defaults to reduced-precision float32 matmul. Use full precision for
# architecture parity, not a looser tolerance hiding numerical differences.
os.environ["MLX_ENABLE_TF32"] = "0"
import mlx.core as mx
import numpy as np
import torch
from transformers import Gemma4UnifiedTextConfig, Gemma4UnifiedForCausalLM
from mlx_lm.models.gemma4_text import Model, ModelArgs

from gemma_mlx import ROOT


class ArchitectureTests(unittest.TestCase):
    def test_sliding_global_and_incremental_logits(self):
        torch.manual_seed(7)
        cfg = json.loads((ROOT / "models/speakrail-gemma/model/config.json").read_text())["text_config"]
        # Retain the checkpoint's attention/norm/RoPE choices, shrink dimensions.
        cfg.update(hidden_size=64, intermediate_size=128, num_attention_heads=4,
                   num_key_value_heads=2, num_global_key_value_heads=1,
                   head_dim=16, global_head_dim=32, num_hidden_layers=2,
                   layer_types=["sliding_attention", "full_attention"], vocab_size=128,
                   sliding_window=8, num_kv_shared_layers=0)
        hf_cfg = Gemma4UnifiedTextConfig(**cfg)
        hf_cfg._attn_implementation = "eager"
        hf = Gemma4UnifiedForCausalLM(hf_cfg).eval().float()
        mlx = Model(ModelArgs.from_dict(cfg))
        weights = {k: mx.array(v.detach().numpy()) for k, v in hf.state_dict().items()
                   if k != "lm_head.weight"}
        mlx.load_weights(list(weights.items()), strict=True)
        ids = list(range(2, 21))  # Cross the sliding-window boundary.
        cache = mlx.make_cache()
        with torch.no_grad():
            expected = hf(torch.tensor([ids]), use_cache=False).logits.numpy()
        actual = np.array(mlx(mx.array([ids])))
        full_error = float(np.max(np.abs(actual - expected)))
        np.testing.assert_allclose(actual, expected, atol=2e-4, rtol=2e-4)
        incremental = []
        for tid in ids:
            incremental.append(np.array(mlx(mx.array([[tid]]), cache=cache)))
        incremental = np.concatenate(incremental, axis=1)
        incremental_error = float(np.max(np.abs(incremental - expected)))
        np.testing.assert_allclose(incremental, expected, atol=2e-4, rtol=2e-4)
        result = {"full_max_abs_error": full_error, "incremental_max_abs_error": incremental_error,
                  "scope": "Small random float32 model; not full checkpoint/vLLM logit parity"}
        (ROOT / "architecture-parity.json").write_text(json.dumps(result, indent=2) + "\n")
        print(result)


if __name__ == "__main__":
    unittest.main()
