# Research Digest — Desktop-App Automation Layer (macOS AX) for jev-ultrafast

Date: 2026-10-15. Evidence sources: repo files (`path:line`), live probes on this machine
(macOS 26.6.2 arm64, Google Chrome 154.0.8037.100, uv 0.12.19), Chromium `main` source fetched
2026-10-15, and the references listed inline. `unknown` / `inferred` markers mark evidence gaps.

## Findings

### Repository structure (the loop to replicate)

1. **The core loop is exactly "indexed element table → model picks operation+target id → trusted execution".**
   `Browser.observe()` returns `{url, title, w, h, text, scroll, actions, marker, page_key, guards, fingerprint, screenshot?}`
   (`jev_ultrafast/browser/browser.py:44-113`, `browser.py:188-194`); `actions` items carry
   `{id: "e1".., kind: click|fill|select|scroll|wait, node, role, label, value, rect, ...}`
   (`jev_ultrafast/browser/snapshot.js:61-104`). A desktop layer must emit the same shape to be
   consumable by the existing brains.

2. **Action kinds and controls.** Snapshot emits per-element `click`/`fill`/`select`
   (`snapshot.js:68-80`), plus pseudo-actions `scroll_up`/`scroll_down`/`wait`
   (`snapshot.js:102-104`), capped at 250 elements with `omitted_actions` counter
   (`snapshot.js:99-100`). Role vocabulary is ARIA-ish: `button, link, checkbox, radio, switch, tab,
   menuitem, menuitemradio, option, gridcell, combobox, textbox, searchbox, spinbutton`
   (`snapshot.js:24-25`).

3. **Freshness/guard mechanism (to be mirrored, not imported).** Three layers:
   (a) whole-page `marker` = `[timeOrigin, href, scrollX/Y, innerWidth/Height, title, text, semantics,
   form-state array]` (`snapshot.js:44-53, 97-98`); (b) per-action `guards[node]` = identity + role +
   name + value + checked + selected + readonly + disabled + aria state + href + 6k-char scope text
   (`snapshot.js:47-53`); (c) at execution time the target is re-resolved and geometry/hit-tested
   before input (`browser.py:144-168`). `Browser.act()` refuses stale pages with `StalePage`
   (`browser.py:100-102`); execution is logged before the post-action observation
   (`jev_ultrafast/agent/agent.py:117-148`); a decision is consumed before any mutation so a retry
   cannot double-click (`agent.py:90-92`). Never retry a browser mutation (AGENTS.md) maps to
   `browser.py:105-107` (`after_input`) and `agent.py:118`.

4. **Agent layer hard-depends on `Browser` in exactly one place**: `self.browser = Browser(url)`
   (`agent.py:20`); everything else goes through `observe/fresh/act` and `page["actions"]`.
   `model.action_space()` maps kind→operation `click→CLICK, fill→TYPE_TEXT, select→SELECT`, treats
   everything else (e.g. `wait`) as a control, and builds operation-specific target heads
   (`jev_ultrafast/agent/model.py:152-182`). So a desktop source satisfying
   `observe()/fresh()/act()/close()` with kinds from that vocabulary can drive the same loop with
   no model changes (this matches `docs/architecture.md:20-26` and `examples/external_agent.py`).

5. **MCP server pattern to copy** (`jev_ultrafast/mcp_server.py`):
   module-global single session (`_browser`, `mcp_server.py:36-69`); `MCPServer("jev-browser")`
   from `mcp.server.mcpserver` with `@server.tool()` async functions returning
   `json.dumps(result, indent=2)` (`mcp_server.py:88-269`); tools `jev_navigate/jev_observe/jev_act/
   jev_close/jev_config`; `jev_act(action_id, text?)` re-observes, finds the action by id, executes,
   then reports the new state (`mcp_server.py:154-194`); errors are returned as
   `{"error": "..."}` JSON, not exceptions (`mcp_server.py:169, 194, 207`). The server calls no
   model and needs no API keys.

