"""Which tier answers a question on the note: lookup (the glossary), quick (one cheap model call), lead (a turn of the lead), visual (a drawn answer).

A keyword classifier, logged with its escalations so the gate can tune it. The researcher may pick a tier; the router
only proposes one."""
import re

VISUAL_WORDS = ("draw", "sketch", "plot", "diagram", "visual", "show me", "picture", "graph", "chart")
CHALLENGE_WORDS = ("why not", "challenge", "disagree", "wrong", "doubt", "instead", "what if", "assume", "assumption", "justify", "evidence", "revise", "change")
DEFINE_WORDS = ("what is", "what does", "define", "meaning of", "stands for", "definition")


def classify(question, kind="ask", glossary=()):
    text = (question or "").strip().lower()
    terms = [entry["term"].lower() for entry in glossary if entry.get("term")]
    if kind == "visualize" or any(word in text for word in VISUAL_WORDS):
        return "visual"
    if kind == "challenge" or any(word in text for word in CHALLENGE_WORDS) or len(text) > 240:
        return "lead"
    if kind == "define" or any(word in text for word in DEFINE_WORDS):
        asked = re.sub(r"^(what (is|does|are)|define|meaning of)\s+", "", text).strip(" ?.")
        if any(asked == term or asked in term or term in asked for term in terms):
            return "lookup"
        return "quick"
    if len(text) <= 120 and text.endswith("?"):
        return "quick"
    return "lead"
