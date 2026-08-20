# ModelForge Future UI Design System

## Product Character

ModelForge is a **Local AI Development & Agent Workstation**. The interface uses a restrained dark engineering surface, precise data typography, thin structural boundaries, and status-led feedback. It is not a generic SaaS dashboard or RGB cyberpunk theme.

## Tokens

| Role | Token | Value |
|---|---|---|
| Application background | `BG` | `#07090D` |
| Secondary surface | `BG_ELEVATED` | `#0B0F14` |
| Panel | `PANEL` | `#10151C` |
| Primary signal | `CYAN` | `#4DE8FF` |
| Secondary signal | `PURPLE` | `#9B7CFF` |
| Success | `SUCCESS` | `#4DFFB8` |
| Warning | `WARNING` | `#FFC857` |
| Error | `DANGER` | `#FF5C7A` |

The UI font is the system interface stack. Engineering telemetry uses the system monospace stack. Radii are 4/6/8px only; status colors communicate state and are not decorative.

## Information Architecture

The permanent left rail groups **Command** (Overview, Chat, Models, Datasets, Training, Knowledge, Agents), **Operations** (Tasks, Runtime, Activity), and **System** (Settings). The top bar identifies the product, active area, backend health, and available compute telemetry. A bottom line communicates current service or stream state.

## Components

`MFPanel`, `MFSection`, `MFMetric`, `MFStatusBadge`, and `MFEmptyState` are the starting primitives. New pages must reuse them or the global theme rather than adding page-specific visual systems. `AsyncApiMixin`, `TaskStore`, and existing streaming workers remain the required boundary for real API interactions.

## Interaction

Primary actions use cyan; destructive actions remain quiet but visibly dangerous. Keyboard focus always uses the cyan outline. Streaming, running, progress, and reconnecting may animate only when supported by actual data. Metrics absent from the service must render `Unavailable` rather than approximated values.

## Accessibility and Scaling

The shell has a minimum viewport of 1180×720 and supports standard 1280×720 through high-DPI desktop resolutions. Text uses readable system sizes, interactive controls expose focus, disabled controls reduce contrast without disappearing, and status never depends on color alone.
