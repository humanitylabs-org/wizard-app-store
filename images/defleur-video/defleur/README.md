# DeFleur video

A portable Hermes Agent Plugin v1 workflow for turning arbitrary source footage into a coherent, accessible short without imposing a house aesthetic. It provides editorial, audio-integrity, portrait-framing, semantic-motion, and caption mechanics; projects, sources, renders, presets, model weights, credentials, and creative decisions stay outside this package.

## Install and enable

```sh
hermes plugins install <reviewed-plugin-source> --no-enable
hermes plugins enable defleur-video
```

Hermes discovers the three namespaced skills after enablement. Disable or uninstall through the native plugin lifecycle. The package never writes SOUL or global memories.

## Project and preset locations

Create each production project wherever the owner chooses. Package code is immutable after installation. Owner presets are external, profile-scoped files:

```text
${HERMES_HOME}/data/wizard-modules/defleur-video/presets/
```

For a project, resolve settings in this order: explicit project preset or `project/defleur-preset.json`; active profile preset of the same name; package `defaults/neutral-preset.json`. Project values override owner values; owner values override module defaults. Never write a project decision back into an owner preset without explicit owner approval.

The default is deliberately restrained: readable sans typography, high contrast, no forced palette, no supplied visual assets, and no clip-specific editorial decisions.

## Execution placement

Use the owner-authorized execution machine, which may be the Hermes VPS itself or a dedicated worker. Honor its placement rules. Inventory RAM/CPU/disk before local media work, cap workers, and keep cloud Opus separate from local rendering. No spare desktop is required by this module. Installation performs no media work or paid model calls. See SETUP.md for project preparation.

See the three skill directories for the operating workflow and helper contracts.
