# CLI conventions

Core owns the `ardt` group and four things inside it: the mount point plugins hang their commands off, two flags every command honors, the `--json` envelope, and error UX. Everything else is a plugin.

| Option | Does |
|---|---|
| `-C`, `--directory DIR` | run as if ardt had started in `DIR` |
| `-v`, `--verbose` | show the commands being run; repeatable |
| `--dry-run` | print the plan, run nothing |
| `--json` | emit a machine-readable result envelope on stdout |
| `-V`, `--version` | the `ardt-core` version |
| `-h`, `--help` | help, on the group or any command |

**`--dry-run` and `--json` are injected, not implemented per command.** Core adds them to every command a plugin mounts, recursively into subgroups, so a third-party task gets them without its author doing anything. They also read the same before or after the subcommand: `ardt --json build` and `ardt build --json` are identical, and a flag set on the group is never unset by the subcommand.

## The envelope

With `--json`, stdout is exactly one JSON object and every diagnostic goes to stderr, so piping into `jq` is always safe.

```json
{
  "ok": true,
  "command": "ardt info",
  "ardt_version": "0.3.0",
  "project_version": "1.2.0",
  "data": {},
  "error": null
}
```

`data` is whatever the command contributed: digests, report paths, the context dump. On failure `ok` is `false`, `error` carries the one-line `message` and an optional `hint`, and the envelope is still printed.

## Failure

An expected failure is a one-line diagnosis on stderr plus a hint, and exit **1**. Never a traceback: a stack trace reaching a user means an ardt bug, not a usage error. Usage errors (a bad flag, a missing argument) exit **2**, click's convention, and an interrupt exits **130**.

## Inspecting an install

`ardt info` dumps the resolved context: project, root, version, where the config came from, git branch and sha with a dirty marker, the detected CI platform, and the plugin count. It is the first thing to run when a command behaves differently than expected, because almost every such surprise is a context that resolved differently than you assumed.

```console
$ ardt info
project      my_robot
root         /ws/src/my_robot
version      1.2.0
config       ardt.yaml
git          main @ 3f9a1c2 (dirty)
ci           none
plugins      6 loaded
```

`ardt plugins` lists what is loaded and what each one contributes, at which plugin API version:

```console
$ ardt plugins
ardt-ros-tasks 0.3.0 (api 1)  commands: build, test, deps
ardt-ros-dev 0.3.0 (api 1)  dev_profiles: ros2
```

A plugin that failed to load is reported as a warning with the reason rather than being dropped silently, which is how a version-skewed or half-installed module makes itself visible. Both commands honor `--json`, so CI can assert on them.
