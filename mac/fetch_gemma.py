"""Fetch only the pinned conversation model; no speech models or shared caches."""
import importlib.util
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
os.environ["MODELS_DIR"] = str(ROOT / "models")
os.environ["HF_HOME"] = str(ROOT / "hf-home")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
spec = importlib.util.spec_from_file_location(
    "upstream_init", ROOT.parent / "services/model-init/init.py"
)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def main():
    for repo, name, dest, size, digest in upstream.FILES:
        if repo not in (upstream.GEMMA, upstream.SPEAKRAIL):
            continue
        path = upstream.fetch(repo, name, dest, size, digest)
        if digest and upstream.sha256(path) != digest:
            raise RuntimeError(f"Checksum mismatch: {dest}")
    for name in upstream.TOKENIZER_FILES:
        shutil.copyfile(ROOT / "models/speakrail-gemma/tokenizer" / name,
                        ROOT / "models/speakrail-gemma/model" / name)
    upstream.gemma()
    final = ROOT / "models" / upstream.GEMMA_WEIGHTS[2]
    if upstream.sha256(final) != upstream.PATCHED_SHA256:
        raise RuntimeError("Patched model checksum mismatch")
    # This cache contains only files fetched by this script.
    shutil.rmtree(upstream.CACHE, ignore_errors=True)
    print("Pinned Gemma + Speakrail adapter and token rows verified.", flush=True)


if __name__ == "__main__":
    main()
