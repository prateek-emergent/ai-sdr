"""Every line the code itself says (never the LLM), per language. Wording is unchanged from the 16 Oct worker,
except the two recovery lines, which are new: they replace silence when the language model fails."""
from __future__ import annotations

import re

LINES: dict[str, dict[str, str]] = {
    "dnc": {"en": "Understood, we won't bother you again. Sorry for the inconvenience.",
            "it": "Capito, non la disturberemo più. Mi scusi per il disturbo."},
    "check_in_1": {"en": "Hello? Are you there? I can't hear you.",
                   "it": "Pronto? È in linea? Non la sento."},
    "check_in_2": {"en": "I still can't hear you. I think there might be a network issue on your end. Are you there?",
                   "it": "Continuo a non sentirla. Forse c'è un problema di rete dalla sua parte. È lì?"},
    "give_up": {"en": "Sorry, we aren't able to hear you. We'll get in touch with you after a short while. Talk soon!",
                "it": "Mi scusi, non riusciamo a sentirla. La ricontattiamo tra un po'. A presto!"},
    "ask_time": {"en": "Sorry, the line keeps breaking up. When would be a good time for me to call you back?",
                 "it": "Mi scusi, la linea continua a interrompersi. Quando posso richiamarla?"},
    "thanks": {"en": "Thanks for your time. ", "it": "Grazie per il suo tempo. "},
    # the language model failed to answer (both routes): ask them to repeat instead of going silent
    "recover": {"en": "Sorry, could you say that again?", "it": "Mi scusi, può ripetere?"},
    # it keeps failing: close politely rather than leave dead air
    "tech_trouble": {"en": "Sorry, I'm having a technical problem on my side. We'll call you back shortly. Bye for now!",
                     "it": "Mi scusi, ho un problema tecnico. La richiamiamo a breve. A presto!"},
}


def line(name: str, language: str) -> str:
    table = LINES[name]
    return table.get(language, table["it"])


def check_ins(language: str, n: int) -> list[str]:
    return [line("check_in_1", language), line("check_in_2", language)][:n]


GOODBYE_WORDS = re.compile(
    r"\b(?:good)?bye\b|good ?night|have an? (?:nice|good|great|lovely|wonderful|fantastic) (?:day|evening|one|weekend)"
    r"|take care|talk soon|speak soon|see you|arrivederci|buona (?:giornata|serata|continuazione)|buonanotte"
    r"|a presto|ciao", re.I)

# the agent has already said the do-not-call line in its own words
DNC_SAID = re.compile(r"bother|won't call|disturb|non la chiameremo", re.I)

# what the agent says when it can't hear or understand the person (counted by LineWatch: unchanged policy)
TROUBLE_WORDS = re.compile(
    r"breaking up|cut(?:ting)? out|lost you|can't hear|cannot hear|(?:did|could)n't catch|repeat that"
    r"|(?:could|can) you (?:please )?(?:repeat|say that)|say that (?:again|once more)|didn't get that"
    r"|one more time\?|are you there|si interrompe|va e viene|non la sento|l'ho persa|può ripetere|ripetere|è in linea|è lì",
    re.I)
