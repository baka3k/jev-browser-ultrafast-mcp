# Research: Codebase Touchpoints for a Windows UIA Backend

Date: 2026-10-16. Scope: enumerate every macOS/AX-specific site in `jev-ultrafast` and what a
second desktop backend (`UiaBackend`) implies, using the existing `AXBackend` Protocol seam
(`jev_ultrafast/desktop/ax.py:55-84`). All paths relative to repo root unless absolute. Evidence is
`path:line` in the current tree; `unknown` / `inferred` mark evidence gaps.

## Findings

### A. `jev_ultrafast/desktop/ax.py` — the seam and what surrounds it

1. **The Protocol is the seam, and it is complete** (backend-swappable, category (a)):
   `AXBackend` declares 7 methods — `application(bundle_id)`, `copy(element, attribute)`,
   `set(element, attribute, value)`, `perform(element, action)`, `is_settable(element, attribute)`,
   `action_names(element)`, `same(a, b)` (`ax.py:55-84`). `UiaBackend` implements exactly these;
   nothing else in the layer imports pyobjc.
2. **Attribute-name constants are AX-labeled strings** (`ax.py:23-37`): `ROLE="AXRole"`,
   `TITLE="AXTitle"`, `DESCRIPTION`, `HELP`, `VALUE="AXValue"`, `POSITION`, `SIZE`, `ENABLED`,
   `CHILDREN`, `PARENT`, `WINDOWS`, `FOCUSED_ELEMENT`, `MENU_BAR`, `MENUS`, `ATTRIBUTES`. They are
   plain strings passed through `backend.copy/set` — category (b): generic mechanism, AX naming.
   Who owns translation is an open design point (see Finding 27). Note `MENUS` and `ATTRIBUTES`
   are currently **unused** (dead constants; `AXMenus` was abandoned per
   `docs/logs/2026-10-16-desktop-app-layer.md` "Decision"), as is `ACTION_UNSUPPORTED`
   (`ax.py:20`, never referenced; `perform` just checks `error == 0`).
3. **Hardcoded raw AX strings bypass the constants** — a UIA implementer will trip on these:
   `"AXFocusedUIElement"` literal in `tree.py:192` and `tree.py:215` (the `FOCUSED_ELEMENT`
   constant exists but is not used there), `"AXPress"` literals in `tree.py:146` and
   `app.py:106,121`, `"AXManualAccessibility"` in `app.py:44` and `tests/test_desktop.py:63,222`,
   `"AXRole"/"AXChildren"` in `scripts/check_ax.py:85,88`.
4. **Error taxonomy is AX-flavored but semantically generic**: `AXError(RuntimeError)` with
   `.code`, and `ElementGone(AXError)` (kAXErrorInvalidUIElement) (`ax.py:40-52`). `ElementGone`
   is load-bearing outside the backend: `app.py:11,92,115,122`, `desktop_mcp.py:22,72,106`.
   A `UiaBackend` must raise the same types (UIA `COMError` / dead-hwnd → `ElementGone`) or the
   classes move to a neutral module (churn: 3 import sites + tests).
5. **Genuinely macOS-only in `PyobjcBackend`** (category (c)): guarded pyobjc import block
   (`ax.py:9-16`); `application()` resolves bundle id via `NSWorkspace...runningApplications()` +
   `AXUIElementCreateApplication(pid)` (`ax.py:99-103`); `same()` via `CFEqual` (`ax.py:139-145`);
   `_normalize` converts pyobjc position/size structs to `(x, y)` / `(w, h)` tuples
   (`ax.py:147-152`) — **this tuple contract is what `read_guard` and the tests expect**; a UIA
   backend must synthesize the same tuples from `BoundingRectangle` (one property, not two
   attributes).
