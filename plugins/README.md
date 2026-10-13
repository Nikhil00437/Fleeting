# Plugins

A plugin is a folder under `~/.config/fleeting/plugins/` containing a
`plugin.json`. The manifest **declares** what the plugin provides — capture
sources, enrichers, views — and names the hook that implements each one.

## The manifest is a catalogue, not an execution vector

Execution already exists and is opt-in, per file, in a directory you control:
[`hooks/`](../hooks/README.md) runs your Python, and `actions.toml` runs your
commands. A plugin manifest describes an extension; it does not run one.

That division is the whole design, and it is what makes a plugin shareable. **A
plugin folder someone sent you is data, not code.** The only thing its manifest
can name is a hook — and that hook still has to be installed, separately, by you.

The consequence is enforced rather than documented: the loader copies only keys
it knows from each entry, so a `"command"`, `"script"` or `"module"` field in a
manifest is dropped without being read. It is a whitelist, not a denylist, so a
field nobody thought of is also dropped by default.

## Format

```json
{
  "name": "Notion Sync",
  "version": "0.1.0",
  "api_version": 1,
  "description": "Sends captures to a Notion page",
  "author": "you",
  "provides": {
    "capture_sources": [
      { "name": "notion", "title": "Notion page", "hook": "notion_sync.py" }
    ],
    "enrichers": [
      { "name": "notion-tags", "description": "Adds Notion ids as tags", "hook": "notion_sync.py" }
    ],
    "views": []
  }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | display name |
| `version` | yes | your plugin's version, as a string |
| `api_version` | yes | the manifest shape you target; `1` today |
| `provides` | yes | what the plugin provides |
| `description` | no | one line, shown in the list |
| `author` | no | free text |
| `homepage` | no | free text |

### `provides`

Each key is a list, and each entry needs a `name`.

| Kind | May also carry |
| --- | --- |
| `capture_sources` | `title`, `description`, `hook` |
| `enrichers` | `description`, `hook` |
| `views` | `title`, `description`, `url` |

A kind this app does not know about is ignored, not an error — so a plugin built
for a newer version still loads and shows the parts this one understands.

## Validation

The app checks each manifest and reports what is wrong instead of dropping it
silently. `GET /api/plugins` returns `{plugins, errors}`; one bad plugin costs
you that plugin and nothing else.

- **`api_version` too new** is the check that saves the most time, and it names
  both numbers: `api_version 2 is newer than this app supports (1) — update
  Fleeting`. "Incompatible" is the least useful thing a loader can say to someone
  who just wrote their first plugin.
- **A `hook` is a bare filename.** `"../../../etc/passwd"` is rejected — nothing
  opens that path, but the string has to stay safe to use as an identifier
  wherever it is later joined to one.
- **A missing required field is named**, not counted.

## Making one

There is no build step, no registry and no network. Make a folder, write the
manifest, and — if it needs to do anything — copy a hook from
[`hooks/`](../hooks/README.md) into `~/.config/fleeting/hooks/` and name it.

## What is not here yet

`capture_sources` and `views` are declared and listed but not rendered: there is
no in-app surface for a third-party view, and capture sources currently arrive
through the API and `flee`. The manifest is the stable half, so wiring the other
half later is a small change rather than a format change.