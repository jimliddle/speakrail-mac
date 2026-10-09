"""Pinned speech models only, using the experiment's private download directories."""
from pathlib import Path
import shutil
from fetch_gemma import ROOT, upstream
from huggingface_hub import snapshot_download


def main():
    for repo, name, dest, size, digest in upstream.FILES:
        if repo not in (upstream.VOXTRAL, upstream.TURN_HEAD):
            continue
        path = upstream.fetch(repo, name, dest, size, digest)
        if digest and upstream.sha256(path) != digest:
            raise RuntimeError(f"Checksum mismatch: {dest}")
    shutil.rmtree(upstream.CACHE, ignore_errors=True)
    snapshot_download("mlx-community/Breeze-TTS-2-mlx-8bit",
                      revision="c6e4a2ff6ab9afba68b7853de802273ffe23fb49",
                      local_dir=ROOT / "models/breeze-mlx-8bit",
                      allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "LICENSE*", "README.md"],
                      max_workers=2)
    print("Pinned Voxtral/turn-head verified; pinned Breeze MLX snapshot downloaded.", flush=True)


if __name__ == "__main__":
    main()