6. **Error-code mapping to replicate**: `-25212`/`-25205` → `None` (absent), `-25202` →
   `ElementGone`, anything else → `AXError` (`ax.py:105-113`, `set/perform/is_settable`
   `ax.py:115-137`). UIA has no numeric parity (`unknown`: exact `COMError` → classification map
   must be derived on Windows; e.g. `UIA_E_ELEMENTNOTAVAILABLE` ≈ `ElementGone`).

### B. `jev_ultrafast/desktop/tree.py` — walker ownership

7. **`walk()` is dict-in/dict-out over the 7 Protocol methods only** (`tree.py:1-6` docstring,
   `tree.py:128-210`) — no pyobjc imports. It **can stay shared** with a UIA backend iff the
   backend speaks the attribute-string vocabulary; the AX-specific parts are the *inputs* (role
   strings, menu behavior), not the traversal machinery.
8. **`ROLE_MAP` maps AX raw roles → generic vocabulary** (`tree.py:32-44`): `AXButton→button`,
   `AXTextField/AXTextArea→textbox`, `AXMenuBarItem/AXMenuItem→menuitem`, `AXTabGroup→tab`,
   etc. Downstream consumers (`model.action_space()`, MCP formatting) only see the mapped
   values, so the target vocabulary is already portable. Category (b): a UIA backend can either
   emit AX-style raw role strings (map `ControlType`→`"AXButton"` at the backend) or the map
   gains UIA entries. `EDITABLE_ROLES`/`PRESSABLE_FALLBACK` operate on the mapped vocabulary
   (`tree.py:45-46`) — portable, but `PRESSABLE_FALLBACK`'s justification ("checkboxes/radios
   support AXPress universally", `tree.py:46`) does not transfer: UIA checkboxes use
   `TogglePattern`, not necessarily `Invoke` (`inferred` from UIA pattern semantics; needs
   verification).
9. **Role-string logic constants are AX-specific** (category (c) as strings, (b) as intent):
   `SECURE_ROLE="AXSecureTextField"` (`tree.py:47`, used `tree.py:169-170`), `MENU_ROLES={"AXMenu"}`
   (`tree.py:48`, used `tree.py:177-184,189`), `WINDOW_ROLE="AXWindow"` (`tree.py:49`, used
   `tree.py:112`). UIA equivalents: `IsPassword` property (not a role — the current "skip by role
   string" mechanism has no direct UIA analogue), `ControlType_Menu`, `ControlType_Window`.
10. **Menu-open detection is macOS-AX behavior, not just naming**: a closed `AXMenu` is descended
    only when the app's focused element lives inside it (`tree.py:177-184` + `within()`
    `tree.py:116-125`, decided per `docs/logs/2026-10-16-desktop-app-layer.md` because
    `AXMenus` is unsupported on Chrome). On Windows, menu items are typically enumerable while
    closed (`unknown`: needs live verification — the rule may harmlessly never fire or may
    wrongly prune).
11. **Menu-bar traversal is an app-element attribute read** (`tree.py:196-198`:
    `backend.copy(app, MENU_BAR)` then `visit`). Windows apps usually expose menus inside the
    window element tree, not as an app-level attribute — the backend may return `None` here and
    the walker degrades gracefully, but `check_ax.py`'s `MIN_MENU_ITEMS >= 5` menu-bar assertion
    (`scripts/check_ax.py:26,62-64`) is macOS-shaped.
12. **`read_guard`/`path_of`/`marker_of` dependencies** (`tree.py:79-105`, `tree.py:213-227`):
    role, label (TITLE→DESCRIPTION→HELP precedence, `tree.py:71-76`), ENABLED, VALUE for editable
    roles, **parent-path identity anchor** (PARENT chain up to the app element,
    `tree.py:79-88`), and **(position, size) tuple**. UIA provides all of these:
    `TreeWalker`/parent element, `BoundingRectangle` (backend splits it into the two-attribute
    contract), focused element property. `same()` could additionally use `RuntimeId` — but note
    `RuntimeId` stability across re-enumeration is not guaranteed (`unknown`; COM pointer
    identity works while an element lives, `inferred`). The guard tuple shape is in-memory only
    (reconciled per session, `app.py:55-77`), so a UIA guard with identical arity composes with
    `_reconcile_ids` unchanged.
