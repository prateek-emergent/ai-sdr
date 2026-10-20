---
name: Talk to Giulia
description: A monochrome frosted-glass call console where Emergent's team tests Giulia, the AI SDR, in light and dark.
colors:
  # Light mode: declared on .talk (frontend/src/App.css)
  ink: "#0b0b0b"
  ink-hover: "#2a2a2a"
  on-ink: "#fafafa"
  ground: "#f0f0f0"
  ink-2: "#3d3d3d"
  ink-3: "#575757"
  glass: "rgba(255, 255, 255, 0.42)"
  glass-solid: "#f3f3f3"
  sheen: "rgba(255, 255, 255, 0.5)"
  raised: "rgba(255, 255, 255, 0.78)"
  chip: "#ffffff"
  edge: "rgba(0, 0, 0, 0.07)"
  shine: "rgba(255, 255, 255, 0.85)"
  hairline: "rgba(0, 0, 0, 0.08)"
  hairline-strong: "rgba(0, 0, 0, 0.18)"
  wash: "rgba(0, 0, 0, 0.045)"
  thumb: "rgba(0, 0, 0, 0.2)"
  light-her: "#d4d4d4"
  light-you: "#bcbcbc"
  ring: "rgba(0, 0, 0, 0.09)"
  # Dark mode: the same tokens redefined on html[data-talk-theme="dark"] .talk; key = light name + "-dark"
  ink-dark: "#f4f4f4"
  ink-hover-dark: "#d9d9d9"
  on-ink-dark: "#0b0b0b"
  ground-dark: "#0a0a0a"
  ink-2-dark: "#b8b8b8"
  ink-3-dark: "#9a9a9a"
  glass-dark: "rgba(16, 16, 16, 0.45)"
  glass-solid-dark: "#161616"
  sheen-dark: "rgba(255, 255, 255, 0.05)"
  raised-dark: "rgba(255, 255, 255, 0.07)"
  chip-dark: "rgba(255, 255, 255, 0.14)"
  edge-dark: "rgba(255, 255, 255, 0.08)"
  shine-dark: "rgba(255, 255, 255, 0.07)"
  hairline-dark: "rgba(255, 255, 255, 0.09)"
  hairline-strong-dark: "rgba(255, 255, 255, 0.2)"
  wash-dark: "rgba(255, 255, 255, 0.055)"
  thumb-dark: "rgba(255, 255, 255, 0.22)"
  light-her-dark: "#262626"
  light-you-dark: "#1a1a1a"
  ring-dark: "rgba(255, 255, 255, 0.07)"
typography:
  title:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  transcript:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  body:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  body-strong:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "14px"
    fontWeight: 500
    lineHeight: 1.5
  label:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
  small:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  caption:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.5
  meta:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: '"tnum"'
rounded:
  pane: "20px"
  bubble: "18px"
  control: "12px"
  ghost: "10px"
  segment: "9px"
  joined: "6px"
  pill: "999px"
spacing:
  "2xs": "2px"
  xs: "4px"
  sm: "8px"
  row: "10px"
  md: "12px"
  inset: "14px"
  lg: "16px"
  xl: "20px"
  gutter: "24px"
components:
  console:
    backgroundColor: "{colors.glass}"
    rounded: "{rounded.pane}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-quiet:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  nav-link:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.ghost}"
    padding: "0 10px"
    height: "36px"
  nav-link-hover:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.ink}"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.ghost}"
    size: "36px"
  icon-button-hover:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.ink}"
  input:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  segmented:
    backgroundColor: "{colors.wash}"
    rounded: "{rounded.control}"
    padding: "3px"
    height: "44px"
  segmented-option:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.body-strong}"
    rounded: "{rounded.segment}"
    padding: "0 14px"
  segmented-option-selected:
    backgroundColor: "{colors.chip}"
    textColor: "{colors.ink}"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  status-dot:
    backgroundColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    size: "10px"
  bubble-her:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    typography: "{typography.transcript}"
    rounded: "{rounded.bubble}"
    padding: "9px 14px"
  bubble-you:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    typography: "{typography.transcript}"
    rounded: "{rounded.bubble}"
    padding: "9px 14px"
  bubble-you-draft:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
  alert:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
  latest-pill:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "32px"
  action-row:
    textColor: "{colors.ink}"
    typography: "{typography.body-strong}"
    padding: "10px 0"
