# Research digest: Windows UI Automation (UIA) ecosystem from Python

Inputs: `jev_ultrafast/desktop/ax.py` (AXBackend Protocol), `jev_ultrafast/desktop/tree.py`
(budgeted walker, guard/fingerprint scheme), `jev_ultrafast/desktop/README.md` (v1 scope:
click/fill only, no select/scroll/keyboard), `pyproject.toml` (pyobjc gated
`sys_platform == 'darwin'`), `tests/test_desktop.py` (FakeBackend contract). Researched
2026-10-16 against PyPI JSON API, GitHub sources, and Microsoft Learn.

## Findings

### 1. Python UIA library landscape

| | `uiautomation` | `pywinauto` | raw `comtypes` | WinAppDriver |
| --- | --- | --- | --- | --- |
| Latest release | 2.0.29, 2025-08-05 | 0.6.9, 2025-01-06; **1.0.0b1 pre-release 2026-10-15** (PyPI JSON, verified) | 1.4.9, 2025-01-06 | 1.2.1, June 2021 |
| Maintained-ness | Active, sole maintainer (yinkaisheng); 2.0.21–2.0.27 releases yanked for bugs — rapid fix cycles | Sporadic (0.6.8 2019 → 0.6.9 2025); 1.0.0b1 published one day before this research, unreviewed | Active, "Production/Stable" | Dormant since 2021; 1000+ open issues unanswered; closed source (microsoft/WinAppDriver issues #1103, #2018) |
| License | Apache-2.0 | BSD-3 | MIT | Proprietary |
| Paid/bundled services | None | None | None | None |
| Raw tree walk + budgets | Yes: `Control.GetChildren()`, `GetFirstChildControl`, `GetNextSiblingControl`, `GetParentControl`, generator `WalkControl(control, maxDepth)` — host-side budgeting applies directly (uiautomation.py:6990-7050, 10474) | Possible via ElementInfo API but the wrapper/best-match layer is the intended path; walking raw patterns per element fights the wrapper model (docs: pywinauto.application, code.pywinauto.backend) | Total control; you write the TreeWalker loop yourself | N/A (selenium-style find_element, no raw walk) |
| Pattern reads per element | `Control.GetPattern(patternId)` incl. Invoke/Toggle/Value/SelectionItem/Selection/ExpandCollapse/Scroll/RangeValue/LegacyIAccessible; `Control.Element` exposes raw `IUIAutomationElement` (uiautomation.py:6862, 6971, 8417-8720) | Via wrapper properties (`.texts()`, `.select()`, ...); raw access awkward | Direct `GetCurrentPatternAs` | Via WebDriver endpoints |
| Sync call model | Fully synchronous | Fully synchronous | Synchronous | Async HTTP WebDriver session, separate driver process — fails the in-process sync-pull requirement |
| Installability off-Windows | Universal `py3-none-any` wheel installs anywhere; **import fails off-Windows** (unconditional `import comtypes`, `import ctypes.wintypes`, module-level `ctypes.windll.*` calls — verified in source) | Deps `comtypes`/`pywin32` gated `sys_platform == "win32"`, so installable anywhere; **import fails off-Windows** (pywin32 absent) | Installs (pure py) but Windows-only at use; `requires-python >=3.9` | Separate installer, Windows-only |
| Marker-gating fit | `"uiautomation>=2.0.29,<3; sys_platform == 'win32'"` mirrors the pyobjc entries exactly | Same mechanism possible | Transitively required by both libs | n/a |

- Both Python libs depend on `comtypes` as the COM gateway (uiautomation `requires_dist: comtypes>=1.2.1`; pywinauto same for py>3.6).
- uiautomation sets Per-Monitor DPI awareness at import time: `SetProcessDpiAwareness(ProcessDpiAwareness.PerMonitorDpiAware)` runs at module level (uiautomation.py:2944-2958).
- **WinAppDriver is disqualified**: dormant (no release since 1.2.1, June 2021), closed source, and architecturally a separate HTTP/Appium driver process, which breaks the host's "one in-process synchronous backend seam" model and adds an external moving part to deploy.
- **Recommendation: `uiautomation` as the primary library** — thinnest maintained wrapper over the exact COM API the host needs, exposes raw elements/patterns, sync, Apache-2.0, comtypes escape hatch for anything it hides.

### 2. VB6 / classic Win32 exposure

- VB6 runtime controls (`ThunderRT6*` window classes) have **no native UIA provider**. UIA exposes them through the MSAA-to-UIA bridge using Oleacc.dll default proxies: "Oleacc.dll ... provides proxy objects used by the MSAA to UI Automation Proxy to support Win32 controls" (UIA Overview); proxies map each `IAccessible` method to Win32 messages (IAccessible Proxies doc). Community evidence of rough edges: UiPath forum "Unable to target some ThunderRT6 elements" (OLEDB grid not exposed), FlaUI issue #385 (VB6 modal windows invisible to UIA inspectors).
- Control pattern requirements per UIA ControlType (Microsoft, "Control Types and Their Supported Control Patterns"):
  - Button: Invoke conditional → click works.
  - CheckBox: **Toggle must-support**; RadioButton: **SelectionItem must-support**, Toggle not supported.
  - Edit: **Value conditional** (plus RangeValue, Text) → text fill is the designed mechanism.
  - ListItem: **SelectionItem must-support**; List: Selection + Scroll conditional.
  - ComboBox: ExpandCollapse must, Selection/Value conditional. Document: Text must, Scroll/Value conditional. Tree/Pane: Scroll conditional. MenuItem: Invoke/ExpandCollapse/SelectionItem/Toggle conditional.
- Confirm/deny:
  - **Text fill via ValuePattern + read-back: CONFIRMED as the designed path** for Edit controls; read-only-ness is exposed as `ValuePattern.IsReadOnly` (bridge maps `STATE_SYSTEM_READONLY` → Value/RangeValue `IsReadOnly`), which is exactly the host's `is_settable(·, VALUE)` probe. RangeValue `put_accValue` also bridges (Appendix G).
  - **List/combo selection via SelectionItemPattern: CONFIRMED by spec** (ListItem must-support; `SELFLAG_TAKESELECTION` → `SelectionItemPattern.Select`), with the caveat that on VB6-proxied content the pattern exists only if the bridge derives it — `STATE_SYSTEM_SELECTABLE` → "SelectionItemPattern is supported" (Appendix G), so presence is detectable per element.
  - **Scrolling via ScrollPattern: CONFIRMED by spec for native content** (List/Document/Tree/Pane conditional), but Scroll is *not* in the bridge's default-action fallback set (Invoke/ExpandCollapse/Toggle only) — MSAA-proxied VB6 content is unlikely to offer ScrollPattern. Treat scroll as pattern-conditional, not universal.
  - **Keyboard synthesis via SendInput: CONFIRMED, with pitfalls** — events go to the *foreground thread's message queue* (KEYBDINPUT doc: KEYEVENTF_UNICODE posts WM_KEYDOWN/WM_KEYUP to the foreground thread), so the target must hold focus; verify the foreground window right before sending. KEYEVENTF_UNICODE bypasses scan codes (apps reading scan codes misbehave); injected input is flagged `LLKHF_INJECTED` and filterable by hooks (community docs); UIPI blocks injection into elevated targets (see 5).

### 3. MSAA-to-UIA bridge caveats (what a pure UIA walker sees of legacy content)

Available (Appendix G, Active Accessibility Bridge):
- `accName` → Name; `accRole` → ControlType (full role table: ROLE_SYSTEM_PUSHBUTTON→Button, ROLE_SYSTEM_TEXT→Edit, ROLE_SYSTEM_CHECKBUTTON→CheckBox, ROLE_SYSTEM_LISTITEM→ListItem, ROLE_SYSTEM_MENUPOPUP→Menu, ROLE_SYSTEM_OUTLINE→Tree, ...).
- `accState` → UIA properties: UNAVAILABLE→IsEnabled, FOCUSED→HasKeyboardFocus, CHECKED→ToggleState.On (checkbox) / SelectionItem.IsSelected (radio), SELECTED→SelectionItem.IsSelected, READONLY→Value IsReadOnly, EXPANDED/COLLAPSED→ExpandCollapseState, PROTECTED→IsPassword.
- `accDoDefaultAction`/`accDefaultAction` → default actions per control type ("Press" for buttons, "Check/Uncheck" toggle, "Jump"→Invoke for hyperlinks); when no default action exists the bridge falls back to Invoke/ExpandCollapse/Toggle patterns.
- `accValue` → Value (string) or RangeValue (0–100) pattern value; `accLocation` → BoundingRectangle; `accSelection` → SelectionPattern.GetSelection; `accFocus` → IUIAutomation.FocusedElement; `accSelect` SELFLAGs → SetFocus / SelectionItem Select/AddToSelection/RemoveFromSelection.

Missing vs native UIA:
- **No AutomationId equivalent** (no accX maps to it in Appendix G) — the host's guard/fingerprint scheme must not depend on AutomationId for legacy content; anchor identity on `GetRuntimeId()` + (ControlType, Name) parent path + BoundingRectangle, which is structurally identical to tree.py's (role, title) path + (position, size).
- `accDescription` → **Not implemented**; `accHelpTopic` → Not implemented (Appendix G) — DESCRIPTION may be empty on legacy content; HELP maps from `accHelp`.
- No text object model (no Text pattern) for pure-MSAA content ("MSAA has no text object model", MSAA-vs-UIA Compared) — large legacy text views expose Value only.
- Escape hatch: `IUIAutomationLegacyIAccessiblePattern` exposes raw MSAA Role/State/DefaultAction/ChildId to UIA clients (Accessing MSAA Servers doc; uiautomation.py:6971 `GetLegacyIAccessiblePattern`) — use it for extra fingerprint signal when present.

### 4. App addressing on Windows

- There is **no bundle_id equivalent**. Candidate identifiers: exe name (`notepad.exe`), PID, window title, window class (`"Notepad"`, `"ThunderRT6FormDC"` for VB6 forms).
- pywinauto's `Application.connect()` accepts exactly one of `process` (PID), `handle` (HWND), `path`, or find_elements criteria (title/class) — confirming these are the ecosystem's addressing modes (pywinauto.application docs).
- Stability for the host's per-observe re-resolution (must survive app restarts):
  - **exe name: stablest across restarts** (survives PID churn) — recommended as the primary key, like bundle_id.
  - window title: changes at runtime — usable only as a hint.
  - window class: app-stable but shared by all instances of the app.
  - PID: dies with the process — useless for restart survival, fine as a per-observation resolution product.
- Process enumeration: `psutil` (7.2.2, active, cross-platform, `requires-python >=3.6`) enumerates processes by name portably and installs everywhere (import-safe); pure-ctypes Toolhelp32Snapshot is the zero-dependency alternative. From PID → app element: UIA has no per-process element; resolve top-level windows whose `ProcessId` matches (uiautomation: `GetRootControl().GetChildren()` filtered by `ProcessId`, or `Compare=lambda c: c.ProcessId == pid`; native path: `IUIAutomation` root + `CreatePropertyCondition(UIA_ProcessIdPropertyId, pid)` + FindFirst). The synthesized "app element" for the host seam is then the main window element (or the process's set of windows) — `inferred`: UIA intentionally has no app root, so `backend.application(exe)` must return a chosen window/document root and `AXWindows` maps to filtered top-level windows of the resolved PID set.

### 5. Gotchas for a headless-agent driver

- **UAC / UIPI**: a lower-integrity process cannot send synthetic input or messages — and per Microsoft's Power Automate troubleshooting page, UIA queries and actions — to a higher-integrity (elevated) process. Mitigations: run the agent elevated, or a signed `uiAccess="true"` manifest in a secure location (heavyweight; out of scope). Also: "UI Automation does not enable communication between processes that are started by different users through the Run as command" (UIA Overview). Practical rule: the agent's integrity level must be >= target app's; surface a detectable failure rather than silent refusal.
- **DPI**: `BoundingRectangle` is physical-screen coordinates only when the client process is DPI-aware; a DPI-unaware process gets virtualized/scaled values (UIA and Screen Scaling docs). uiautomation already requests Per-Monitor awareness at import (uiautomation.py:2958) — but that changes the *whole process*, so this belongs in the plan's explicit initialization notes. RDP/per-monitor mixed setups have reported wrong rectangles (SO 66673639).
- **Focus stealing**: SendInput lands in the foreground thread's queue; a background agent must SetFocus (UIA `SetFocus` / accSelect SELFLAG_TAKFOCUS) before typing and verify the foreground window after. uiautomation's readme notes some edits need `Click()` before `SendKeys`, and SendKeys triggers a lazy control search with the global timeout (LookupError on miss).
- **UIA timeouts (client knobs, all on IUIAutomation2)**: ConnectionTimeout default **2 s**, TransactionTimeout default **20 s**, CommandTimeout default **3 min**; exceeded calls return `UIA_E_TIMEOUT` (get_ConnectionTimeout/TransactionTimeout docs). uiautomation adds its own search layer: `TIME_OUT_SECOND = 10`, `Exists(maxSearchSeconds=5)`, `Refind(...)` (uiautomation.py:35, 7098, 7174). The host's walker should not use property searches inside walks (they carry these timeouts); walk raw from known roots and keep budgeting in tree.py.
- **CacheRequest**: `IUIAutomationCacheRequest` bulk-fetches properties/patterns per cross-process call — still fully synchronous (`FindFirstBuildCache`/`BuildUpdatedCache`), so it fits the pull model; use it if the walk proves round-trip-bound.
- **Events**: UIA event handlers (IUIAutomationEventHandler etc.) require registered COM callbacks/threads — the host layer is strictly pull-based, so do not register any; derive open-menu state from focused-element position in the tree as tree.py already does.
- **Antivirus**: SendInput-injecting processes are sometimes flagged by AV/EDR — `inferred`, community-reported only; no primary source found.
- **Windows 10/11 spread**: UIA COM API is stable since the Windows 7 rewrite; uiautomation claims XP SP3–11 support; IUIAutomation2..9 additions are progressive (timeout knobs need IUIAutomation2, i.e. Win8+). `unknown`: uiautomation on Windows Server SKUs beyond the readme's claims — untested.
- **Elevated runner trade-off**: running the agent as admin (uiautomation's own recommendation for enumeration reliability) raises the agent's own blast radius; make elevation a deployment note, not a code assumption.

### 6. Testing without Windows

- **Import safety**: none of uiautomation / pywinauto / comtypes can be *imported* off-Windows (uiautomation: unconditional `import comtypes` + `ctypes.wintypes` + module-level `ctypes.windll` calls — verified in source; pywinauto: pywin32 not installed off-win32; comtypes: Windows-only COM). Offline tests can only cover: (a) the guarded-import path reports lazily (exactly the ax.py:9-16 pattern), (b) everything above the seam. Marking the win32 dep `; sys_platform == 'win32'` keeps `uv build` and `uv sync` green on macOS.
- **Fake backend: CONFIRMED to fit.** `tests/test_desktop.py:35` defines `FakeBackend` implementing the full Protocol in-memory with a mutation log; `tree.py` is dict-in/dict-out with zero pyobjc imports ("No pyobjc imports", tree.py:1), so a UIA backend that only satisfies `AXBackend` inherits the same offline testability. The backend class must take its platform module injectably in `__init__` (`PyobjcBackend(ax=None, workspace=None)`, ax.py:87-97) — mirror that as `UiaBackend(uia=None)` so tests inject a fake and the real module import stays guarded.

## Conventions to follow (mirroring the pyobjc backend's shape)

1. New `jev_ultrafast/desktop/uia.py`: guarded module import (`try: import uiautomation ... except ImportError: _uia = None`), `UiaBackend(uia=None)` injectable constructor raising `RuntimeError` with an install hint naming the win32 marker — copy of ax.py:87-97's shape.
2. `pyproject.toml`: add `"uiautomation>=2.0.29,<3; sys_platform == 'win32'"` next to the pyobjc entries (comtypes arrives transitively; pin only if a comtypes regression appears).
3. Attribute vocabulary mapping (backend-internal, same constants): AXRole←ControlType string, AXTitle←Name, AXDescription←HelpText (empty on legacy), AXHelp←HelpText/accHelp, AXValue←ValuePattern.Value (RangeValue for sliders), AXPosition/AXSize←BoundingRectangle split, AXEnabled←IsEnabled, AXChildren/AXParent←raw walker, AXWindows←top-level Window elements of the resolved PID set, AXMenuBar←MenuBar ControlType under the app root, AXFocusedUIElement←FocusedElement.
4. Role map additions in tree.py terms: Button→button, Edit/Document→textbox, CheckBox→checkbox, RadioButton→radio, ComboBox→combobox, ListItem→(select), MenuItem/MenuBarItem→menuitem, TabItem→tab; secure-field skip maps to IsPassword instead of AXSecureTextField.
5. Operation mapping: click←InvokePattern.Invoke (Toggle fallback for checkboxes, mirroring `PRESSABLE_FALLBACK`); fill←ValuePattern.SetValue + read-back, gated by `not ValuePattern.IsReadOnly` (the settable probe); select (new)←SelectionItemPattern.Select (+ ExpandCollapse for combos); scroll (new)←ScrollPattern scroll, offered only when the pattern exists; keyboard (new)←SetFocus then SendInput (uiautomation SendKeys), foreground verified first.
6. Element identity: `same(a, b)` via `IUIAutomation.CompareElements` (or GetRuntimeId equality as a cheap pre-check); `ElementGone` raised on COMError `UIA_E_ELEMENTNOTAVAILABLE`, mapped like ax.py:48-52.
7. App resolution: `application(exe_name)` re-resolves every observe — enumerate processes by exe basename (psutil or Toolhelp32Snapshot), then find that PID set's top-level windows via ProcessId property condition; never cache PIDs across observations.
8. Keep all mutation logging/one-try semantics from AGENTS.md: log execution before observing; never retry a browser-style mutation; never retry SendInput either.
9. Never emit selectors or code from the model — the backend stays a fixed seam, targets remain observed elements, exactly as AX does it.

## Risks / open questions

- `unknown`: real-world SelectionItemPattern/ValuePattern availability on production VB6 `ThunderRT6*` grids — community reports gaps (UiPath, FlaUI #385); needs a one-hour on-Windows spike before promising select/fill on legacy apps.
- `inferred`: UIA has no per-app root element, so `application()` must return a chosen main-window element; multi-window apps need a "which window is the app" policy (first-found? focused?).
- `unknown`: behavior with two instances of the same exe (two notepad.exe) — the exe-name key is ambiguous; title/class disambiguation policy is an open design decision.
- `inferred`: AV/EDR false-positive rate on SendInput — no primary source; only community reports.
- `unknown`: pywinauto 1.0.0b1 (published 2026-10-15, one day before this research) may change the wrapper/dependency story — not reviewed; do not pin against it.
- `unknown`: comtypes/uiautomation compatibility ceiling on Python 3.13+ (uiautomation readme's tested range ends at 3.12; comtypes 1.4.9 declares `>=3.9` with no stated ceiling).
- `unknown`: Chromium/Electron UIA trees on Windows are believed to be natively exposed (as on macOS), but this was not verified here.
- Elevated-target automation (UIPI) will fail silently-ish from a non-elevated agent; the backend should translate the failure into a distinct error, but the exact COMError signature needs the on-Windows spike.

## Recommended approaches

1. **Primary: `uiautomation` 2.0.29 behind a new `UiaBackend`** in `jev_ultrafast/desktop/uia.py`, marker-gated `; sys_platform == 'win32'`, guarded import + injectable constructor mirroring `PyobjcBackend`, raw `GetChildren`/`WalkControl` walking with budgets kept in `tree.py`, patterns read per element, `CompareElements`/RuntimeId identity, exe-name→PID→ProcessId-filtered windows re-resolution each observe.
2. **Fallback within the same dependency chain: raw `comtypes` against UIAutomationCore** if uiautomation's wrapper layer gets in the way of pattern access or identity — same install marker, same sync model, more boilerplate.
3. **Testing: reuse the existing fake-backend pattern** — a `FakeUiaBackend` in `tests/` satisfying the Protocol (copying `FakeBackend`'s mutation-log shape) plus one import-guard test asserting the lazy RuntimeError; document WinAppDriver as rejected (dormant, separate driver process) and pywinauto as non-primary (wrapper model, sporadic cadence).

## Sources

- PyPI JSON API (fetched 2026-10-16): pypi.org/pypi/{uiautomation,pywinauto,comtypes,psutil}/json
- uiautomation source, master: github.com/yinkaisheng/Python-UIAutomation-for-Windows (uiautomation/uiautomation.py: lines 35, 2944-2958, 6862, 6907, 6971, 6990-7050, 7098, 7174, 10474; readme.md)
- pywinauto docs: pywinauto.readthedocs.io/en/latest/code/pywinauto.application.html
- Microsoft Learn: uiauto-controlpatternmapping; microsoft-active-accessibility-and-ui-automation-compared; appendix-g--active-accessibility-bridge-to-ui-automation; iaccessible-proxies; uiauto-uiautomationoverview; uiauto-accessingmsaaservers; uiauto-cachingforclients; uiauto-screenscaling; dotnet ui-automation-and-screen-scaling; iuiautomation2 get_ConnectionTimeout/get_TransactionTimeout; winuser KEYBDINPUT/SendInput; power-automate uipi-issues troubleshooting
- Community: github.com/microsoft/WinAppDriver (issues #1103, #2018; releases); forum.uipath.com ThunderRT6 thread; github.com/FlaUI/FlaUI issue #385; stackoverflow 1970917 (SendInput layouts), 31135839 (UIA timeouts), 66673639 (BoundingRectangle)
- Host: jev_ultrafast/desktop/ax.py, jev_ultrafast/desktop/tree.py, jev_ultrafast/desktop/README.md, pyproject.toml, tests/test_desktop.py
