# ModelForge Desktop Design System

## Product Character

ModelForge is a **Local AI Development & Agent Workstation**. The interface uses restrained, neutral engineering surfaces (zinc scale), precise data typography, thin structural boundaries, and status-led feedback. It is not a generic SaaS dashboard or an RGB cyberpunk theme.

## Tokens (single source: `client/pyside6/theme/tokens.py`)

The implementation ships **two palettes** — Light (default workspace) and Dark — plus shared layout metrics in `theme/metrics.py`.

### Palette (Dark shown; Light mirrors with zinc-light values)

| Role | Token | Value |
|---|---|---|
| Application background | `bg` | `#0F0F10` |
| Surface (panels, inputs) | `surface` | `#18181B` |
| Subtle surface | `surface_subtle` | `#202023` |
| Hover / selection | `hover` / `selection` | `#28282B` / `#2A2A2E` |
| Borders | `border` / `border_strong` | `rgba(255,255,255,.08)` / `.14` |
| Text | `text` / `muted` / `dim` | `#F4F4F5` / `#A1A1AA` / `#71717A` |
| Accent (primary action) | `accent` + `accent_fg` | `#F4F4F5` on `#18181B` |
| Success / Warning / Danger / Info | `success` / `warning` / `danger` / `info` | `#4ADE80` / `#FBBF24` / `#FB7185` / `#60A5FA` |

`CYAN #4DE8FF` and `PURPLE #9B7CFF` remain **reserved future accent candidates**; the shipped accent is the foreground zinc color. Status colors communicate state and are not decorative. The UI font is the system interface stack (`FONT_UI`); engineering telemetry uses `FONT_MONO`. Radii are 6/8/10px only (`RADIUS_SM/MD/LG`). Layout primitives: `SIDEBAR_WIDTH=236`, `TOPBAR_HEIGHT=52`; window metrics (`MIN_WINDOW 1180×720`, `STATUSBAR_HEIGHT`, `CONTENT_MAX_WIDTH`) live **only** in `theme/metrics.py` — never redefine a token in a second module.

## Information Architecture

The permanent left rail groups **Command** (Overview, Chat, Models, Datasets, Training, Knowledge, Agents), **Operations** (Tasks, Runtime, Activity), and **System** (Settings). The top bar identifies the product, active area, backend health, and available compute telemetry. A bottom line communicates current service or stream state; it must not expose raw endpoint URLs or internal error codes — details belong in tooltips (correlation IDs included).

## Components

`MFPanel`, `MFSection`, `MFMetric`, `MFStatusBadge`, and `MFEmptyState` are the starting primitives. Page identity uses `MFSection(eyebrow, title)` (or a `QLabel` with `setProperty("role", "pageTitle")` — `setObjectName("pageTitle")` does nothing). Every list/table that can be empty overlays `install_empty_state(view, title, detail)` from `components/mf/primitives.py` instead of inline placeholder rows. New pages must reuse these or the global theme rather than adding page-specific visual systems; page-level `setStyleSheet` is limited to transparent-background adjustments. `AsyncApiMixin`, `TaskStore`, and existing streaming workers remain the required boundary for real API interactions.

## Interaction

Primary actions use the accent (foreground zinc) button; destructive actions remain quiet but visibly dangerous. Buttons that operate on a selected row (edit/delete/retry/lifecycle) stay **disabled until a row is selected** — empty or unselected lists never expose destructive actions. Keyboard focus always uses the visible outline. Streaming, running, progress, and reconnecting may animate only when supported by actual data. Metrics absent from the service must render `Unavailable` rather than approximated values.

## Accessibility, i18n, and Scaling

The shell has a minimum viewport of 1180×720 and supports standard 1280×720 through high-DPI desktop resolutions. Text uses readable system sizes, interactive controls expose focus, disabled controls reduce contrast without disappearing, and status never depends on color alone. User-facing strings originate as Chinese source text and map to English/Japanese through `i18n/ui_localizer._TEXT` (or the `i18n/*.json` shell keys); hardcoding English literals in page code is a defect.
