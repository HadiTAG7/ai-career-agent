# AI Career Agent design system

This file turns the approved dashboard and job-analysis concepts into implementation constraints. The concept PNGs in this directory remain the visual source of truth.

## Direction

- Arabic-first, right-to-left product UI with an immediate Arabic/English switch.
- True white canvas (`#ffffff`), deep ink text (`#102a43`), emerald action color (`#07845c`), cool gray rules (`#d9e2ec`), and amber only for actionable gaps (`#f59e0b`).
- Open workspaces, rows, rails, and dividers. Cards are reserved for a single summary, evidence detail, or form boundary.
- No gradients, glow, glass effects, cream backgrounds, decorative pills, mass-apply controls, or interview probability.

## Typography

- Arabic content and chrome: `Noto Sans Arabic`, then system Arabic fallbacks.
- Latin content and chrome: `Inter`, then system sans-serif fallbacks.
- Page title: 32/42 desktop, 28/40 mobile, weight 700.
- Section title: 20/30, weight 700.
- Body: 15/26, weight 400.
- UI controls: 14/22, weight 600. Never rely on browser-default control typography.
- Captions: 12/20, weight 500, muted ink.

## Geometry and spacing

- Desktop navigation rail: 244 px on the right; supporting evidence rail: 320 px when present.
- Main gutters: 32 px desktop and 20 px mobile.
- Spacing scale: 4, 8, 12, 16, 24, 32, 48.
- Functional radii: 8 px controls, 12 px summary/form frames, fully round only for avatars and circular progress.
- Borders: 1 px cool gray. Shadows are rare and subtle.
- Minimum interactive target: 44 by 44 px.

## Core components

- `AppShell`: quiet top bar, right navigation on desktop, fixed bottom navigation on mobile.
- `LanguageSwitch`: two-option segmented control with no decorative label.
- `JobRow`: title/location, requirement coverage, source/freshness, recommendation, evidence affordance.
- `EvidenceProgress`: verified percentage plus incomplete fact groups; it never implies employability.
- `DecisionSummary`: requirement coverage, readiness band, confidence, and recommendation.
- `RequirementRow`: requirement, status, mapped evidence, and expandable provenance.
- `EvidenceDrawer`: source, verification status, correction action, and unsupported-claim state.
- `ApplicationStageRail`: saved, ready, applied, interview; counts are user-confirmed.
- `StickyActionBar`: generate tailored CV, save, and open original application page.

## Status semantics

- Confirmed/supported: emerald.
- Partial or needs improvement: amber.
- Unsupported/blocking: red, always paired with text and an icon.
- Unknown/insufficient data: neutral slate, never treated as failure.
- Readiness uses `low | medium | high`; it must never render a numeric interview probability.

## Above-the-fold copy lock

- `AI Career Agent`
- `صباح الخير` / `Good morning`
- `هذه أهم الخطوات التي ترفع جودة بحثك اليوم.` / `These are the highest-impact steps for your search today.`
- `حلّل وظيفة جديدة` / `Analyze a new job`
- `ملفك موثّق بنسبة 82%` / `Your profile is 82% verified`
- `أفضل الفرص لك` / `Best opportunities for you`
- `تحتاج انتباهك` / `Needs your attention`

Do not add marketing claims, an eyebrow, fake proof, or a secondary CTA above the fold.

## Responsive rules

- At widths below 900 px, remove the desktop rail and show the four essential destinations in the bottom navigation.
- Job table columns collapse into open stacked rows; source details move under the title and recommendation remains visible.
- The evidence drawer becomes a sheet or inline accordion.
- Sticky actions remain reachable above the mobile navigation and respect safe-area insets.

## Motion and accessibility

- Use 140–180 ms color/border transitions and a short accordion height/opacity transition.
- Disable nonessential motion under `prefers-reduced-motion`.
- Keep focus rings visible in emerald with an outer white offset.
- Do not convey verification, gaps, or unsupported claims through color alone.
