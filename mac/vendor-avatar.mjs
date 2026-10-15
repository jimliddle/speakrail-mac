import { copyFile, mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const source = path.join(root, 'node_modules/three');
const target = path.join(root, '../app/web/live/vendor/three');
const pkg = JSON.parse(await readFile(path.join(source, 'package.json'), 'utf8'));
if (pkg.version !== '0.180.0') throw new Error('Expected Three.js 0.180.0');
for (const [from, to] of [
  ['build/three.module.js', 'three.module.js'],
  ['build/three.core.js', 'three.core.js'],
  ['examples/jsm/loaders/GLTFLoader.js', 'loaders/GLTFLoader.js'],
  ['examples/jsm/utils/BufferGeometryUtils.js', 'utils/BufferGeometryUtils.js'],
  ['LICENSE', 'LICENSE'],
]) {
  const dest = path.join(target, to);
  await mkdir(path.dirname(dest), { recursive: true });
  await copyFile(path.join(source, from), dest);
}
console.log('Vendored Three.js 0.180.0 and GLTFLoader, including MIT licence.');
