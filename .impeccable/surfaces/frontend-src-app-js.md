---
version: 1
slug: "frontend-src-app-js"
primary_target: "frontend/src/App.js"
related_targets: ["frontend/src/App.css","frontend/public/index.html"]
---

# Talk to Giulia (`/`)

## Scope

- **Mode:** Operate. This is a working test console for Emergent's team; customers never see it.
- **Job:** start a call in Italian or English (optionally with a name and an app for her to ask about), hear Giulia open, talk, and judge three things: what she heard, what she said, and what she did.
- **Must stay:**
  - every current control and message
  - the client-event reporting
  - the drafts shown as "not final yet" until the final transcript arrives
  - the "Tap to hear Giulia" fallback
- **Out of scope:** `/calls` keeps its own look and its latency colours.

## Direction contract

**THESIS:** A monochrome glass call console. The conversation is the content, and the glass has a job: frosted panes sit over two discs, one on each speaker's side, that answer whoever is talking. It refuses the category default: a coloured chat app with a neon voice orb, or a dashboard of cards.

**OWN-WORLD:**
- **Colour:** strict neutrals from #000 to #fff, with no tint.
- **Ground:** #f0f0f0 in light mode and #0a0a0a in dark.
- **Panes:** translucent, with a 28px backdrop blur, a 1px hairline, an inner top highlight and a soft offset shadow.
- **Buttons:** the primary is filled with ink; secondary actions use a hairline.
- **Transcript:** your lines are ink-filled and Giulia's are frosted. Your draft is a dashed outline that fills in when it becomes final.
- **Type:** the platform UI face (the `system-ui` stack: SF Pro on the team's Macs, Segoe UI Variable on Windows) at 400, 500 and 600, with tabular times. Reason: this is a working tool on the team's laptops, there is nothing to load, and the native face sits naturally beside the glass.
- **Icons and corners:** Lucide icons at a 1.75 stroke. Corners are 20px on panes, 12px on controls, and full pills.

**STORY:** A teammate:
1. picks the language and starts the call;
2. hears her open (when the browser blocks audio, "Tap to hear Giulia" is the primary action);
3. reads her turns, their own drafts settling into finals, and her actions as they land, in full.

A blocked microphone or a failed join is impossible to miss. Ending the call leaves the transcript there to review.

**FIRST VIEWPORT:**
- **Top bar:** "Talk to Giulia" with "Emergent's AI SDR", then a Calls link (opens in a new tab) and the theme toggle.
- **Console:** one full-height frosted console below it, with a 69px control bar:
  - idle: name · Italiano/English · app · Start talking
  - live: status dot, timer and language · Tap to hear (only while audio is blocked) · End call
- **Body:** the transcript on the left, which scrolls, sticks to the latest line and shows a "Latest" pill when the reader scrolls up, and the "What Giulia did" rail at 300px on the right. On phones the layout is one column, with the rail below.
- **Signature, the voice light:**
  - Two crisp discs with hairline rings sit across the console's corners: Giulia's at the top left, yours at the bottom right.
  - They are sharp outside the glass and frosted behind it, and that contrast is what makes the glass legible.
  - Each swells with its live audio level (scale up to 12%, plus opacity).
  - In dark mode they are lights that brighten. In light mode they are shadows that deepen, because a light disc under 42% white glass would not show.
  - They hold still when idle. Under reduced motion they change opacity only, from a resting value of 0.4.
- **Motion:** state changes take 180ms with an ease-out, new lines rise 4px over 220ms, and the status dot breathes while she listens and ripples while she speaks.

**FORM:** monochrome frosted glass, pinned by Prateek on 2026-10-20, with the conversation-first layout he chose in the confirmation round. No concept roll was run, because the brief pinned the palette, the material and the layout, and a pinned direction beats the roll.
seed: none (direction pinned by user; roll not run)

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- There is no "follow system" option once a theme is picked by hand; the toggle remembers the choice per browser.
- The voice-level gate (0.08) and gain (×3) are estimates. Tune them on real calls if a disc sits fully swollen during silence, or barely moves.
