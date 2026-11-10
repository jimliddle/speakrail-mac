"""Apply the reviewed ASR boundary without accepting other dependency edits."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def apply_patch(checkout, revision, patch, *, check_only=False):
    checkout, patch = Path(checkout).resolve(), Path(patch).resolve()

    def git(*args, env=None):
        return subprocess.check_output(['git', '-C', str(checkout), *args], env=env)

    if git('rev-parse', 'HEAD').decode().strip() != revision:
        raise RuntimeError('ASR dependency is not at the pinned revision')
    if git('diff', '--cached', '--name-only', 'HEAD'):
        raise RuntimeError('ASR dependency has staged changes; leave them intact and review manually')
    # A temporary index computes the exact expected result without touching the checkout.
    with tempfile.TemporaryDirectory(prefix='speakrail-patch-') as tmp:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
        git('read-tree', revision, env=env)
        git('apply', '--cached', '--whitespace=error', str(patch), env=env)
        paths = git('diff', '--cached', '--name-only', '-z', revision, env=env).decode().split('\0')[:-1]
        changed = git('diff', '--name-only', '-z', 'HEAD').decode().split('\0')[:-1]
        if set(changed) - set(paths):
            raise RuntimeError('ASR dependency has unrelated tracked changes')
        pristine, patched = True, True
        for name in paths:
            path = checkout / name
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != checkout.parent):
                raise RuntimeError('Refusing a symlink in ASR patch paths')
            current = path.read_bytes() if path.exists() else None
            expected = git('show', ':' + name, env=env)
            exists = subprocess.run(['git', '-C', str(checkout), 'cat-file', '-e', revision + ':' + name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            original = git('show', revision + ':' + name) if exists else None
            pristine &= current == original
            patched &= current == expected
        if not pristine and not patched:
            raise RuntimeError('ASR patch paths contain unrecognized changes; refusing to overwrite them')
    if pristine and not check_only:
        git('apply', '--check', str(patch))
        git('apply', str(patch))
    return 'already patched' if patched else ('patch applicable' if check_only else 'patched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--checkout', type=Path, default=ROOT / 'audio.cpp')
    args = parser.parse_args()
    sources = json.loads((ROOT / 'sources.json').read_text())
    print(apply_patch(args.checkout, sources['dependencies']['audio.cpp']['revision'],
                      ROOT / 'patches/audio-local-access.patch', check_only=args.check))
