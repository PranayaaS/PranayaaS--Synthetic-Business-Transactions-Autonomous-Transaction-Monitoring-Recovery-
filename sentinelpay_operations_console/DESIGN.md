---
name: SentinelPay Operations Console
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#bcc9cd'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#869397'
  outline-variant: '#3d494c'
  surface-tint: '#4cd7f6'
  primary: '#4cd7f6'
  on-primary: '#003640'
  primary-container: '#06b6d4'
  on-primary-container: '#00424f'
  inverse-primary: '#00687a'
  secondary: '#4fdbc8'
  on-secondary: '#003731'
  secondary-container: '#04b4a2'
  on-secondary-container: '#003f38'
  tertiary: '#7bd0ff'
  on-tertiary: '#00354a'
  tertiary-container: '#23b2ec'
  on-tertiary-container: '#00415a'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#acedff'
  primary-fixed-dim: '#4cd7f6'
  on-primary-fixed: '#001f26'
  on-primary-fixed-variant: '#004e5c'
  secondary-fixed: '#71f8e4'
  secondary-fixed-dim: '#4fdbc8'
  on-secondary-fixed: '#00201c'
  on-secondary-fixed-variant: '#005048'
  tertiary-fixed: '#c4e7ff'
  tertiary-fixed-dim: '#7bd0ff'
  on-tertiary-fixed: '#001e2c'
  on-tertiary-fixed-variant: '#004c69'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 2rem
    fontWeight: '600'
    lineHeight: 2.5rem
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Inter
    fontSize: 1.5rem
    fontWeight: '600'
    lineHeight: 2rem
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 1.25rem
    fontWeight: '600'
    lineHeight: 1.75rem
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 1.125rem
    fontWeight: '500'
    lineHeight: 1.5rem
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: '400'
    lineHeight: 1.5rem
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: '400'
    lineHeight: 1.25rem
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: '400'
    lineHeight: 1rem
    letterSpacing: 0.01em
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 0.875rem
    fontWeight: '500'
    lineHeight: 1.25rem
    letterSpacing: -0.01em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: '500'
    lineHeight: 1rem
    letterSpacing: 0em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 0.6875rem
    fontWeight: '400'
    lineHeight: 0.875rem
    letterSpacing: 0.02em
  metric-display:
    fontFamily: JetBrains Mono
    fontSize: 1.75rem
    fontWeight: '600'
    lineHeight: 2rem
    letterSpacing: -0.03em
  metric-sub:
    fontFamily: JetBrains Mono
    fontSize: 1.125rem
    fontWeight: '500'
    lineHeight: 1.375rem
    letterSpacing: -0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  margin: 1.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system serves mission-critical bank operations teams, settlement engineers, and fraud analysts who monitor high-throughput cooperative payment corridors around the clock. The interface evokes unyielding stability, clinical precision, and real-time situational awareness. 

The aesthetic is a high-density, mission-critical operations console blending **Modern Technical Minimalism** with **Tactical Observability Dark Mode**. Visual clutter is eliminated in favor of strict structural outlines, muted surface layering, and luminous visual signals that immediately draw the eye to latency spikes, settlement discrepancies, and corridor degradations. 

Key principles:
- **Zero-Latency Readability**: Information hierarchy prioritizes immediate triage of payment lifecycles and anomaly detection.
- **Instrument-Grade Precision**: Fine 1px borders, compact padding, and monospace numeric alignment build trust and spatial density.
- **Controlled Luminescence**: Glowing cyan and status accents are reserved strictly for active telemetry indicators, alerts, and focal actions—never for passive decoration.

## Colors

The palette is engineered specifically for prolonged viewing in low-light operations command centers, preventing optical fatigue while maintaining extreme contrast for critical telemetry.

### Palette Architecture
- **Canvas & Base Layer**: Deep Navy Black (`#0A0F1D`) grounds the entire viewport.
- **Surface Elevation Levels**:
  - `surface-1` (Panels / Sidebars): `#0F172A`
  - `surface-2` (Cards / Tables / Inspect Drawers): `#1E293B`
  - `surface-3` (Hover states / Elevated overlays): `#334155`
