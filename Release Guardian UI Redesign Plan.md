# Release Guardian UI Redesign Plan

Nov 8, 2026 · @Jawahiir

The Release Guardian frontend is small enough to rebuild rather than patch: about 250 lines of UI code, one 50-line stylesheet, and a single 10-line Button component.

The whole signed-in app is one 200-line `AuthenticatedApp` component that renders health, org switcher, forms, integrations, projects, events and deliveries on one page. The sidebar links (Overview, Projects, Activity) point to nothing, and only Integrations is styled as active. Tailwind and shadcn/ui are in the spec's stack but are not actually used.

## Design-system problems

There is no design system: every color, size and space is a one-off value written straight into the CSS.

- Hex values such as `#0f172a`, `#111827` and `#1e293b` are hardcoded throughout `styles.css`, with no tokens.
- The light theme is a single `@media` line that only partly overrides the dark one, so light mode is half-broken.
- Spacing is arbitrary (11px, 14px, 18px, 36px, 58px) and type sizes are ad hoc.
- There is one flat blue accent and no semantic colors for success, warning or error.
- `Button` is a thin wrapper around CSS classes, with no sizes, loading state or destructive variant.
- Every dependency in `package.json` is pinned to `latest`, which risks surprise breakage.

## UX problems

Nothing on the page has hierarchy, so the one thing a release tool must answer, whether something is failing right now, is a tiny pill.

- Every section is the same card at the same weight, and there is no routing between pages.
- Events show raw `event_type` strings and truncated SHAs, with no link to the pipeline and no detail view.
- Delivery statuses "failed" and "pending" share the same gray pill.
- Secret replacement and project registration give no confirmation or toast, though the spec requires both.
- Forms sit permanently on the page instead of in dialogs or drawers.
- The spec's core idea, separating observed facts from AI hypotheses and unknowns, has no visual language.
- On mobile the nav collapses to bullet characters.

## Proposed direction

The tool is checked during incidents, so it should feel calm, dense and trustworthy: Linear meets the Vercel dashboard, with near-black neutral surfaces and status color used only for status.

- **Color:** a 10-step neutral scale, one indigo or violet accent, and semantic green, amber, red and blue for pipeline states, all as CSS variables with light and dark defined together.
- **Type:** Inter for the interface and Geist Mono or JetBrains Mono for SHAs, project IDs and refs.
- **Spacing and shape:** a 4px scale, 6, 8 and 12px radii, and hairline borders instead of heavy shadows.
- **Signature element:** a fact vs. inference treatment. Facts get a solid check-style marker, AI analysis gets a dashed border and a "Hypothesis" tag, and unknowns get a muted style. This follows the spec and gives the product a recognizable look.

## Rebuild order

Start with steps 1 and 2, because every later screen sits on the foundation and the shell.

1. **Foundation:** pin dependency versions, add shadcn/ui properly with tokens in Tailwind, set up fonts, and wire light and dark switching.
2. **App shell:** real routing (TanStack Router or React Router), sidebar, and a top bar with the org switcher and a worker-health dot, as the spec lays out.
3. **Overview page:** active failures first, then health stats, latest events and recent deliveries.
4. **Projects:** a table with status and last poll, plus a detail page.
5. **Activity and event detail:** the fact, hypothesis and evidence layout.
6. **Integrations:** cards with masked-secret state, drawers for add and rotate, confirmations and toasts.
7. **Login, empty, loading and error states, and a mobile pass.**

## Open decision and constraints

One choice is still open: a dark-first ops console as described above, or a warmer, light-first look closer to Notion or Stripe.

- Repo access is read-only, so changes are made in a local copy and handed over as modified files or a patch to apply.
- The token set and app shell get built first, once the direction is chosen.
