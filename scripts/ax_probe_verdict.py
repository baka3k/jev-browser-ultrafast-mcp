"""Verdict formatting for ax_probe. Stdlib only, so pytest may import it anywhere."""

EXIT_OK = 0  # an activation recipe exposed web content
EXIT_CHROME_UI = 2  # chrome UI readable, web content unreachable
EXIT_NO_AX = 3  # no usable accessibility tree at all

RECIPES = {
    "baseline": "web content readable with no activation step",
    "role-read": "reading AXRole enabled native AX mode",
    "enhanced-ui": "AXEnhancedUserInterface write enabled full mode",
    "relaunch-flag": "Chrome relaunched with --force-renderer-accessibility",
    "accessibility-page": "visiting chrome://accessibility enabled renderer AX",
    "cdp-a11y": "CDP Accessibility.enable exposed the renderer tree",
}


def verdict_line(verdict: str) -> str:
    return f"VERDICT={verdict}"


def masking_line(masking: str) -> str:
    return f"MASKING={masking}"


def exit_code(verdict: str) -> int:
    if verdict == "none":
        return EXIT_NO_AX
    if verdict == "chrome-ui-only":
        return EXIT_CHROME_UI
    if verdict in RECIPES:
        return EXIT_OK
    raise ValueError(f"unknown verdict: {verdict}")


def summarize(candidates: list[dict], counts: dict) -> list[str]:
    """Human-readable log lines; `counts` maps role -> occurrences."""
    lines = []
    for candidate in candidates:
        lines.append(f"[{candidate['name']}] {candidate['outcome']}")
    if counts:
        interesting = {r: n for r, n in sorted(counts.items()) if r in (
            "AXWebArea", "AXToolbar", "AXTextField", "AXButton", "AXMenuBarItem",
            "AXSecureTextField", "AXTabGroup", "AXRadioButton",
        )}
        rendered = ", ".join(f"{role}={n}" for role, n in interesting.items()) or "none"
        lines.append(f"roles seen: {rendered} (distinct roles: {len(counts)})")
    return lines