- **Structural Outlines**: Crisply defined borders use `#334155` (default) and `#1E293B` (recessed separators). Active or focused borders use `#06B6D4`.
- **Text & Data Contrast**:
  - Primary Readout: `#F8FAFC` (95% contrast against base)
  - Secondary Readout: `#94A3B8` (metadata, passive labels)
  - Muted/Disabled: `#475569` (placeholders, inactive indicators)

### Status & Telemetry Semantic Scale
Semantic signals are absolute and must never be repurposed for purely aesthetic components:
- **Healthy / Cleared (`#10B981`)**: Instant settlement nominal, quorum intact, API responses `<120ms`.
- **Degraded / Warning (`#F59E0B`)**: Reconciliation drift, gateway queue accumulation, retry bursts.
- **Critical / Interrupted (`#EF4444`)**: Batch dropped, ledger imbalance, circuit breaker trip.
- **Telemetry Glows**: Radial box-shadows matching status tokens are restricted to a subtle spread of `0 0 12px` at `25%` alpha for active warning and critical conditions.

## Typography

The typographic strategy balances human scanning efficiency with computational clarity:
- **Inter** handles structural UI labels, contextual instructions, and section titles. Features tabular lining figures enabled by default (`tnum`) across all UI elements.
- **JetBrains Mono** governs all dynamic metrics, transaction hashes, ledger identifiers, ISO 20022 message codes, currency readouts, countdown timers, and UTC timestamps. It enforces rigid spatial consistency, preventing jitter during rapid stream updates.

### Scaling and Implementation Rules
- Numerical readouts (`metric-display`, `metric-sub`) must always render with vertical center alignment to adjacent delta badges.
- All micro-labels (`label-sm`) render in uppercase with `0.05em` track expansion when used as table column headers or data card pre-headers.

## Layout & Spacing

The layout is built on a high-density, viewport-optimized fluid operational grid tailored to multi-monitor workstations and mission control consoles.

### Layout Rhythm
- **Grid Architecture**: 24-column flexible grid system on screens `>= 1440px` allowing fine division of telemetry columns; collapses to 12 columns between `1024px` and `1439px`, and 4 columns on secondary monitoring screens (`< 1024px`).
- **Vertical Rhythm**: Base 4px sub-grid unit. Padding inside metric cards is condensed (`space-md`) to ensure critical health charts, error streams, and reconciliation balances reside above the fold.
- **Gutters & Separation**: Strict `1rem` (16px) gutters across primary telemetry quadrants with `1px` structural borders between sibling monitors.

### Breakpoint Strategy
- **Desktop Ultrawide / Multi-Display (>= 1920px)**: 4-quadrant layout with persistent left rail navigation, 3-column telemetry core, and right-hand streaming transaction waterfall.
- **Desktop Standard (1280px - 1919px)**: Dual-stream split; telemetry metrics stacked atop tabular settlement queues.
- **Field Terminal / Tablet (768px - 1279px)**: Collapsible sidebar into compact icon dock; summary telemetry tabs with drill-down modals.

## Elevation & Depth

This design system avoids traditional dropped shadows, which soften interfaces and reduce apparent density. Instead, depth is conveyed through **Low-Contrast Outlines**, **Tonal Layering**, and **Luminescent Boundary States**.

### Hierarchy of Surfaces
- **Level 0 (App Shell)**: `#0A0F1D` — Recessed, passive space holding structural layout dividers.
- **Level 1 (Data Grid & Dashboard Workspaces)**: `#0F172A` with a crisp `1px solid #334155` outline.
- **Level 2 (Active Cards & Cell Modules)**: `#1E293B` with border `1px solid #334155`.
- **Level 3 (Modal Drawers & Emergency Overlays)**: `#1E293B` elevated with an inner highlight of `inset 0 1px 0 0 rgba(255, 255, 255, 0.05)` and a subtle directional perimeter halo (`0 8px 32px -4px rgba(0, 0, 0, 0.6)`).

