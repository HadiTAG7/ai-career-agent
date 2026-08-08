# AI Career Agent — Hadi Alghanim design specification

## Source of truth

- Claude Design project: `https://claude.ai/design/p/2486410c-d660-42d7-8a9a-44c4dab10dcb`
- Bound library: `Hadi Alghanim Design System`
- Dark desktop dashboard: `docs/design/concepts/dashboard-field-guide-desktop-v2.png`
- Light desktop dashboard: `docs/design/concepts/dashboard-field-guide-light-desktop.png`
- Mobile dashboard: `docs/design/concepts/dashboard-field-guide-mobile.png`
- Dark desktop resume: `docs/design/concepts/resume-proofing-studio-desktop-v2.png`
- Light desktop resume: `docs/design/concepts/resume-proofing-studio-light-desktop.png`
- Mobile resume: `docs/design/concepts/resume-proofing-studio-mobile.png`

The existing routes, user data, API states, privacy gates, copy, and workflow remain authoritative. Concept-only sample people, jobs, contact details, and metrics must never replace real application state.

## Visual direction

The product is an Arabic-first, high-trust career workspace built around one metaphor: a living field guide and evidence-backed editorial dossier. It is a real product surface, not a marketing page, a financial dashboard, or an AI-chat template.

The dark theme is the primary Hadi environment. The light theme is a deliberate mineral-paper editorial variant, not a mechanical inversion. Both themes preserve the same layout, density, hierarchy, and semantic use of color.

### Core tokens

| Role | Dark | Light |
| --- | --- | --- |
| Background | `#080C16` | `#F5F2EA` |
| Surface | `#0B111E` | `#FFFEFB` |
| Raised surface | `#0E1525` | `#FFFFFF` |
| Foreground | `#F8FAFC` | `#0A1324` |
| Secondary foreground | `#DBE6F0` | `#27364C` |
| Muted foreground | `#7588A3` | `#5B6C82` |
| Border | `#20283C` | `#CBD2DC` |
| Control border | `#5B6C8E` | `#95A1B2` |
| Primary gold fill | `#F8C630` | `#F8C630` |
| Gold text/line | `#F8C630` | `#8A6400` |
| Primary foreground | `#080C16` | `#0A1324` |
| Verified emerald | `#1CCE5E` | `#008A67` |
| Destructive | `#F16F79` | `#B4232F` |

The resume document canvas is always true white (`#FFFFFF`) with dark document ink (`#172033`). In light mode it remains distinct from the mineral-paper app canvas. Do not add glow or gradients.

### Typography and icons

- Arabic: Noto Sans Arabic, 400–700.
- English: Inter, 400–700.
- Headings are compact and confident; controls, tables, inspectors, and chat chrome use an explicitly smaller type scale.
- Icons use the existing Lucide family with a consistent 1.6–1.8 stroke and no filled/outline mixing except selected mobile navigation.

## Container and component model

- Use open layouts, hairline rules, rails, ledgers, lists, tables, timelines, and a document canvas. A drawer or proof strip may be bordered only when it has a real interaction role.
- Avoid default bento grids, nested cards, decorative pills, fake charts, and filler metrics.
- Shared families: square-edged primary/secondary/danger/ghost actions, ruled fields, chapter navigation, data annotations, evidence route, ledger rows, editorial tabs, proof strips, dialogs, and drawers.
- Default radius is `0–8px`; editorial regions and rows use no radius. Borders are 1px hairlines, elevation is reserved for the physical résumé paper, and focus uses the system primary color.
- Gold is reserved for primary actions, active navigation, current steps, selected controls, and focus. Emerald denotes verified evidence or success, not generic calls to action.

## Shell contract

Desktop navigation is a narrow right chapter index in this exact order: نظرة عامة، السيرة الذاتية، مساري، الملف المهني، الفرص، التقديمات، المستندات، الإعدادات. Only the active chapter receives a large number and gold rule; inactive chapters remain compact. Mobile uses a top chapter strip (`01 / 08`) and a menu drawer, not a bottom tab bar. Arabic defaults to RTL and English to LTR.

The top bar contains the brand, AR/EN control, authentication/development state, account/notification controls, and an accessible sun/moon theme control. Theme choice persists locally; absent a saved choice, system preference is used without a hydration flash.

## Primary-screen contract

### Dashboard

Preserve `مساحتك المهنية`, the live summary, horizontal evidence route, four real typographic annotations, opportunities ledger/table, application timeline, and marginal evidence promise. The route is level and documentary, never a rising chart. Never invent metrics or opportunities when the backend returns none.

### Resume workspace

Desktop is an Editorial Proofing Studio: a dominant light document canvas, a slim folio/version rail, numbered AI marginalia connected directly to selected sentences, an evidence ledger, and a ruled command strip. AI guidance must not become chat bubbles or a generic chatbot panel. Mobile uses `السيرة` and `الهوامش` editorial tabs, a contextual proof strip, a horizontal folio rail, and sticky document actions. Preserve three stages, autosave, selection commands, before/after rewrite review, accept/reject, version restore, language choice, PDF preview, and the reviewed-information gate before download.

## Responsive behavior

- Desktop concept target: 1440px wide.
- Mobile concept target: 390px wide with safe-area padding and 44px minimum targets.
- The chapter index collapses to the top chapter strip and menu drawer; no bottom navigation is introduced.
- Dense tables become scoped horizontal regions or compact rows; they do not become unrelated card grids.
- Resume panels become segmented views while retaining the current draft, selection, and pending AI state.

## Copy and functional lock

Existing localized copy is authoritative. Do not introduce a hero, marketing claims, decorative badges, fit guarantees, or provider-generated facts. Requirements must be reviewed before a job match appears. PDF download remains disabled until the user confirms review. API failures remain fail-closed. Contact data is not sent to the AI provider.