6. **MCP registration pattern** (`scripts/install_mcp.py`): `SERVER_NAME="jev-browser"`,
   `ENTRY_POINT="jev-mcp"` (`install_mcp.py:27-28`); spawn command is always
   `[uv, --directory <project>, run, (--env-file <project>/.env), ENTRY_POINT]` with absolute paths
   (`install_mcp.py:42-49`); a declarative `Agent` dataclass registry holds per-agent config path,
   JSON key path, aliases, and entry-shape builders (Codex=TOML section, OpenCode={"type":"local",
   "command": argv}, ZCode adds `"cwd"`) (`install_mcp.py:184-277`); upsert is idempotent and never
   writes credentials (`install_mcp.py:103-150`, tests at `tests/test_make_scripts.py:60-105`).
   `make install [agent]` / `make install-dry` / `--status` wrap it (`Makefile:50-54`,
   `install_mcp.py:342-376`). A desktop server would add one registry entry (or a sibling script)
   with its own server name.

7. **Entry points / packaging** (`pyproject.toml`): deps `browser-harness==0.1.13`,
   `httpx[http2]>=0.28,<1`, `mcp>=1.0.0` (`pyproject.toml:8`); scripts `jev = jev_ultrafast.demo:main`,
   `jev-mcp = jev_ultrafast.mcp_server:main` (`pyproject.toml:10-12`); requires-python `>=3.12`;
   ruff line-length 120, select `["E","F","I"]` (`pyproject.toml:21-25`); pytest `testpaths=["tests"]`
   (`pyproject.toml:27-28`). Build via hatchling; `uv build` (Makefile:34-36).

8. **Tests are offline contracts** — "No paid APIs" is stated in the first line of both test files
   (`tests/test_agent.py:1`, `tests/test_make_scripts.py:1`); model calls are mocked at
   `model.post_json` / provider `_post` (`tests/test_agent.py:77-114, 143-156`); browser internals
   are tested by mocking `browser_harness.helpers.cdp` (`tests/test_agent.py:237-275`).
   The live local check is a script, not a test: `scripts/check_guards.py` builds a `data:...`
   HTML page, runs real observe/fresh/act in the local Chrome, asserts outcomes, prints
   `PASS: N browser guard checks; no model calls` (`scripts/check_guards.py:1-137`). This is the
   template for a desktop live check.

9. **Checks contract** (AGENTS.md + README Development + Makefile):
   `uv run ruff check .`, `uv run pytest`, `node --check jev_ultrafast/static/app.js`,
   `node --check jev_ultrafast/browser/snapshot.js`, `uv build`; `make build` runs all of them;
   `make doctor` runs `scripts/doctor.py` which reports toolchain/env/Chrome/MCP state
   (`scripts/doctor.py:60-208`) — a desktop layer should extend doctor with an
   Accessibility-permission check rather than inventing a new health command.

10. **No desktop/AX code exists yet.** `find` over the repo shows no `desktop*`, no `ax*`, no
    pyobjc/atomacos in `uv.lock` (only `browser-harness`); `docs/plans/` does not exist. Nothing
    to reuse; the seams are the `Browser` interface (4) and the MCP scaffold (5).

### macOS AX from Python

11. **pyobjc is the viable maintained route.** `uv pip install pyobjc-framework-ApplicationServices
    pyobjc-framework-Cocoa` resolved to **pyobjc 12.2.2 (current, Oct 2026)** on Python 3.12 in a
    throwaway venv on this machine; `import ApplicationServices` exposes
    `AXUIElementCreateApplication`, `AXUIElementCopyAttributeValue`,
    `AXUIElementSetAttributeValue`, `AXUIElementCreateSystemWide`,
    `AXUIElementCopyElementAtPosition`, `AXUIElementCopyActionNames`, `AXIsProcessTrusted`, and
    `AXUIElementPerformAction`; `AppKit` (NSWorkspace) and `Quartz` come in as dependencies
    (pyobjc-framework-quartz 12.2.2 was installed automatically). PyObjC changelog:
    https://pyobjc.readthedocs.io/en/latest/changelog.html — refs:
    https://pyobjc.readthedocs.io ,
    https://developer.apple.com/documentation/applicationservices/1459374-axuielementcreateapplication .
    **Gap found empirically**: `AXUIElementCopyFocusedUIElement` is NOT wrapped — use the
    system-wide element + `kAXFocusedUIElement` attribute instead (AttributeError observed in probe).

