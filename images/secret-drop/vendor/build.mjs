// Reproducible build of ../static/noble-crypto.js. Run: npm ci && node build.mjs
import { build } from 'esbuild';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';

const lock = JSON.parse(readFileSync(new URL('./package-lock.json', import.meta.url)));
const pins = ['@noble/ciphers', '@noble/curves', '@noble/hashes']
  .map((name) => `${name}@${lock.packages[`node_modules/${name}`].version} ${lock.packages[`node_modules/${name}`].integrity}`);
const result = await build({
  entryPoints: [new URL('./src/entry.mjs', import.meta.url).pathname],
  bundle: true, format: 'iife', globalName: 'SecretDropCrypto', platform: 'browser',
  target: ['es2020'], minify: false, legalComments: 'inline', charset: 'ascii', write: false,
  banner: { js: `/* Secret Drop vendored crypto. MIT-licensed @noble libraries by Paul Miller (paulmillr.com).\n * Exact pins (npm integrity):\n${pins.map((p) => ' *   ' + p).join('\n')}\n * Rebuild: cd images/secret-drop/vendor && npm ci && node build.mjs */` },
});
const code = result.outputFiles[0].contents;
writeFileSync(new URL('../static/noble-crypto.js', import.meta.url), code);
console.log(createHash('sha256').update(code).digest('hex'), code.length);
