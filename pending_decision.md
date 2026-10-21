# Pending decisions: why Giulia's first two replies are slower

Measured on the preview pod, 21 Oct. Nothing here is built yet. Decide each one separately.

Scope of the data: the pod has 109 web calls, of which only 11 are real people. The other 98 are scripted test callers, filtered out by caller lines repeated word for word across 3+ calls. So the people numbers are directional. The LLM benchmark is solid: 6 rounds per arm, Giulia's real prompt and 14 tools, run on the pod.

## Where the time goes (real people, 11 calls)

| Reply | Whole reply | Waiting for the person to finish (share at the 1.2 s cap) | LLM first word |
|---|---|---|---|
| 1st | 2.06 s | 1.20 s (82%) | 1.05 s |
| 2nd | 1.52 s | 0.88 s (44%) | 0.84 s |
| 3rd onwards | 1.14–1.28 s | 0.42–0.58 s | 0.50–0.60 s |

Compared with the same call's later replies, reply 1 is about 1.4 s slower: roughly 0.8 s from waiting for the person and 0.5 s from the LLM. Reply 2 is about 0.3 s slower.

There are two separate causes, below.

---

## Decision 1: warm the LLM's prompt cache at call start

**The problem.** Every LLM request sends Giulia's whole prompt: 11,358 tokens covering instructions, 14 tools and the customer card. Anthropic, through LiteLLM's cache marker, keeps a copy of the start of the prompt for 5 minutes. A request that starts with exactly the same text skips re-reading it.

Within a call the instructions and tools never change, so replies 2 onwards reuse the copy. Reply 1 can't: the opener is pre-written and makes no LLM request, so reply 1 is the call's first request and reads the full prompt while the person waits.

**The proposal.** As soon as the session starts, while the opener plays (about 10 s), send one hidden background request. It carries the same instructions, tools and customer card plus a placeholder line, asks for 1 word, and throws it away. Anthropic stores the copy, and the first real reply finds it.

```
TODAY
0 s    call connects (LiveKit already opens the connection to the LLM proxy)
~1 s   opener starts: pre-written, no LLM
~10 s  person answers
~11 s  1st LLM request reads all 11,358 tokens, then stores a copy -> first word 0.80 s (slow cases 1.16 s)
later  replies reuse the copy -> first word 0.52 s

WITH WARMUP
~1 s   opener starts AND the hidden request goes out (takes ~1 s, finished long before the person speaks)
~11 s  1st real reply finds the copy -> first word 0.58 s
```

**Measured on the pod**, 6 rounds each, real prompt and tools, reply 1 sent 16 s after call start as in real calls:

| | LLM first word p50 / p90 | First sentence p50 | Tokens read from cache |
|---|---|---|---|
| Today | 0.80 / 1.16 s | 0.97 s | 0 |
| With warmup | 0.58 / 0.77 s | 0.74 s | 10,957 |
| Warmup + connection refresh | 0.56 / 0.67 s | 0.73 s | 10,957 |
| Later replies (reference) | 0.52 / 0.56 s | 0.69 s | 10,957 |

**Why the copy matches.** The hidden request would be built by LiveKit's own request builder: the agent's instructions message (`lk.agent_task.instructions`), the same tools in the same order, through the same LLM client. Its start is therefore byte-for-byte identical to the real reply's. The benchmark confirms it: 10,957 of 11,358 tokens were read from the copy.

**Why it's safe:**
- It produces no audio, adds nothing to the conversation, and doesn't change what Giulia says.
- It runs while nothing else talks to the LLM, about 9 s before the person's first words. The 20 Oct `LLM_WARM_ON_SPEECH` experiment that slowed replies fired while the caller spoke and competed with LiveKit's early (preemptive) request; this doesn't.
- It fails silently (proxy down, daily budget used up), and the call then runs exactly as today.

**Edge cases:**
- **Language switch:** the other language has a different prompt, so warm it at the switch.
- **Phone calls:** start it while the phone rings, so it's ready before "Pronto?".
- **Emergent backup route:** that route has no copy anyway, so nothing is lost.
- **Very fast first answer:** reply 1 is no worse than today.

**Cost.** The copy is written on reply 1 today anyway; the warmup writes it about 10 s earlier, and reply 1 then reads it at a tenth of the price. The extra is about $0.0015 per call, roughly $1.50 per 1,000 calls.

**Effort and test.** About 30 lines in `agent/worker.py` behind a setting (e.g. `LLM_PROMPT_WARMUP=1`), plus a unit test. A/B on the pod: call reports already record reply 1's `llm_node_ttft` and the cached tokens.