13. **`windows_of` encodes a macOS quirk**: windowless apps list the application element itself in
    `AXWindows`, filtered out by role (`tree.py:108-113`); `walk()` walks `windows[0]`'s title into
    `state["title"]` (`tree.py:200-203`). The same shape works if the UIA backend returns real
    top-level windows for the process.
14. **Budgets are portable**: `MAX_ACTIONS=250, MAX_NODES=3000, MAX_DEPTH=25, MAX_TEXT=6000,
    MAX_MENU_CHILDREN=40` (`tree.py:26-30`) and the omitted-subtree counter (`tree.py:186-188`) —
    no platform coupling. `fingerprint()` hashes semantic content only (`tree.py:230-237`) —
    portable.

### C. `jev_ultrafast/desktop/app.py` — facade

15. **Backend selection is one hard-coded point**: `_default_backend()` imports and returns
    `PyobjcBackend` (`app.py:20-23`), used by `DesktopApp.__init__` when `backend=None`
    (`app.py:27-29`). This is where platform dispatch (`sys.platform == "win32"` → `UiaBackend`)
    or an env override lands. `DesktopApp(bundle_id, backend=...)` injection already works for
    tests (`tests/test_desktop.py:157-163`).
16. **`_attach` best-effort Electron opt-in is macOS-only logic** (category (c)):
    `self.backend.set(app, "AXManualAccessibility", True)` inside try/except pass
    (`app.py:40-46`); `tests/test_desktop.py:203-228` contract it (opt-in attempted; refusal
    tolerated; counted as config, not a UI mutation). Windows UIA has no equivalent opt-in
    (`inferred`: recent Chromium on Windows exposes web content via UIA by default; needs
    verification). Options: keep the generic `set(...)` best-effort call (a UIA backend returns
    False) or gate it per backend.
17. **Action execution hardcodes AX action/attribute strings**: click =
    `backend.perform(ref, "AXPress")` (`app.py:106`); pressability = `"AXPress" in
    backend.action_names(ref) or role in CHECKBOX_RADIO` (`app.py:119-122`); fill =
    `backend.set(ref, VALUE, text)` + read-back verification (`app.py:109-112`). The
    fill read-back loop is semantically generic (UIA `ValuePattern.SetValue` +
    `CurrentValue`); the "AXPress"/"AXValue" strings must be translated by the backend or
    neutralized at the call sites.