### Instrument Glows
Selected critical elements utilize ambient state glows instead of standard shadows:
- **Focused Input / Target**: `0 0 0 1px #06B6D4, 0 0 12px rgba(6, 182, 212, 0.25)`
- **Corridor Failure**: `0 0 0 1px #EF4444, 0 0 16px rgba(239, 68, 68, 0.3)`
- **Telemetry Sparklines**: Semi-transparent vertical gradients beneath charts transitioning from `rgba(6, 182, 212, 0.2)` at the peak down to `rgba(6, 182, 212, 0)` at the baseline.

## Shapes

The design system enforces a **Soft Technical (Level 1)** geometric discipline. Radii are strictly bounded to maintain an engineered, hardware-like appearance without sharp, aggressive points.

### Radius Conventions
- **Data Cards, Panels & Metric Blocks**: `0.25rem` (4px). Clean, technical, and space-efficient.
- **Interactive Buttons & Form Fields**: `0.25rem` (4px).
- **Badge Pills, State Indicators, Live Counters**: Fully rounded pill shapes (`9999px`) to create an unmistakable shape-level contrast against the rectilinear layout grid.
- **Modal Dialogs & Floating Command Palettes**: `0.5rem` (8px).

## Components

### Buttons
- **Primary / Action Trigger**: Background `#06B6D4`, text `#0A0F1D` (bold Inter), font size `0.875rem`. Hover shifts to `#38BDF8` with a `0 0 12px rgba(6, 182, 212, 0.4)` glow.
- **Secondary / Operational**: Background `#1E293B`, border `1px solid #334155`, text `#F8FAFC`. Hover shifts background to `#334155` and border to `#06B6D4`.
- **Destructive / Halt**: Background `rgba(239, 68, 68, 0.1)`, border `1px solid #EF4444`, text `#EF4444`. Hover fills with `#EF4444` and text shifts to `#FFFFFF`.

### High-Density Data Cards
- Container background `#0F172A`, bordered with `1px solid #334155`.
- Header section features an uppercase `label-sm` tracking label in `#94A3B8`, an adjacent real-time heartbeat dot (`6px` circular badge), and an optional countdown timer.
- Metric values rendered in `JetBrains Mono` (`metric-display`) in `#F8FAFC`, paired with a compact trend badge (emerald `#10B981` or rose `#EF4444`).

### Telemetry Charts & Sparklines
- Chart baselines use `#1E293B` dotted grid lines with interval markings in `label-sm`.
- Main transaction velocity line drawn with a `2px` stroke in `#06B6D4`, supported by an area gradient fill fading to zero opacity at the baseline.
- Real-time scrubber displays precise timestamp and value in a floating `#0F172A` tooltip bordered by `#06B6D4`.

### Badge Pills & Status Markers
- Compact height (`20px`), pill-rounded (`9999px`), padding `0 8px`.
- Monospace font (`JetBrains Mono`, `0.6875rem`, weight 500).
- Background colors use `10%` alpha of their semantic color, paired with a solid `1px` border at `40%` alpha:
  - **Healthy**: Background `rgba(16, 185, 129, 0.12)`, border `#10B981`, text `#34D399`.
  - **Warning**: Background `rgba(245, 158, 11, 0.12)`, border `#F59E0B`, text `#FBBF24`.
  - **Failure**: Background `rgba(239, 68, 68, 0.12)`, border `#EF4444`, text `#F87171`.

### Data Tables & Transaction Logs
- Row height: Fixed `36px` for maximum informational throughput.
- Header row: Background `#0A0F1D`, borders top and bottom `1px solid #334155`, text `label-sm` in `#94A3B8`.
- Alternating rows: Subtle striping using `#0F172A` and `#131D31`.
- Hover state: Row highlight `#1E293B` with a left border accent (`2px solid #06B6D4`).

### Countdown Timers & Latency Tickers
- Rendered in `JetBrains Mono`.
- Uses a decaying ring or bar indicator with a `2px` line gauge that transitions color from `#06B6D4` down to `#F59E0B` as timeouts or refresh windows approach zero.

### Inputs & Filters
- Background `#0A0F1D`, border `1px solid #334155`, text `#F8FAFC`, placeholder `#475569`.
- Focus state: Outline border `#06B6D4` with zero displacement halo `0 0 0 1px #06B6D4`.