**Ruled out on the pod (not worth building):**
- *Keeping the connection alive.* The proxy keeps idle connections open for at least 90 s, a new connection costs only 0.03–0.04 s, and LiveKit already opens one at session start. The 20 Oct note "proxy drops idle connections" came from the laptop, so `LLM_WARM_ON_SPEECH` isn't needed.
- *Warming the worker process.* A fresh process's first request was as fast as its second (0.46–0.58 s vs 0.46–0.53 s).
- *LiteLLM routing.* A single deployment (`aws-external-anthropic.us-east-1`) serves Haiku, so the copy is always where reply 1 goes.

**To decide:** build it behind a setting and A/B it on the pod?

---

## Decision 2: open the call in two parts

**The problem.** The opener is one 27–30-word block, about 10 s, spoken in one go by `CallController.greet()`:

- IT: "Buongiorno Marco, sono Giulia, l'assistente AI di Emergent. La chiamo per la sua app, {app}: volevamo sapere come si sta trovando. Ha due minuti?"
- EN: "Hi Marco, it's Giulia, the AI assistant at Emergent. I'm calling about your app, {app}: we'd love to hear how it's going. Do you have a couple of minutes?"

The other versions:
- **No app known:** adds "la piattaforma per creare app con l'intelligenza artificiale", because "Emergent" is misheard as "emergency".
- **Callback:** "…la richiamo come d'accordo. È ancora un buon momento?"
- **After 17:00 their time:** "Buonasera".
- **Recording on:** a recording sentence is added.

The opener starts with a greeting, which invites a greeting back. 10 of 11 real people greeted back while Giulia was still talking: "Hello? Who's this?", "Hi, Julia. How are you?", "Yeah.". LiveKit's turn model rates those overlapping greetings as unfinished (scores 0.03–0.37 against a 0.386 threshold), so it waits the full 1.2 s. Warmup can't fix this.

**The proposal.** The same words, split in two with a pause where people naturally greet back:

| | Italian | English |
|---|---|---|
| Part 1 (~3 s) | "Buongiorno Marco, sono Giulia, l'assistente AI di Emergent." | "Hi Marco, it's Giulia, the AI assistant at Emergent." |
| pause | they say "Buongiorno!", "Sì?", "Mi dica" | "Hi!", "Yes?", "Hello?" |
| Part 2 (~5 s) | "Senta, la chiamo per la sua app, {app}: volevamo sapere come si sta trovando. Ha due minuti?" | "So, I'm calling about your app, {app}: we'd love to hear how it's going. Do you have a couple of minutes?" |

Rules for the pause:
- **A short greeting:** part 2 starts about 0.3 s after they stop. No LLM and no turn-model wait.
- **Silence:** part 2 starts after about 1.2 s.
- **Anything more** ("Un'AI?", "Chi le ha dato il numero?", "Sto guidando"): skip part 2 and let the LLM answer; it sees part 1 in the history.

The other versions split the same way:
- **No app known:** the platform description moves to the start of part 2.
- **Callback:** part 2 is "La richiamo come d'accordo: è ancora un buon momento?"
- **Recording on:** the recording sentence goes in part 2, before the question.

**Why:**
- It's how people open phone calls: greet and say who you are, pause, then the reason. A 10-second monologue is the clearest robocall signal, and the 20 Oct feedback was "it feels like talking to a bot".
- The AI disclosure stays in the first sentence (EU AI Act art. 50), and the app name stays (half the human SDRs' "no"s came at generic openers).
- The first LLM reply becomes a clean answer to "Ha due minuti?" after Giulia has finished.

**Expected effect.** Most of reply 1's extra 0.8 s of waiting should go. This is an estimate from 11 calls, so it needs test calls with real people; TTS-voiced test callers can't judge turn-taking (21 Oct finding).

**Effort and test.**
- Code: split `opener()` into two parts, and make `CallController.greet()` say part 1, wait for a short greeting or silence, then say part 2. Using the existing `GREETING` state, the greeting itself should not get its own LLM reply.
- Checks: update the prompt check and the grader's AI-disclosure check.
- Tests: 5–10 calls with real people per language.

**To decide:** OK the new script? Should the Italian part 2 open with "Senta, …"?

---

Sources: pod call reports (`call_reports`) and a pod benchmark through LiveKit's OpenAI plugin with LiteLLM prompt caching. The analysis scripts stayed in the session scratchpad, not the repo. Spend for this research: about $0.24 of the LiteLLM daily budget.