18. **Addressing**: `DesktopApp.bundle_id` stored and re-resolved on every observation
    (`app.py:27-38` docstring "Re-resolve the app on every observation: restarts and pid reuse
    stay safe"). The attribute *name* and the Protocol parameter `application(bundle_id: str)`
    are macOS; an exe-name target slots into the same string parameter but the naming/docs lie
    (`StaleState` message `"com.google.Chrome is not running"` is fine, attribute name is not).

### D. `jev_ultrafast/desktop/__init__.py` + `jev_ultrafast/desktop_mcp.py` — MCP surface

19. **`__init__.py` exports only `DesktopApp`/`StaleState`** (`desktop/__init__.py:1-5`); only its
    docstring says "macOS AX observation". Platform-neutral otherwise.
20. **`desktop_mcp.py` platform assumptions**: module docstring "expose macOS Accessibility app
    control" + "trusted AXPress / AXValue write" (`desktop_mcp.py:1-15`); `DEFAULT_ALLOW =
    "com.google.Chrome"` — a macOS bundle id as the cross-platform default (`desktop_mcp.py:24`);
    allowlist error message says "comma-separated bundle ids" (`desktop_mcp.py:40-44`);
    `desktop_attach` tool schema docstring "by bundle id (e.g. com.google.Chrome)"
    (`desktop_mcp.py:126-132`). The schema itself is a plain `app: str` — an exe name fits
    mechanically. `ElementGone` imported from `desktop.ax` (`desktop_mcp.py:22`). Tool bodies
    (`observe_state`, `act_by_id`, `close_app`) are platform-neutral.

### E. `scripts/check_ax.py` + `tests/test_check_ax.py` — live-check pattern

21. **The skip chain is a pure function** `decide_skip(darwin, pyobjc_ok, trusted,
    chrome_running, window_count)` → reason-or-None (`scripts/check_ax.py:41-55`), offline-tested
    over every unavailable condition (`tests/test_check_ax.py:21-35`), and `main()` skips with
    exit 0 and a `PASS: 0 desktop AX checks; no model calls (skipped)` footer
    (`check_ax.py:123-126`). A Windows live check replicates this shape: (not-windows, comtypes/
    UIA missing, target app not running, no window). macOS-only extras: TCC probe
    `AXIsProcessTrusted` (`check_ax.py:104-110`), spike-verdict gating for mutations
    (`check_ax.py:25,136-150`, reads `docs/plans/desktop-app-layer/spike-activation.md`).
22. **Read-only assertions split into portable vs macOS-shaped**: `check_table` window/secret/
    duplicate-id/cap assertions are portable (`check_ax.py:58-74`); the `MIN_MENU_ITEMS >= 5`
    menu-bar assertion and `raw_roles` probe (`check_ax.py:26,62-64,77-89`) assume a menu bar.
    The committed-verdict test `test_the_committed_spike_doc_parses` (`tests/test_check_ax.py:73-75`)
    is macOS-spike-specific.

### F. Tests — fake-backend shape and hardcoded AX strings

23. **`FakeBackend` satisfies the Protocol over plain objects** (`tests/test_desktop.py:35-87`):
    `copy()` dispatches on the `tree.*` constant strings against a dict built from `FakeElement`
    attributes (`test_desktop.py:20-31`: role/title/value/desc/help/children/parent/press/
    writable/position/size/enabled/dead/transform); `set()` logs mutations but routes
    `"AXManualAccessibility"` to a separate `opt_ins` list (`test_desktop.py:62-72`);
    `perform()`/`action_names()` use `element.press` lists; `same()` is `a is b`; dead elements
    raise `ElementGone`. `make_app()` builds an AX-role tree (`test_desktop.py:90-112`).
    **This entire offline suite runs the layer through the Protocol only** — a `UiaBackend`
    contract needs the same shape; whether the fake speaks AX strings (if the backend translates)
    or a new vocabulary determines reuse vs duplication.
24. **Tests hardcoding AX strings** (each needs a UIA twin or neutralization):
    role-mapping table `test_desktop.py:125-134`; `press=("AXPress",)` defaults throughout
    `FakeElement` usage; `("perform", "AXPress")` mutation assertions
    (`test_desktop.py:341`, `test_desktop_actions.py:20`, `test_desktop_mcp.py:67`);
    `AXManualAccessibility` (`test_desktop.py:63,222`); secure-field role
    (`test_desktop.py:97,150-154`); windowless-app macOS quirk (`test_desktop.py:255-259`).
25. **pyobjc-layer unit tests mock the C API surface** — `FakeAXModule` with
    `AXUIElementCopyAttributeValue` etc. returning `(code, value)` pairs, `FakeWorkspace` with
    `runningApplications()` (`test_desktop.py:324-361`); error-mapping contract
    `test_pyobjc_backend_error_mapping` (`test_desktop.py:363-385`); import-guard test via
    `monkeypatch.setitem(sys.modules, "ApplicationServices", None)` + `importlib.reload`
    (`test_desktop.py:398-411`). A `UiaBackend(uia=None)` injection point plus a fake comtypes/
    UIAutomation module is the direct analogue — feasible with the same style.
26. **MCP tests are already platform-neutral**: `patch_desktop` monkeypatches
    `desktop_mcp.DesktopApp` (`tests/test_desktop_mcp.py:19-23`); allowlist tests use
    `com.test.app` strings (`test_desktop_mcp.py:26-40`). Installer contracts for the
    two-server registry: `tests/test_make_scripts.py:131-175`.

### G. Packaging, Makefile, install, doctor, docs

27. **pyproject**: pyobjc deps marker-gated `; sys_platform == 'darwin'`
    (`pyproject.toml:12-14`) — the convention to copy for the Windows dep
    (`unknown`: which library — direct comtypes vs pywinauto vs `uiautomation` — drives both the
    marker line and the fake-layer design). Entry point `jev-desktop =
    jev_ultrafast.desktop_mcp:main` (`pyproject.toml:20`): one server can serve both platforms
    if `desktop_mcp`/`DesktopApp` dispatch backend by platform; a separate entry point would
    require a third `SERVERS` registry entry (`install_mcp.py:45-48`) + installer tests.
28. **Makefile**: `install-all` described as "also register jev-desktop (macOS AX; explicit
    opt-in)" (`Makefile:4,26`); `check-desktop` runs `scripts/check_ax.py` unconditionally
    (`Makefile:28,62-63`) — on Windows this needs platform dispatch inside the script or a new
    target; `doctor` delegates to `scripts/doctor.py` (`Makefile:65-67`).
29. **install_mcp.py has no darwin gating** — it installs on any OS; only wording is
    macOS-specific: SERVERS description "desktop-app automation over macOS AX (opt-in)"
    (`install_mcp.py:47`), post-install note "macOS Accessibility permission ... required on
    first use" (`install_mcp.py:448-450`). Docstrings at `install_mcp.py:15-17`.
30. **doctor.py**: `check_desktop` emits the `Desktop AX` line — non-darwin →
    "skipped — macOS only" (`doctor.py:163-167`); TCC probe (`doctor.py:168-180`); allowlist
    display (`doctor.py:181-182`). A Windows branch needs symmetric "Desktop UIA" readiness
    (library importable, target resolvable). `unknown`: whether UIA needs any permission
    analogue (`inferred`: no TCC equivalent for same-session, non-elevated targets; elevated
    apps require an elevated client). Related gap: `chrome_installed()` knows only macOS paths +
    Linux `which` names, no Program Files candidates (`doctor.py:53-59`).
31. **Predecessor plan docs**: `docs/plans/desktop-app-layer/plan.md` frontmatter `status:
    pending` (`plan.md:4`) although the layer is implemented per
    `docs/logs/2026-10-16-desktop-app-layer.md`; scope HOLD line "macOS-only; Windows UIA /
    Linux AT-SPI stay a reserved seam, no code" (`plan.md:21`); deferred list "Windows/Linux
    backends ..." (`plan.md:44`). `research-digest.md` platform-scope risk (`research-digest.md:262-263`).
    **`jev_ultrafast/desktop/README.md:50-51` explicitly promises**: "Windows UIA / Linux AT-SPI
    are a reserved seam (`AXBackend` Protocol), deliberately unimplemented" — the new plan
    fulfills this and must update it.
32. **README claims that must stay consistent** (AGENTS.md rule): line 5 ("now driving macOS
    desktop apps too"), line 10 and 36 (jev-desktop / desktop layer descriptions), line 47
    ("macOS — only for the desktop layer"), line 118 (`JEV_DESKTOP_ALLOW` "comma-separated
    bundle ids"), lines 152-165 (mermaid: jev-desktop → "macOS Accessibility (AX)"), lines
    183/185 (make targets), the `jev-desktop` section lines 253-295 (bundle-id attach,
    AXPress/AXValue wording, AXManualAccessibility claim, `make check-desktop`), inline example
    lines 333-338 (`DesktopApp("com.google.Chrome")`), file table lines 354-362 (`ax.py` "macOS
    AX layer"), tests line 375, scope paragraph line 381 ("The desktop layer is macOS-only").
    Also `docs/architecture.md:9,35-59,171-175`. `examples/` has no desktop example (only
    `custom_text_provider.py`, `external_agent.py`, `flights.py`, `run.py`) — no touchpoint, but
    README's inline example doubles as the example surface.

## Addressing implications (research question 2, consolidated)

- `DesktopApp(bundle_id)` (`app.py:27`), `backend.application(bundle_id)` (`ax.py:58-60,99-103`),
  MCP `desktop_attach(app)` (`desktop_mcp.py:126`), and `JEV_DESKTOP_ALLOW`
  (`desktop_mcp.py:24,29-31`) form the addressing chain. Exe-name addressing implies:
  (i) `UiaBackend.application(target)` resolves exe name (or path/title — `unknown`: exact
  matching rule) to a process then to a root UIA element; (ii) the Protocol parameter and
  `DesktopApp` attribute get neutral names or the docs call the macOS value a bundle id and the
  Windows value an exe name; (iii) `JEV_DESKTOP_ALLOW` entries become platform-mixed
  (mechanically unchanged — flat string list — but `DEFAULT_ALLOW="com.google.Chrome"` must
  become platform-conditional or documented as darwin-only); (iv) security semantics shift:
  an exe-name match is broader than a bundle id (any process with that name, any path) —
  `inferred` path-scoped entries may be needed for parity with the README's "treat allowlist
  entries as grants" stance (`README.md:295`).

## Conventions to follow

- **Fake-backend shape**: plain-object elements + 7-method fake with a mutation log, opt-in
  side-channel, and `ElementGone` on death (`tests/test_desktop.py:35-87`); `make_app()` factory;
  backend injected as `DesktopApp(bundle, backend=...)`. New backend gets an injectable native
  module (`UiaBackend(uia=None)`) mirroring `PyobjcBackend(ax=..., workspace=...)`
  (`ax.py:90-92`) with a fake C-API-module unit test (`test_desktop.py:324-385`).
- **Marker-gated deps**: `; sys_platform == 'darwin'` pattern (`pyproject.toml:12-14`) → add the
  Windows equivalent so Linux/macOS test runs stay green; guarded module-level import with
  lazy `RuntimeError` (`ax.py:9-16`) + a `sys.modules` monkeypatch reload test
  (`test_desktop.py:398-411`).
- **Live-check skip pattern**: pure `decide_skip(...)` function, exit 0 with an actionable
  reason, `PASS: N ... ; no model calls` footer, mutations opt-in, plus an offline pytest
  contract of the skip chain (`scripts/check_ax.py:41-55,123-126`,
  `tests/test_check_ax.py:21-35`).
- **README consistency rule**: "Keep examples, README claims, raw evidence, and model-call
  counts consistent" (`AGENTS.md:13`) — the README/architecture/desktop-README claim sweep is
  part of the change set, not an afterthought (Finding 32).
- **Never retry mutations; log execution before observing** (`AGENTS.md:9`) — `app.act()` and the
  MCP `act_by_id` flow already encode this; a UIA backend must not change the one-attempt
  semantics (`tests/test_desktop_actions.py:98-104`).
- **Offline tests only in pytest**; no paid APIs, no model calls; live checks are scripts
  (`tests/test_desktop.py:1`, `docs/architecture.md:171-175`).
- Element-table shape `{id, kind, label, role, value, node}` is consumed by
  `model.action_space()` (`jev_ultrafast/agent/model.py:152-183`) and MCP formatting — the UIA
  backend must emit the identical mapped vocabulary (`button/textbox/...`), not raw UIA types.

## Risks / open questions

1. `unknown` — **choice of Windows UIA access library** (direct `comtypes` +
   `UIAutomationClient`, `pywinauto`, or `uiautomation`): drives the pyproject marker, the fake
   native-module design, and `uv build` on non-Windows (comtypes imports must stay guarded).
2. `unknown` — **`same()` identity semantics on UIA**: `RuntimeId` reuse across re-enumeration vs
   COM pointer identity vs `IUnknown::Compare` (`inferred`: pointer equality while alive +
   RuntimeId fallback; needs a decision and a live Windows probe).
3. `unknown` — **secure-field handling**: current skip is by AX role string (`tree.py:47,169-170`);
   UIA signals it via the `IsPassword` property, which does not fit the role-string mechanism —
   either the backend maps IsPassword into the role vocabulary or tree.py grows a property hook.
4. `unknown` — **menu behavior on Windows**: whether the closed-menu focus rule
   (`tree.py:177-184`) and the app-level `MENU_BAR` read (`tree.py:196-198`) match UIA reality
   per app framework (Win32, WinUI, Electron, Qt) — needs the Windows analogue of the activation
   spike (`scripts/ax_probe.py`); `check_ax.py`'s `MIN_MENU_ITEMS` assertion has no guaranteed
   Windows equivalent.
5. `unknown` — **whether the AX-string vocabulary stays the internal lingua franca** (backend
   translates UIA→AX names, `tree.py` untouched) or a neutral vocabulary is introduced (touches
   `tree.py`, `ROLE_MAP`, all fake-element trees, tests, desktop README). Evidence does not
   decide it; it is the largest sizing fork.
6. `inferred` — **AXManualAccessibility has no Windows equivalent**; the attach-time opt-in
   (`app.py:40-46`) and its two tests (`tests/test_desktop.py:203-228`) become darwin-specific
   behavior that a UIA backend must tolerate (return False) or skip.
7. `inferred` — **allowlist security parity**: exe-name matching is weaker than bundle-id
   matching (no signed-identity); README's "treat allowlist entries as grants" guidance
   (`README.md:295`) needs Windows-specific wording; UIA elevation mismatch (elevated target vs
   non-elevated client) is a failure mode doctor should mention.
8. `inferred` — **guard tuple equivalence**: `read_guard` needs (position, size) as separate
   attributes; UIA exposes one `BoundingRectangle` — the backend splits it, but coordinate
   systems (physical vs logical DPI pixels) may differ from macOS points (`unknown`: DPI
   awareness of the MCP server process).
9. Dead-code candidates to not confuse with seams: `MENUS`/`ATTRIBUTES` constants (`ax.py:36-37`),
   `ACTION_UNSUPPORTED` (`ax.py:20`) — unused today; `ax.py:1` module docstring and
   `desktop/__init__.py:1` say "macOS".
10. `docs/plans/desktop-app-layer/plan.md:4` frontmatter still says `status: pending` although
    implemented (`docs/logs/2026-10-16-desktop-app-layer.md`) — the new plan's status field
    should be set deliberately and the predecessor's status corrected or noted.

## Recommended approaches

1. **Translate at the backend, keep AX strings as the internal vocabulary**: `UiaBackend` maps
   UIA properties/patterns to the existing attribute-string Protocol (role→AX-style names,
   `BoundingRectangle`→POSITION/SIZE, `Invoke`→"AXPress"), so `tree.py`, `app.py` fill logic, and
   the element-table contract stay untouched — smallest diff, fulfilled "reserved seam".
2. **One platform-dispatch seam + one addressing decision**: `_default_backend()` picks by
   `sys.platform` (`app.py:20-23`), `application(target)` neutralized to bundle-id-or-exe-name,
   `DEFAULT_ALLOW`/docs/error strings made platform-aware; gate `AXManualAccessibility` and the
   menu-bar live-check assertions per platform.
3. **Mirror the proof pattern 1:1**: `UiaBackend(uia=None)` + fake comtypes layer for offline
   translation/error tests, `decide_skip`-style `scripts/check_uia.py` (or platform dispatch in
   `check_ax.py`) for the Windows live check, and a single README/desktop-README/architecture
   claims sweep to satisfy the AGENTS.md consistency rule.