12. **atomacos/pyatom is stale — avoid.** atomacos 3.3.0 released 2021-05-24, GPLv2, classifiers
    stuck at py3.4-3.7 (py2.py3 wheel), single maintainer, and it is itself just a pyobjc wrapper
    (https://pypi.org/project/atomacos/ ; original pyatom unreleased since 2013:
    https://github.com/pyatom/pyatom ). Direct pyobjc is strictly better for a 2026 codebase.

13. **This dev machine already holds the Accessibility (TCC) grant** for the host process:
    `AXIsProcessTrusted() == True` returned by a probe run from the terminal
    (`AXIsProcessTrusted=True` in probe output). Note attribution: the grant belongs to the
    *responsible app* (terminal/agent host), so an MCP server spawned by an agent inherits that
    host's grant — `unknown` for each specific agent host; must be checked by `make doctor`-style
    code, not assumed.

14. **Reading Chrome works with zero activation, app level** (all verified live via pyobjc):
    `AXUIElementCreateApplication(pid)` where pid comes from
    `NSWorkspace.sharedWorkspace().runningApplications()` filtered by
    `bundleIdentifier() == "com.google.Chrome"`; app attributes readable: `AXRole='AXApplication'`,
    `AXTitle='Chrome'`; `AXMenuBar` enumerates the full menu bar — Chrome 154 showed 11 items
    (Apple, Chrome, File, Edit, View, History, Bookmarks, Profiles, Tab, Window, Help), each an
    `AXMenuBarItem` with actions `[AXCancel, AXPress, AXPick]` from `AXUIElementCopyActionNames`.

15. **Window level (verified live, while a real window existed)**: `AXWindows` → one element with
    `AXRole='AXWindow'`, `AXTitle='<page title> - <profile name>'`, `AXMinimized=True` (readable),
    children = `AXGroup` (title = window title) + 3 window-control `AXButton`s with action
    `[AXPress]`. `AXToolbar` returned `-25205 kAXErrorAttributeUnsupported` while the window was
    minimized. With **no** Chrome window open, `AXWindows` returns a list containing the
    application element itself and `AXMainWindow`/`AXFocusedWindow` return
    `-25212 kAXErrorNoValue` (observed). Error codes seen live: `0` success, `-25205`
    kAXErrorAttributeUnsupported, `-25208` kAXErrorActionUnsupported, `-25212` kAXErrorNoValue.

### Chrome accessibility activation (the crux)

16. **Current Chromium source** (fetched 2026-10-15, `main`):
    `chrome/browser/chrome_browser_application_mac.mm` —
    https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/chrome_browser_application_mac.mm :
    - `-[BrowserCrApplication accessibilitySetValue:forAttribute:]` handles
      `@"AXEnhancedUserInterface"`: sets → `enableScreenReaderCompleteModeAfterDelay:YES`, which is
      **debounced 2 seconds** (`kTwoSecondDelay = 2.0`) and then enables screen-reader-complete
      accessibility mode; comments state VoiceOver is now monitored directly via KVO
      (`voiceOverStateChanged:`) and "other AT can set a value for AXEnhancedUserInterface, so we
      can't ignore it".
    - `-[BrowserCrApplication accessibilityRole]` **immediately** enables AX mode when any AT reads
      the app's role: `ui::AXMode::kNativeAPIs` if `kSonomaAccessibilityActivationRefinements` is on
      (macOS 14+), else `ui::kAXModeBasic` — "such as Voice Control... turning on a11y when an AT
      accesses the 'accessibilityRole' property".
    - `AXManualAccessibility` appears **nowhere** in Chrome proper; it is the **Electron** mechanism
      (https://electronjs.org/docs/latest/tutorial/accessibility documents setting
      `AXManualAccessibility` via `AXUIElementSetAttributeValue` on the app element).

17. **Official design doc** (https://www.chromium.org/developers/design-documents/accessibility):
    "Chromium turns on or off accessibility support based on whether it sees a client, such as
    VoiceOver, has set the AXEnhancedUserInterface attribute on the main application window",
    plus two overrides: launch flag `--force-renderer-accessibility`, and visiting
    `chrome://accessibility` to toggle support per-tab. (Doc wording says "main application
    window" while the current code handles it on the NSApplication subclass — `inferred`: either
    works via AppKit attribute forwarding; doc may be stale.)

18. **Live activation attempts FAILED on this stack** (macOS 26.6.2 + Chrome 154.0.8037.100):
    `AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface", True)` → `-25208` repeatedly
    (3 retries); `set "AXManualAccessibility"` → `-25205`; same on the window element. Reading
    `AXRole` on the app succeeded (`0`) and, per finding 16, should have enabled native-API mode —
    consistent with menus/windows being readable, but **web content never appeared**
    (`AXWebArea: 0` in every enumeration; window children limited to chrome UI). An unverified
    third-party claim says "Chrome 152 breaks Mac accessibility API"
    (https://www.linkedin.com/posts/manduks_kato-your-follow-ups-drafted-before-you-activity-7505626629382025216-2s38
    — unverified, login-gated); a related tracker issue
    https://issuetracker.google.com/issues/40865608 documents AXEnhancedUserInterface toggling
    regressions. **unknown**: the exact working activation recipe for Chrome 154 on macOS 26;
    candidates that remain untested: `--force-renderer-accessibility` on launch,
    `chrome://accessibility` page toggle, window-restored timing (the test window was minimized and
    was later closed mid-probing), and CDP `Accessibility.enable` (project already has CDP via
    browser-harness, but that couples the desktop layer back to CDP for this one app).

19. **What a Chrome AX snapshot can enumerate — verified vs not**:
    - Verified live: app role/title; full menu bar with pressable items; window list/titles/
      minimized state; window-control buttons with `AXPress`.
    - Documented by Chromium's macOS AX implementation but **not observed here** (`unknown` on this
      build): toolbar buttons and tab strip (`AXToolbar`, tab buttons — the file
      `ui/accessibility/platform/browser_accessibility_cocoa.mm` exists in
      https://chromium.googlesource.com/chromium/src/+/main/ui/accessibility/platform/ listing),
      omnibox as a text field, and `AXWebArea` for page content once full mode is active.
    - Structural limits (by design of the layer split): DOM contents belong to the existing CDP
      element table; the AX layer covers chrome UI + menus + whatever AX exposes for the web area.
      Secure (password) field values: Chrome masks them over AX — `inferred` from the repo's own
      rule of never exposing secret values (`snapshot.js:9` skips `password` inputs;
      `scripts/check_guards.py:107` asserts secrets never appear); `unknown` for AX specifics.

20. **Action execution surface**:
    - `AXUIElementPerformAction(element, "AXPress")` is the trusted, event-free path — verified
      indirectly: `AXUIElementCopyActionNames` returned `AXPress` on buttons and
      `AXPress/AXPick/AXCancel` on menu items live; Apple API reference for perform-action:
      https://developer.apple.com/documentation/applicationservices (AXUIElementPerformAction /
      kAXPressAction). `inferred` (standard API, not exercised in probes).
    - Keyboard text entry needs synthesized events: `Quartz` CGEventCreateKeyboardEvent +
      CGEventPost (pyobjc-framework-Quartz installed as a pyobjc dependency) — `inferred`
      (not probed); alternative is `AXUIElementSetAttributeValue(kAXValueAttribute)` on editable
      fields — `inferred` (not probed).
    - Permissions: pure AX observation/action requires the caller to be AX-trusted (finding 13);
      synthesized CGEvents also land under the same Accessibility TCC category; AppleScript/System
      Events route would additionally need Automation (Apple Events) TCC — avoid AppleScript to
      keep a single permission surface (`inferred` from Apple's TCC categories; not verified).

## Conventions to follow

- **Package layout**: mirror the layer split — `jev_ultrafast/desktop/` (e.g. `ax.py` for the
  AX bridge + `chrome.py` target) exporting the same 4-call interface as `Browser`
  (`observe/fresh/act/close`, plus `StalePage`-equivalent), documented in
  `jev_ultrafast/desktop/README.md` like `jev_ultrafast/browser/README.md`; register exports in
  `jev_ultrafast/desktop/__init__.py` (`__all__`) like `jev_ultrafast/browser/__init__.py:1-5`.
- **Element-table shape**: ids `e1..`, `kind` limited to the model vocabulary
  (`click/fill/select` + `wait`/scroll controls), fields `id/kind/label/value/role` so
  `model.action_space()` (`model.py:152-182`) and the MCP formatting (`mcp_server.py:130-138`)
  work unchanged. Map AX roles → ARIA-ish roles (`AXButton→button`, `AXTextField/AXTextArea→textbox`,
  `AXCheckBox→checkbox`, `AXMenuBarItem/AXMenuItem→menuitem`, ...).
- **Guards**: re-verify each target immediately before performing its action (AX attributes are
  re-readable per node — this is the natural analogue of `snapshot.js:47-53` +
  `browser.py:144-168`); log execution before observing the result (AGENTS.md; `agent.py:120`).
- **MCP server**: new standalone stdio server, e.g. entry point `jev-desktop` →
  `jev_ultrafast.desktop_mcp:main`, `MCPServer("jev-desktop")`, same four-tool shape
  (`desktop_open/observe/act/close` or similarly prefixed), `json.dumps(..., indent=2)` results,
  error-as-JSON, single global session, zero model calls. Register it by adding one `Agent` entry
  (new SERVER_NAME) to the `install_mcp.py` registry or a sibling `scripts/install_desktop_mcp.py`,
  keeping `server_argv()` absolute-path + `--env-file` semantics (`install_mcp.py:42-49`).
- **Tests**: offline pytest under `tests/` with fake AX data and mocked `ApplicationServices`
  (same style as `tests/test_agent.py` mocking `cdp`); the live Chrome-AX check goes in a script
  (`scripts/check_ax.py`) mirroring `scripts/check_guards.py` — `data:` URL page, no model calls,
  `PASS: N ... ; no model calls` footer, and skip (don't fail) when `AXIsProcessTrusted()` is
  False so `make build` never blocks on a TCC prompt.
- **Commands**: `uv run ruff check .` (line-length 120, E/F/I), `uv run pytest`,
  `node --check` for any new JS, `uv build`; extend `scripts/doctor.py` with an
  AX-permission + Chrome-running check instead of a new health tool.
- **Dependencies**: add pyobjc behind a marker, e.g.
  `pyobjc-framework-ApplicationServices>=12; sys_platform == "darwin"` (+ Cocoa/Quartz), so Linux
  installs/tests keep working; never put credentials in code or configs (AGENTS.md); never commit.

## Risks / open questions

1. **`unknown` — Chrome web-content activation on current builds.** The AXEnhancedUserInterface
   write fails (`-25208`) on macOS 26.6 + Chrome 154; `AXWebArea` never appeared in probes. The
   layer may be limited to chrome UI (menus/window/toolbar/tabs) until one of these is verified:
   `--force-renderer-accessibility`, `chrome://accessibility` toggle, window-restore timing, or
   CDP `Accessibility.enable`. Plan should include a dedicated activation experiment as step 0.
2. **`unknown` — omnibox/tab-strip AX shape on Chrome 154** (roles, labels, press actions). Must be
   re-probed with a restored window; `AXToolbar` returned unsupported while minimized.
3. **`inferred` — TCC attribution for agent-spawned MCP servers** (finding 13): the Accessibility
   grant follows the host app; first run from a new agent host will prompt or silently fail.
   Doctor must detect and explain this (`AXIsProcessTrustedWithOptions` with
   `kAXTrustedCheckOptionPrompt` can prompt — decide deliberately whether to prompt).
4. **`inferred` — keyboard synthesis** (CGEventPost) not exercised; may behave differently across
   Secure Input / permissions; `kAXValueAttribute` writes may be rejected by some fields.
5. **`unknown` — window-manager vs element-id stability**: AX elements are not long-lived handles
   across UI changes; `fresh()` for desktop needs a re-resolution strategy (role+label+path
   matching) since there is no WeakMap like `snapshot.js:3-8`. Design needed, evidence missing on
   Chrome's AX id churn rate.
6. **Menu-bar depth**: Chrome has ~8.6k AXMenuItems under menus in one probe (bookmarks inflate
   it) — an observe() must cap traversal like `snapshot.js:99-100` (`omitted_actions`) or the
   element table explodes.
7. **Platform scope**: everything macOS-only; Linux/Windows out of scope per mission, but
   dependency markers and import guards are required to keep `uv run pytest` green cross-platform.
8. **`unknown` — whether AXPress on Chrome menu items triggers the full menu action without the
   app being frontmost**, and whether focus emulation (CDP-style, `browser.py:27`) has any AX
   analogue; background-tab operation is a stated product requirement (README "Background tab").

## Recommended approaches

1. **Direct pyobjc** (`pyobjc-framework-ApplicationServices` + Cocoa/Quartz, marker-gated) — no
   atomacos (stale 2021, GPLv2).
2. **Separate MCP server** (`jev-desktop` entry point, own SERVER_NAME in the install registry) —
   the browser server's tools and single-session globals would collide, and the desktop loop may
   not need `jev_navigate` semantics.
3. **Test strategy**: offline pytest with a fake AX tree + `scripts/check_ax.py` live probe against
   real Chrome (data: URL page, `AXIsProcessTrusted()` skip-guard, no model calls), with a
   step-0 activation experiment (`--force-renderer-accessibility` vs `chrome://accessibility`)
   before committing to the web-content scope.
