# Code audit report

Files scanned: 21

- **[warning]** `agents\vision\executor.py:114` (silent-exception-swallow) — except NoDisplayError: caught and silently ignored (bare 'pass') — errors here vanish without a trace.
- **[warning]** `agents\vision\executor.py:54` (silent-exception-swallow) — except BrowserNoDisplayError: caught and silently ignored (bare 'pass') — errors here vanish without a trace.