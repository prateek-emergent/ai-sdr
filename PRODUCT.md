# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **The Talk page (`/`)** is used by Emergent's own team (sales and product) only. They practise and test calls with Giulia from a laptop browser, in Italian or English. Customers never see this page; they only ever receive phone calls. (Confirmed by Prateek on 2026-10-20.)
- **The `/calls` page** is for the same team. They review call reports, transcripts and per-turn latency. It is protected by a debug token, because transcripts are customer data.
- **The people Giulia calls** are existing Emergent.sh customers, the heaviest spenders first, starting with Italy. They hear her voice but never see the interface.

## Product Purpose

Giulia is Emergent.sh's AI SDR, a voice agent built on LiveKit with an STT → LLM → TTS pipeline.

- **What she does on a call:** she phones existing customers to ask how Emergent is working for them: what they build, what problems they solve, and what they want next. She gauges their intent and, for the right customers, books a free call with the product team.
- **Her role:** she is the first filter.
- **Success:** honest feedback is captured, the right customers reach the product team, and nobody is pushed.

The Talk page lets the team start a fresh call with Giulia in one click. They hear her, follow the live transcript, and see what she did: calendar checks, bookings, callbacks, do-not-call. A finished call's report lands on `/calls`.

## Positioning

Giulia knows the account before she dials. A customer card pulled from HubSpot shapes the call, and it is split into what she may say aloud and background she must never say. She never speaks numbers.

She works in Italian and English and can switch language mid-call. Every prompt change lands in both languages.

## Operating Context

- **Each test:** the team runs it from a browser with a microphone. Every call opens a fresh LiveKit room, and Giulia speaks first.
- **Languages:** Italian is the customer language; English is mandatory for testing and refining.
- **Code changes:** they flow from the local repo to GitHub (`prateek-emergent/ai-sdr`), and the Emergent job pulls them into the preview pod. Code is never edited on the pod.
- **Decisions:** `decisions.md` records each decision and the reason for it, with a revert line for settings whose effect is unproven.

## Capabilities and Constraints

- **Talk page:**
  - Before a call: an optional first name, the call language (Italiano / English), an optional app for Giulia to ask about, and start or end.
  - Audio: "Tap to hear Giulia" when the browser blocks audio.
  - Live transcript: the caller's drafts are dimmed until the final version arrives.
  - Actions: "What Giulia did" is fed by the `sdr.events` data topic.
  - Errors: shown for a blocked microphone, Giulia failing to join, and a failed start.
  - Reporting: browser-side events are posted to `/api/client-events` for the call report.
- **Stack:** React 19 (Create React App via craco), `@livekit/components-react` 2.9.24, `livekit-client` 2.22.0 and `lucide-react`. Tailwind is configured but unused.
- **Product claims:** Giulia may only make the claims in `backend/ai_sdr/agent/prompts/claims_*.md`, and never with numbers.
- **`/calls`:** it keeps green, amber and red latency colours, because slow turns must stand out. (Confirmed on 2026-10-20.)

## Brand Commitments

- **Names:** the agent is Giulia, Emergent's AI SDR. The company is Emergent.sh.
- **Talk page look:** minimal and monochrome (white, black and grays only), with frosted glass and blur, light and dark modes, and smooth scrolling where needed. (Pinned by Prateek on 2026-10-20.)

## Evidence on Hand

- **Nooks call analysis:** it covers 4,281 human SDR calls, and its findings are summarised in `decisions.md`. Raw call summaries live in HubSpot, and recordings are on Drive.
- **Not available:** there are no customer testimonials, logos or metrics for use in the interface, and none may be invented.

## Product Principles

1. **Feedback first, sale second.** Giulia listens and filters; the meeting is for customers worth the product team's time.
2. **Account-aware, never creepy.** Account data shapes the call, but amounts and other numbers are never spoken.
3. **Both languages are first-class.** A fix lands in Italian and English, or it isn't done.
4. **The test page is an instrument.** Within seconds, a tester can see what she heard, what she said, what she did and what failed.
5. **Reversible by default.** Uncertain changes ship in their own commit, with a revert line in `decisions.md`.