---

# Design System: Talk to Giulia

This file governs the Talk page (`/`) only. The `/calls` metrics page deliberately keeps its own older inline-styled look, including its green, amber and red latency colours, and nothing here applies to it.

## Overview

**Creative North Star: "The Glass Booth"**

Talk to Giulia is a call console seen through frosted glass. The conversation is the content: a teammate starts a call, hears Giulia open, and reads what she heard, what she said and what she did. Everything is monochrome, from near-black to white with no tint, so the only things that pull the eye are the lines being spoken and the one action that matters now.

The glass has a job. Behind the console sit two crisp discs with hairline rings, Giulia's across its top-left corner and yours across its bottom-right, and each swells with its speaker's live voice level. They are sharp outside the glass and frosted behind it, and that contrast is what makes the glass read as glass. In dark mode the discs are lights that brighten; in light mode they are shadows that deepen. Light and dark are equal modes: the system's choice applies until the teammate picks one with the toggle.

Density is that of a working instrument on a laptop: 14px base type, 44px controls, a 69px control bar and a console that fills the window. Motion is small and functional. State changes take 180ms on one ease-out curve (cubic-bezier(0.2, 0.8, 0.2, 1)), new lines rise 4px into place over 220ms, and only the voice moves continuously. The world refuses the category default: a coloured chat app with a neon voice orb, or a dashboard of cards.

**Key Characteristics:**
- Strict neutrals: every colour has equal red, green and blue, in both modes.
- One frosted console (28px blur) over the voice light; surfaces inside it are raised or hairlined, never frosted again.
- Ink is the action: one ink-filled button per bar, your own words in ink, errors as a solid ink block.
- State is told by shape, outline and motion, never by hue.
- The platform UI face at 400, 500 and 600, with tabular figures for every time.
- Lucide outline icons at a 1.75 stroke; 20px panes, 12px controls, full pills.

## Colors

A strictly achromatic palette: near-black ink on pale gray in light mode, near-white ink on near-black in dark, with translucency doing the work that hue does elsewhere.

Light values live on the page scope and dark values redefine the same custom properties under the dark theme attribute; in the frontmatter each dark value is the light key plus `-dark`. The theme attribute is set before first paint by an inline script in `public/index.html`, which also paints the html background with both ground values, so dark mode never flashes white.

