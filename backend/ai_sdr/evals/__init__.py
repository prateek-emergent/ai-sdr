"""Giulia's improvement loop (20 Oct: "we need some kind of self-improvement cycle"), Cekura's loop rebuilt on what
this project already runs, for free:

1. grade   every call, real or test, is graded after it ends: a judge model checks it against what a good call
           sounds like (rubric.py), plus counted checks that need no model. Scores go into the call report and,
           when tracing is on, to Langfuse next to the call's trace (watch.py, started by the web backend).
2. simulate  scripted customers (scenarios.py) played by a model talk to the real agent, prompt and tools in text
           mode (no audio, the fake calendar), and every simulated call is graded the same way (simulate.py).
3. improve a model reads the failures, proposes one change to both prompts, and the scenarios run again on the old
           and the new prompt; the report says whether the change helped (improve.py). A person decides: nothing
           is applied to the repo without --apply, and nothing reaches the pod without the usual commit and pull.

Voice-level problems (latency, interruptions, pauses) are not simulated here: they come from the call reports of real
and scripted voice calls, which carry the timings, and they are graded from those."""
