"""The Italian and English prompts must say the same thing: a fix made in one language has to land in the other
(decided 20 Oct, when calls became bilingual). For each it/en pair this checks the same sections, the same numbered
steps and bullets, the same placeholders, the same tools and the same dispositions.

    python -m ai_sdr.agent.prompt_check      # from backend/; exits 1 on any mismatch. Run it before every push.

No dependencies beyond the standard library: the tool names are read from sdr_agent.py's source."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DIR = HERE / "prompts"
PAIRS = [("system_it.md", "system_en.md"), ("inbound_it.md", "inbound_en.md"), ("claims_it.md", "claims_en.md")]
DISPOSITIONS = ("meeting_booked", "manual_scheduling", "callback", "not_now", "not_interested", "not_a_fit",
                "wrong_person", "dnc", "other")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def tool_names() -> set[str]:
    src = (HERE / "sdr_agent.py").read_text()
    return set(re.findall(r"@function_tool\(\)\s+async def (\w+)\(", src))


def shape(text: str, tools: set[str]) -> dict:
    """What must match between the two languages (wording may differ, structure may not)."""
    text = _COMMENT.sub("", text)
    lines = [x.rstrip() for x in text.splitlines()]
    return {
        "sections (#)": sum(1 for x in lines if x.startswith("# ")),
        "subsections (##)": sum(1 for x in lines if x.startswith("## ")),
        "numbered steps": sum(1 for x in lines if re.match(r"\s*\d+\.\s", x)),
        "bullets": sum(1 for x in lines if re.match(r"\s*-\s", x)),
        "placeholders": sorted(set(re.findall(r"\{(\w+)\}", text))),
        "tools": sorted(t for t in tools if re.search(rf"\b{t}\b", text)),
        "dispositions": sorted(d for d in DISPOSITIONS if re.search(rf'"{d}"|\b{d}\b(?=[,.])', text)),
    }


def problems(folder: Path = DIR) -> list[str]:
    """folder: the prompts to check (the improvement loop checks a candidate copy before simulating it)."""
    tools = tool_names()
    out = []
    for it_name, en_name in PAIRS:
        it, en = shape((folder / it_name).read_text(), tools), shape((folder / en_name).read_text(), tools)
        for key in it:
            if it[key] != en[key]:
                out.append(f"{it_name} vs {en_name}: {key} differ: it={it[key]} en={en[key]}")
    return out


def main() -> None:
    found = problems()
    if found:
        print("prompts out of step:\n  - " + "\n  - ".join(found))
        sys.exit(1)
    print(f"prompts in step: {len(PAIRS)} it/en pairs, tools named: {', '.join(sorted(tool_names()))}")


if __name__ == "__main__":
    main()
