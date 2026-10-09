"""Fetch only the pinned tokenizer/config for upstream simulated session tests."""
import hashlib
from pathlib import Path
import urllib.request

DEST = Path(__file__).resolve().parent / 'tokenizer'
REV = 'f1004b2763dafee266f108bb2f5167554b984c48'
BASE = f'https://huggingface.co/speakrail/gemma-4-12B-it-qat-Speakrail/resolve/{REV}/tokenizer/'
DEST.mkdir(exist_ok=True)
for name in ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'):
    with urllib.request.urlopen(BASE + name, timeout=60) as response:
        content = response.read(50 * 1024 * 1024 + 1)
    if len(content) > 50 * 1024 * 1024:
        raise RuntimeError('Unexpectedly large metadata file')
    digest = hashlib.sha256(content).hexdigest()
    if name == 'tokenizer.json' and digest != 'f7fa088e59a7c7d935ddff8911cf0a901ccdb927ca9cc677c5c1de4bcee22b48':
        raise RuntimeError('Tokenizer hash differs from Speakrail model-init manifest')
    (DEST / name).write_bytes(content)
    print(name, len(content), digest)
