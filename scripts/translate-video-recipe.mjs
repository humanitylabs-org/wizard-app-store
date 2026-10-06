// Execute the real Runtipi 4.8.0 builder, not a hand-written translation.
// Fetch immutable public source into scratch; never vendor it into the image.
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import { parse } from 'yaml';

const revision = '102f1ac87cf4aeb4871595c127df765fba37c67a';
const sources = [
  ['packages/backend/src/common/helpers/app-helpers.ts', '4c05b493e31c432886524a5713c71f170729c6232fdfa42f73dede3f0d26842d'],
  ['packages/backend/src/modules/docker/builders/compose.builder.ts', '5039261e53354e87d47df9d0670060a8bc2d15f532a4bad1e9ff514fb94400b7'],
  ['packages/backend/src/modules/docker/builders/traefik-labels.builder.ts', 'ca9a34ed48e4642f5b7666940d4ce4e0ca27ca5ff4faeeb8e57ee8f1068c43c6'],
  ['packages/backend/src/modules/apps/app-files-manager.ts', '2a6140f996c2fd074e85b94baa42b88ac2f6f16cb8666c0ecf3c97a4d6d7b593'],
  ['packages/backend/src/modules/app-lifecycle/commands/install-app-command.ts', '70b460743a04480ee5ad3c8121ea854b0ed0be054e2b1843377528dca29eb35b'],
];
const scratch = await mkdtemp(join(tmpdir(), 'video-runtipi-translator-'));
try {
  await symlink(resolve('node_modules'), join(scratch, 'node_modules'));
  for (const [path, hash] of sources) {
    const response = await fetch(`https://raw.githubusercontent.com/runtipi/runtipi/${revision}/${path}`, {signal: AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error(`Runtipi source fetch failed: ${response.status}`);
    const source = await response.text();
    if (createHash('sha256').update(source).digest('hex') !== hash) throw new Error(`Source hash mismatch: ${path}`);
    const name = path.split('/').at(-1);
    if (name === 'app-files-manager.ts') {
      if (!source.includes("execFileAsync('chmod', ['-Rf', 'a+rwx', appDataDir])")) throw new Error('Permission model changed');
    } else if (name === 'install-app-command.ts') {
      if (!source.includes('await appFilesManager.setAppDataDirPermissions(appUrn)')) throw new Error('Install permission step missing');
    } else {
      // Type erasure plus import resolution only; builder logic stays unchanged.
      const js = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText
        .replaceAll("'@/common/helpers/app-helpers'", "'./app-helpers.mjs'")
        .replaceAll("'./traefik-labels.builder'", "'./traefik-labels.builder.mjs'");
      await writeFile(join(scratch, name.replace(/\.ts$/, '.mjs')), js);
    }
  }
  const { DockerComposeBuilder } = await import(pathToFileURL(join(scratch, 'compose.builder.mjs')));
  const recipe = parse(await readFile('apps/defleur-video/docker-compose.yml', 'utf8'));
  const output = new DockerComposeBuilder().getDockerCompose(recipe,
    {openPort: true, exposed: false, exposedLocal: false, enableAuth: false},
    'defleur-video:release-smoke', '172.29.240.0/24', 'amd64');
  process.stdout.write(JSON.stringify({revision, source_sha256: Object.fromEntries(sources), compose: parse(output),
    permissions: {command: ['chmod', '-Rf', 'a+rwx'], timing: 'after compose up', uid_metadata_does_not_chown: true}}));
} finally {
  await rm(scratch, {recursive: true, force: true});
}
