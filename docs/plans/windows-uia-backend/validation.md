# Validation Log — windows-uia-backend

Scope challenge (AskUserQuestion, answered by user 2026-10-16):

| Question | Answer | Consequence |
|----------|--------|-------------|
| Scope mode | **EXPANSION** | select/scroll/keyboard synthesis in scope (Phase 2); Linux AT-SPI still deferred; reviewer upgraded to --hard depth (2 researchers + red team) |
| Verify environment | **Offline + live-check script** | Everything above the seam offline-testable on macOS; live parts ship as `scripts/check_uia.py` + spike kit the user runs on the Windows box later |
| Live-check target | **Win32 chuẩn trước** | Notepad is the acceptance target; VB6 verdicts are spike-gated, not promised |

Open decisions left to implementation (with defaults, per output-standards):
- `psutil` fallback if the ctypes Toolhelp32/QueryFullProcessImageName sweep proves brittle (default: ctypes, no new dep).
- Scroll action's AX-vocabulary name (default: document whatever is chosen in `uia.py`).
- Pattern→perform priority order (default: Invoke → Toggle → SelectionItem → ExpandCollapse, documented in-module).

No blocking questions remain; the on-Windows spike (Phase 4) is the designated point where `unknown`s resolve, and its verdict table gates the VB6 promises before the user relies on them.