### Primary
- **Ink** (#0b0b0b · dark #f4f4f4): the action colour and the main text colour. It fills the primary button, your finalized transcript lines, the alert, the status dot, the focus ring and text selection. In dark mode it inverts to near-white, so every ink fill becomes a light fill.
- **Ink Hover** (#2a2a2a · dark #d9d9d9): the primary button's hover fill, one step off ink.
- **On Ink** (#fafafa · dark #0b0b0b): text and icons on any ink fill; selection inside your own lines swaps ink and on-ink.

### Neutral
- **Ground** (#f0f0f0 · dark #0a0a0a): the page behind everything, and the pre-paint html background.
- **Second Ink** (#3d3d3d · dark #b8b8b8): secondary text: the subtitle, pane headings, top-bar links and segment labels at rest, the language chip, action details, draft text and empty-state copy.
- **Third Ink** (#575757 · dark #9a9a9a): tertiary text: placeholders, the timer, counts, speaker names, timestamps and the call-ended line, plus the dashed outline of a draft. It holds at least 4.5:1 on the frosted console in both modes, over the discs included.
- **Frosted Glass** (rgba(255, 255, 255, 0.42) · dark rgba(16, 16, 16, 0.45)): the console's fill under a 28px backdrop blur, and the Latest pill's under 16px.
- **Sheen** (rgba(255, 255, 255, 0.5) · dark rgba(255, 255, 255, 0.05)): a 160° gradient over the glass that fades to nothing 38% of the way across.
- **Solid Glass Fallback** (#f3f3f3 · dark #161616): the console's opaque fill where the browser cannot blur.
- **Raised Fill** (rgba(255, 255, 255, 0.78) · dark rgba(255, 255, 255, 0.07)): surfaces inside the console: inputs, the quiet button and Giulia's lines. A near-opaque milk in light mode, a faint lift in dark.
- **Selected Segment** (#ffffff · dark rgba(255, 255, 255, 0.14)): the chosen language in the segmented control, and nothing else.
- **Glass Edge** (rgba(0, 0, 0, 0.07) · dark rgba(255, 255, 255, 0.08)): the 1px border of glass surfaces.
- **Shine** (rgba(255, 255, 255, 0.85) · dark rgba(255, 255, 255, 0.07)): the 1px inner top highlight on glass and on the selected segment.
- **Hairline** (rgba(0, 0, 0, 0.08) · dark rgba(255, 255, 255, 0.09)): every divider and resting border: the control bar's bottom rule, the rail's side rule, the rules between actions, and the borders of inputs, chips and Giulia's lines.
- **Strong Hairline** (rgba(0, 0, 0, 0.18) · dark rgba(255, 255, 255, 0.2)): the hover border of inputs and the quiet button.
- **Wash** (rgba(0, 0, 0, 0.045) · dark rgba(255, 255, 255, 0.055)): the segmented track, and the hover fill of the top-bar controls.
- **Scroll Thumb** (rgba(0, 0, 0, 0.2) · dark rgba(255, 255, 255, 0.22)): the thin scrollbar thumb.
- **Giulia's Disc** (#d4d4d4 · dark #262626) and **Your Disc** (#bcbcbc · dark #1a1a1a): the voice light. Darker than the ground in light mode, lighter in dark mode.
- **Disc Ring** (rgba(0, 0, 0, 0.09) · dark rgba(255, 255, 255, 0.07)): the two hairline rings around each disc.

### Named Rules
**The Zero Chroma Rule.** Every colour on this page has equal red, green and blue. There is no tint in the grays, no blue link, no green success and no red error. When something must stand out, it gets more ink, not a hue.

**The Ink Is the Alarm Rule.** The loudest thing this world can do is a solid block of ink. A blocked microphone, a failed join or a failed start appears as an ink-filled alert at the top of the console (a light block in dark mode), never as red.

**The Twin Token Rule.** Every colour token is defined twice, once for light and once for dark. A token with one value is unfinished. Shadows stay black in both modes; dark mode only raises their opacity.

## Typography

**Display Font:** none. The ramp tops out at 16px.
**Body Font:** the platform UI stack (ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif)
**Label/Mono Font:** the same stack; times and counts use tabular figures.

**Character:** The platform UI face: SF Pro on the team's Macs, Segoe UI Variable on Windows. It was chosen because this is a working tool on the team's laptops: there is nothing to load, and the native face sits naturally beside the glass. Hierarchy comes from three weights (400, 500, 600) and the three inks across a tight 12 to 16px range, not from size. The shared `public/index.html` also loads Inter 600, but only `/calls` uses it.

### Hierarchy
- **Title** (600, 16px, 1.5, -0.01em): the page name in the top bar. The empty-state lead uses the same size and tracking at 500.
- **Transcript** (400, 15px, 1.45): the words in the bubbles, the largest reading text on the page because the conversation is the content. Lines run to at most 64ch. The live status line uses this size at 500.
- **Body** (400, 14px, 1.5): the base: inputs, the alert, empty-state copy and the timer.
- **Body Strong** (500, 14px, 1.5): anything pressed or scanned: buttons, top-bar links, segment labels and action labels.
- **Label** (500, 13px, 1.5): pane headings ("Live transcript", "What Giulia did") in second ink, and the Latest pill.
- **Small** (400, 13px, 1.5): the subtitle beside the page name and the detail line under an action.
- **Caption** (500, 12px, 1.5): speaker names above a run of lines, and the language chip.
- **Meta** (400, 12px, 1.5, tabular figures): timestamps, counts and the call-ended line.

Parts of one line are joined with a spaced middle dot ("Call ended · 0:03", "billing · Credits run out quickly").

### Named Rules
**The Platform Face Rule.** The page uses the platform UI stack and loads no font of its own. It is a UI face for a working tool, not a display face: nothing is set larger than 16px, and a surface that wants a display voice needs a new type decision, not a bigger system font.

**The Tabular Time Rule.** Every time, duration and count is set in tabular figures, so a ticking timer and a column of timestamps never jitter.

## Layout

The page is a centred column: a 60px top bar with one console below it, both capped at 1120px wide, with a 24px gutter on the sides and bottom (16px on phones). The console fills the rest of the window (100dvh minus 84px, never under 520px) and scrolls inside itself, so on a laptop-height window the page itself never scrolls.

Inside the console, an alert (when there is one) sits inset 12px, then the control bar (at least 69px tall, 12px padding, a hairline below), then two panes. The transcript takes all the remaining width; the "What Giulia did" rail is fixed at 300px behind a hairline. Pane headings sit 16px from the top with a 20px inset, and pane content keeps the 20px inset. Transcript lines stack from the bottom with 3px between lines from one speaker and 14px before a new speaker. Each line runs to at most 78% of the pane or 64ch, Giulia's on the left and yours on the right.

When idle, the control bar is two rows (since 20 Oct, when the model picker joined the voice picker), 8px apart: name (1fr), app (1fr) and language (auto) above; voice (1fr), model (1fr) and Start talking (auto) below. When live, it holds the call status on the left and the actions on the right.

- **At 960px and below,** the two setup rows stay as they are.
- **At 760px and below,** the console becomes one column with the rail under the transcript (a hairline above it) and grows with its content. The transcript scrolls at 56dvh and the rail at up to 40vh, the gutter drops to 16px, and the live actions span the full width.
- **At 600px and below,** the setup stacks one control per row (name, language, voice, model, app, Start talking), the two language segments split the width evenly, and lines may run to 88%.

The voice light tracks the console at every width. Each disc is placed from the console's side inset (the larger of 24px and half the window minus 560px). Giulia's disc is min(40vmax, 620px) across, centred 40px inside the console's left edge and 100px from the top. Yours is min(34vmax, 540px), centred 30px inside the right edge and 84px from the bottom.

Spacing sits on a 2px grid with recurring steps: 4px inside clusters, 8px between controls, 10px inside rows and chips, 12px of bar padding, 14px of horizontal inset inside controls and bubbles, 20px of pane inset and a 24px page gutter.

### Named Rules
**The Conversation First Rule.** The transcript always gets the width the 300px rail leaves, and on phones the rail goes under it. The control bar is the only thing above the conversation.

## Elevation & Depth

Depth is one material plus soft shadow. The console is the only real layer: a frosted pane (28px backdrop blur, 1px glass edge, 1px inner top highlight) lifted by a long, soft shadow that falls below it. Everything inside it sits flat on the glass and separates by hairline and fill, with two exceptions: the primary button carries a short button shadow, and the selected language segment a 1px lift. The Latest pill floats over the scrolling transcript as a small glass pill (16px blur) with the button shadow. The voice light is the deepest layer, behind everything.

### Shadow Vocabulary
- **Pane** (light `box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 32px 64px -32px rgba(0, 0, 0, 0.3)`; dark `0 1px 2px rgba(0, 0, 0, 0.4), 0 32px 64px -32px rgba(0, 0, 0, 0.9)`): the console only, always paired with the Shine highlight `inset 0 1px 0`.
- **Button** (light `box-shadow: 0 1px 2px rgba(0, 0, 0, 0.16), 0 10px 22px -12px rgba(0, 0, 0, 0.5)`; dark `0 1px 2px rgba(0, 0, 0, 0.5), 0 10px 22px -12px rgba(0, 0, 0, 0.8)`): the ink-filled primary button and the Latest pill.
- **Segment lift** (`box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12), inset 0 1px 0` in Shine): the selected language segment.

### Named Rules
**The Blur Has a Job Rule.** Frost only what has something moving behind it: the console over the voice light (28px) and the Latest pill over scrolling lines (16px). Inputs, bubbles, segments and action rows inside the console are raised or hairlined, never frosted again.

## Shapes

Soft rounded rectangles on a strict ladder: 20px for the console, 18px for transcript bubbles, 12px for controls (inputs, buttons, the segmented track and the alert), 10px for the ghost controls in the top bar, 9px for the selected segment (the track's 12px minus its 3px padding), and full pills for the language chip and the Latest pill.

Lines from one speaker join on that speaker's side: the corners facing the previous or next line in the run drop to 6px, so a run reads as one turn (Giulia's join on the left, yours on the right).

Borders are always 1px: hairline at rest, strong hairline on hover, glass edge on glass. Status rings are 1.5px. Icons are Lucide outlines at a 1.75 stroke: 14px in links and the Latest pill, 16px in buttons, and 18px in the theme toggle, the alert and action rows.

### Named Rules
**The Circle Is the Voice Rule.** Circles mean voice: the status dot, its ripple and the two discs with their rings. Controls are rounded rectangles or pills, never circles.

**The Dashed Means Draft Rule.** A dashed outline means "not final yet": your words as heard so far. It is used for nothing else.

## Components

Component tokens in the frontmatter use the light names. In dark mode each reference resolves to its `-dark` twin, which the CSS does by redefining the same custom properties.

### Buttons
Firm and quiet, 44px tall.
- **Shape:** gently rounded (12px), 18px side padding, 8px between a 16px icon and the Body Strong label.
- **Primary:** ink fill, on-ink label and the button shadow. On hover the fill moves to Ink Hover (180ms); on press the button drops 1px (120ms).
- **Quiet:** raised fill, a 1px hairline and an ink label; on hover the border darkens to the strong hairline.
- **Ghost (top bar):** the Calls link (36px tall, 10px padding, a 14px up-right arrow) and the theme toggle (36px square, 18px moon or sun) are transparent and second ink at rest, and take the wash and ink on hover. Corners are 10px.
- **Focus:** a 2px solid ink ring, offset 2px, on everything focusable.

**The One Ink Button Rule.** A bar holds exactly one ink-filled button: Start talking when idle and End call when live. While the browser blocks audio, Tap to hear Giulia takes the ink and End call steps down to quiet.

### Chips
- **Style:** the language chip in the live status row is a full pill with a 1px hairline, no fill, 2px 10px padding and Caption type in second ink. It is a label, not a control.

### Segmented Control
The call language (Italiano / English). A 44px wash track with a hairline border, 12px corners and 3px padding, holding two options in second ink at Body Strong with 14px side padding. The selected option takes the Selected Segment fill, ink text and the segment lift; hovering an option turns its text to ink (180ms). Keyboard focus draws the 2px ink ring at a 1px offset around the option. At 600px and below the two options split the track evenly.

### Cards / Containers
- **Console:** the one container. Frosted glass (see Elevation & Depth), 20px corners, contents clipped to the corners. Inside it, sections separate by hairlines, never by nested cards. Where the browser cannot blur, it takes the Solid Glass Fallback.
- **Alert:** a solid ink block inset 12px from the console's edges, with 12px corners, 12px 14px padding, an 18px circle-alert icon 10px from the message, and on-ink text at line-height 1.45. It rises into place over 220ms.

### Inputs / Fields
- **Style:** 44px tall, 12px corners, raised fill, a 1px hairline, 14px side padding and Body type, with the caret in ink, placeholders in third ink and long values ending in an ellipsis.
- **Hover:** the border darkens to the strong hairline (180ms).
- **Focus:** the 2px ink ring, offset 2px.
- **Error / Disabled:** none. Errors are reported by the alert, not on the field.

### Navigation
A 60px top bar. On the left, the page name in Title type with the subtitle "Emergent's AI SDR" in Small, second ink, baseline-aligned 10px apart; the subtitle truncates before anything wraps. On the right, 4px apart, sit the Calls link (opens in a new tab) and the theme toggle, which shows a moon in light mode and a sun in dark.

### Call Status
The left side of the live control bar: a 10px status dot, the status line (Transcript size at 500), the timer (third ink, tabular) and the language chip, 10px apart. The dot carries the state in shape and motion, not colour:
- **Connecting, or waiting for Giulia:** a hollow 1.5px ring that blinks every 1.2s.
- **Thinking:** a solid dot blinking faster, every 0.8s.
- **Listening:** a solid dot that breathes down to 70% over 2.4s.
- **Speaking:** a solid dot with a 1.5px ring rippling out from it every 1.4s.

### Transcript
- **Giulia's lines:** raised fill, a 1px hairline, ink text, 18px corners, 9px 14px padding and Transcript type, on the left.
- **Your lines:** ink fill and border with on-ink text, on the right.
- **Your draft:** a dashed third-ink outline with no fill and second-ink text until the final transcript lands, then it fills in (a 220ms change of fill, border and colour).
- **Runs:** consecutive lines from one speaker join at 6px inner corners, and only the first line of a run carries the speaker's name (Caption, third ink).
- **Arrival:** new lines rise 4px and fade in over 220ms, and the view follows the newest line until the reader scrolls up, moving smoothly unless reduced motion is set.
- **Latest pill:** when the reader scrolls up, a 32px glass pill (16px blur, glass edge, inner highlight, button shadow) with a 14px down arrow and "Latest" in Label type floats 16px above the bottom. Pressing it returns to the newest line.
- **Call ended:** a centred Meta line ("Call ended · 0:03") between two hairlines, 22px below the last line.
- **Scroll edges:** the scroll area fades its top 12px and bottom 16px; the scrollbar is thin, with a Scroll Thumb.
- **Empty state:** centred, balanced and at most 38ch wide: a lead in Title size at 500 in ink, then Body copy in second ink.

### Action Rail
"What Giulia did" is a 300px column with a Label heading and a Meta count. Each action is a row, not a card: an 18px Lucide icon, the label (Body Strong) over an optional detail (Small, second ink), and the time (Meta, third ink) on the right. Rows have 10px of vertical padding and a hairline between them, and new rows rise into place over 220ms. When empty, the rail shows a single line in third ink.

### Voice Light
The signature. Two crisp discs fixed behind the page, each with two hairline rings (7% and 16% beyond the disc, the outer at 60% opacity), placed across the console's top-left (Giulia) and bottom-right (you) corners. Each swells with its speaker's live voice level: up to 12% larger, and from its resting opacity (0.85 for Giulia and 0.7 for you in light mode; 0.9 and 0.8 in dark) up to full, following the voice with a 160ms ease-out. They hold still when idle. Under reduced motion they never scale: only their opacity changes, from a resting 0.4, with a 0.4s linear transition. They take no pointer events and are hidden from assistive technology.

### Timing Strip
Added 20 Oct. It sits between the control bar and the panes while a call runs, and it can be closed: open by default on a laptop, closed on a phone, and the choice is remembered. It holds three things. On the left, the caller's wait as a 24px Title-weight figure with tabular digits, dashed-underlined when it is over the 1.5s target. On the right, a strip of 6px bars, one per reply, the latest in ink. Below, the flow and the waterfall.

The flow is a row of 30px nodes joined by a 1px line: dashed until a step is done, then solid. A finished step is an ink-filled disc. The step happening now is an ink ring with the Call Status ripple. A step not reached yet is a hairline ring. Tools are 9px-radius squares; people and the voice are round. Each node has a Caption label, a tabular value and, where known, the model in Meta.

The waterfall puts the same reply on one time axis, starting when you stopped talking. Each step gets its own lane:
- **Heard:** an outlined bar.
- **Turn over:** a dashed outline.
- **Thinking:** a second-ink fill, with a hatched tail up to her first sentence.
- **Voice:** an ink fill.

A dashed line marks the target and a solid ink line marks the moment Giulia became audible. It is all monochrome: state is told by fill, outline, dash and motion.

Each node's Meta line starts with the step's standard metric name (STT, EOU, TTFT, TTFB, E2E), then the model where known. Under the waterfall, the metrics row (added 20 Oct) lists the seven standard numbers in one raised, hairline-bordered 12px box split by hairlines: E2E, EOU, STT, TTFT, TTFS, TTFB and TPS. Each cell holds the abbreviation in ink at 11px with 0.05em tracking and the full name in third ink, this reply's value at 15px Title weight, and the call's p50 and p95 in third-ink Meta (for TPS, the median only). While her line still plays, E2E shows the page's own "≈" figure, the same one as the last flow node. The row is seven columns, then four at 1100px and below, then two at 600px and below.

### Quality Page
`/quality` uses the same tokens as a scrolling page of glass panels, with no fixed console. Pass, fail and n/a are told by shape:
- **Pass:** an outlined check.
- **Fail:** an ink-filled mark.
- **N/a:** a dashed ring.

A must-rule is an outlined pill when the rule held, and turns into a solid ink tag in the call list when it broke. A call opens in a right-hand drawer that is frosted but nearly opaque (90%), so the page behind never competes with the verdicts.

The speed panel (20 Oct) has seven tiles in the metrics row's order, each with the abbreviation in ink before its name, the p50 as the value and the p95 with its reply count as the note. Under them, the models table has one row per LLM, sorted by first token. The model name is Body Strong with the provider and reply count beneath it in third ink, and "fastest" marks the quickest model with enough replies. A model with too few replies to compare is greyed (third ink), not hidden. The table scrolls sideways inside its panel on a phone; the page never does.

## Do's and Don'ts

### Do:
- **Do** take every colour from the page tokens, and give each new token both values: light on the page scope, dark under `html[data-talk-theme="dark"]`.
- **Do** keep the pre-paint html backgrounds in `public/index.html`, and the theme colour the page sets, equal to Ground (#f0f0f0 light, #0a0a0a dark).
- **Do** keep exactly one ink-filled button in a bar; when a more urgent action appears, the previous primary steps down to quiet.
- **Do** tell state with fill, outline, shape and motion: a hollow dot while connecting, a dashed outline for a draft, an ink block for an error.
- **Do** use Lucide outline icons at a 1.75 stroke (14px in links and pills, 16px in buttons, 18px in the theme toggle, alerts and action rows), always beside or labelled by text.
- **Do** set every time, duration and count in tabular figures.
- **Do** keep the 2px solid ink focus ring, offset 2px (1px inside the segmented control), on everything focusable.
- **Do** honour reduced motion: stop every animation, jump instead of scrolling smoothly, and let the voice light change opacity only, from a resting 0.4.

### Don't:
- **Don't** introduce hue anywhere on the Talk page: no red errors, green success, blue links or tinted grays.
- **Don't** frost a surface that has nothing moving behind it; surfaces inside the console use the raised fill or a hairline, without blur.
- **Don't** drift back to the category default this world refuses: a coloured chat app with a neon voice orb, or a dashboard of cards.
- **Don't** set the platform face at display sizes or give this page a webfont; the type ramp ends at 16px.
- **Don't** lighten Third Ink (#575757 light, #9a9a9a dark); it is tuned to hold at least 4.5:1 on the frosted console in both modes, over the discs included.
- **Don't** carry this system onto `/calls`; that page keeps its own look and its green, amber and red latency colours.
