# Newbro Executor menu-bar app (macOS)

Build a double-clickable `.app`:

```bash
python -m pip install -e '.[macos-ui-build]'
python packaging/menubar/setup.py py2app
open "dist/Newbro Executor.app"
```

The app is menu-bar only (`LSUIElement`), supervises executor node profiles
stored in `~/.newbro/menubar.json`, and spawns one `python -m
newbro.executors.node` subprocess per active profile.

Deeper executor runtime config (codex/acpx binary paths, Whisper/audio) is
machine-level and is configured separately with `newbro executor setup`.
