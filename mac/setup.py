"""Reproduce the isolated Mac environments; model downloads require explicit consent."""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="print commands without changing files")
    parser.add_argument("--download-models", action="store_true")
    parser.add_argument("--accept-breeze-noncommercial-license", action="store_true")
    args = parser.parse_args()
    if args.download_models and not args.accept_breeze_noncommercial_license:
        parser.error("Read mac/licenses/BREEZE-MODEL-LICENSE.txt, then explicitly pass "
                     "--accept-breeze-noncommercial-license for the research/non-commercial model download.")
    if not args.plan:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            parser.error("This port requires native Apple Silicon macOS (not Rosetta).")
        missing = [name for name in ("git", "cmake", "ffmpeg", "uv", "xcrun") if not shutil.which(name)]
        if missing:
            parser.error("Install these prerequisites first: " + ", ".join(missing))
    env = {**os.environ, "UV_CACHE_DIR": str(ROOT / "uv-cache"),
           "UV_PYTHON_INSTALL_DIR": str(ROOT / "python"), "HF_HOME": str(ROOT / "hf-home")}

    def run(*command):
        command = [str(x) for x in command]
        print(shlex.join(command), flush=True)
        if not args.plan:
            subprocess.run(command, cwd=ROOT, env=env, check=True)

    sources = json.loads((ROOT / "sources.json").read_text())
    for name, source in sources["dependencies"].items():
        dest = ROOT / name
        if dest.exists():
            revision = subprocess.check_output(["git", "-C", str(dest), "rev-parse", "HEAD"], text=True).strip()
            if revision != source["revision"]:
                parser.error(f"{name} is not at the pinned revision; refusing to change an existing checkout")
            if subprocess.run(["git", "-C", str(dest), "diff", "--quiet", "HEAD"]).returncode:
                parser.error(f"{name} has local changes; refusing to build it as the pinned source")
        else:
            run("git", "init", dest)
            run("git", "-C", dest, "remote", "add", "origin", source["url"])
            run("git", "-C", dest, "fetch", "--depth", "1", "origin", source["revision"])
            run("git", "-C", dest, "checkout", "--detach", "FETCH_HEAD")
    for venv, lock in ((".venv", "requirements-app.lock.txt"),
                       (".mlx-venv", "requirements-mlx.lock.txt"),
                       (".tts-venv", "requirements-tts.lock.txt")):
        path = ROOT / venv
        if not path.exists():
            run("uv", "venv", "--python", "3.12", path)
        elif not (path / "bin/python").is_file():
            parser.error(f"{path} exists but is not a virtual environment; refusing to overwrite it")
        run("uv", "pip", "install", "--python", path / "bin/python", "-r", ROOT / lock)
    run("cmake", "-S", ROOT / "audio.cpp", "-B", ROOT / "audio.cpp/build/mac-eval",
        "-DCMAKE_BUILD_TYPE=Release", "-DAUDIOCPP_MODEL_SET=custom",
        "-DAUDIOCPP_MODELS=voxtral_realtime", "-DGGML_METAL=ON",
        "-DGGML_METAL_EMBED_LIBRARY=ON", "-DGGML_CUDA=OFF", "-DBUILD_SHARED_LIBS=OFF",
        "-DENGINE_BUILD_TESTS=OFF", "-DENGINE_BUILD_EXAMPLES=OFF")
    run("cmake", "--build", ROOT / "audio.cpp/build/mac-eval", "--target", "audiocpp_server", "-j", "4")
    if args.download_models:
        for script in ("fetch_tokenizer.py", "fetch_gemma.py", "fetch_speech.py"):
            run(ROOT / ".mlx-venv/bin/python", ROOT / script)
    else:
        print("Model downloads skipped. Use --download-models with explicit Breeze licence acceptance when ready.")
    print("Plan only; nothing installed." if args.plan else "Setup complete. Launch with ./mac/start-voice-prototype from the repository root.")


if __name__ == "__main__":
    main()
