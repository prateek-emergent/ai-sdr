"""Words the voice says wrong, rewritten in the text stream just before it reaches the voice (SDRAgent.tts_node).

Per language, from TTS_PRONUNCIATIONS_IT / _EN ({"written": "spoken"}); empty until an entry has been tested by ear
(decided 20 Oct). Works for every voice in the chain, the fallback included. Only whole words are replaced (a short
entry like "AI" must never touch "mai" or "said"), and the transcript the person reads keeps the written form."""
from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator


class Pronunciations:
    def __init__(self, table: dict[str, str] | None = None):
        self.table = {k.lower(): v for k, v in (table or {}).items() if k.strip()}
        self.pattern = (re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(self.table, key=len, reverse=True))
                                   + r")\b", re.IGNORECASE) if self.table else None)

    def __bool__(self) -> bool:
        return self.pattern is not None

    def apply(self, text: str) -> str:
        if self.pattern is None:
            return text
        return self.pattern.sub(lambda m: self.table[m.group(0).lower()], text)

    async def stream(self, chunks: AsyncIterable[str]) -> AsyncIterator[str]:
        """Rewrite a streamed reply. A word can arrive split across chunks ("Emer" + "gent"), so the text after the
        last space waits for the next chunk; at most one word is held back."""
        pending = ""
        async for chunk in chunks:
            pending += chunk
            cut = max(pending.rfind(" "), pending.rfind("\n"))
            if cut < 0:
                continue
            ready, pending = pending[:cut + 1], pending[cut + 1:]
            yield self.apply(ready)
        if pending:
            yield self.apply(pending)
