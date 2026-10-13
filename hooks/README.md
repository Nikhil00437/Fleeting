# Hooks

Python files in `~/.config/fleeting/hooks/` that the app runs when things
happen. Nothing here is required — the app works exactly the same with no
`hooks/` directory.

## Writing one

A hook is a `.py` file with functions named after events. Only the names matter;
helpers, imports and constants are ignored by discovery.

```python
def on_note_created(payload):
    ...
```

### Events

| Function | Fires when |
| --- | --- |
| `on_note_created(payload)` | a capture becomes a note |
| `on_note_updated(payload)` | a note's content changes |
| `on_note_deleted(payload)` | a note is trashed |
| `on_task_created(payload)` | a task is added |
| `on_task_updated(payload)` | a task changes |
| `on_task_deleted(payload)` | a task is removed |
| `on_dailylog_updated(payload)` | the daily log is rewritten |
| `on_collections_changed(payload)` | a collection changes |

`activity.live` and `whisper.progress` are deliberately **not** hookable. They
fire on every poll and every audio chunk; a subprocess per event would be a fork
bomb wearing a feature's clothes.

## The rules

- **A subprocess, with a 10 second timeout.** A hook that hangs is killed. A
  hook that crashes, or calls `sys.exit`, or leaks memory, cannot affect the app.
- **The payload arrives as JSON on stdin.** Note text is data, never a shell
  string — a note containing `$(rm -rf ~)` is not a command.
- **The return value is ignored.** To change something, edit the database or call
  the API. A second write path into the same tables would have to be audited
  separately from every other writer.
- **Failures are logged, not raised.** A note never fails to save because a hook
  has a typo. Look for `fleeting.hooks` warnings in the log.
- **The event fires at most once per publish**, in filename order, so two hooks
  for one event run in a predictable sequence.

## These are your own code

A hook runs with your full permissions — the same trust level as a shell alias.
Anything that can write to `~/.config/fleeting/hooks/` can run code on every note
you capture. Theme and prompt packs (#495) deliberately cannot.
