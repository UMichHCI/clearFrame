import json

from openai import OpenAI

from .config import MODEL_FULL
from .llm import api_chat, extract_json
from .stage8_selection import CONFIDENCE_WEIGHTS
_OUTLET_CONTEXT_CACHE: dict[str, dict] = {}   # domain -> context, for this run

OUTLET_CONTEXT_SYSTEM = """
You are asked what you know, from your training data, about the institutional position
of a news outlet: who owns it, how it is funded, and what its relationship is to state
power in the country it operates from.

Accuracy matters far more than completeness. If you are not confident, "unknown" is the
correct answer. Fabricating or guessing at ownership details is a failure. Do not infer
ownership from the outlet's name, from its country, or from the general reputation of
media in that country. If you do not specifically recall this outlet, say so.

Return ONLY valid JSON, no markdown fences:

{
  "ownership_summary":  "<who owns and funds it, or 'unknown'>",
  "state_relationship": "<state-owned | state-funded | state-aligned | independent of the state | adversarial to the state | unknown>",
  "confidence":         "high | medium | low"
}

Use confidence "low" whenever you are working from a general impression rather than
specific recall. Use "unknown" freely.

Describe the outlet's institutional position structurally â€” ownership, funding, and its
relationship to state power. Do not characterise the intent of the outlet or its journalists.
"""


def get_outlet_context(domain: str, client: OpenAI) -> dict:
    """
    Returns {ownership_summary, state_relationship, confidence} for a domain.
    Cached per domain for the lifetime of the run.
    BACKEND ONLY â€” must never reach a user-facing field.
    """
    key = str(domain).lower().strip()
    if key in _OUTLET_CONTEXT_CACHE:
        return _OUTLET_CONTEXT_CACHE[key]

    fallback = {
        "ownership_summary":  "unknown",
        "state_relationship": "unknown",
        "confidence":         "low",
    }
    if not key:
        return fallback

    try:
        raw = api_chat(
            client,
            system=OUTLET_CONTEXT_SYSTEM,
            user=f"News outlet domain: {key}",
            max_tokens=400,
            model=MODEL_FULL,
            response_format={"type": "json_object"},
        )
        parsed  = json.loads(extract_json(raw))
        context = {
            "ownership_summary":  str(parsed.get("ownership_summary", "unknown")),
            "state_relationship": str(parsed.get("state_relationship", "unknown")),
            "confidence":         str(parsed.get("confidence", "low")),
        }
    except Exception as e:
        print(f"      [WARNING] Outlet context lookup failed for {key}: {e}")
        context = fallback

    _OUTLET_CONTEXT_CACHE[key] = context
    return context


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# STAGE 7 â€” CHOMSKY PAIR ANALYSIS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# The heart of the system: one full-text call per candidate, comparing it against
# the base article through the analytic categories of the propaganda model.
#
# Sponsor-congeniality of quoted experts is deliberately EXCLUDED from the
# categories below. Herman and Chomsky treat the funding of experts as part of the
# sourcing filter, but think-tank and expert funding is largely undisclosed: the
# model cannot reliably determine who funds a quoted analyst, so any finding in
# that category would rest on guesswork. It is left out rather than guessed at.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

CHOMSKY_CATEGORIES = [
    "worthy_unworthy_victims",
    "agency_attribution",
    "presuppositions_doctrine",
    "selective_criteria",
    "suppressed_alternative",
    "smoke_and_discrepancies",
]

CHOMSKY_PAIR_SYSTEM = """
You are comparing two news articles about the same event through the analytic categories
of Herman and Chomsky's propaganda model (Manufacturing Consent, 1988).

The model is STRUCTURAL, not conspiratorial. Coverage patterns arise from an outlet's
position, its audience, and its sourcing â€” not from the intent of journalists. No editorial
directive is required for these patterns to appear; the selection happens upstream of any
individual article. Never write that an outlet or a journalist "hid," "chose to suppress,"
"deliberately" did anything, or is "producing propaganda." Describe patterns as consequences
of structure. If you cannot state a finding without attributing intent, the finding is wrong
as stated â€” restate it structurally, or drop it.

Your job is to find what this PAIR of articles reveals that neither reveals alone.

The general analytic move underlying every category is the COUNTERFACTUAL SWAP: would these
facts have been written in this register if the actors' nationalities or alignments were
swapped? Would the same things be presupposed? Would the same evaluative criteria apply?

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
ANTI-OVER-FINDING RULES â€” READ THESE BEFORE ANYTHING ELSE
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
"applies": false is a valid and EXPECTED answer.

Most article pairs will exhibit real evidence for only ONE TO THREE of the six categories.
Flagging many categories on weak evidence is a failure mode, not thoroughness.

Every "applies": true requires AT LEAST ONE VERBATIM QUOTE as evidence. If you cannot quote
it, it does not apply. Quotes must be copied exactly from the article text you were given â€”
never paraphrased, never reconstructed.

If the evidence is a stretch, mark the category not-applicable, or mark it low confidence.
A pair with one well-evidenced finding is a better result than a pair with six thin ones.

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
THE SIX CATEGORIES
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

1. worthy_unworthy_victims
Compare how the two articles treat the people harmed. Worthy victims receive extensive
attention, vivid detail, expressions of indignation, and demands for justice. Unworthy
victims receive a low-key, philosophical register that treats violence as a sad constant of
the human condition â€” sober sadness doing the work that suppression would otherwise do.
Also check RESPONSIBILITY DIRECTION: for worthy victims, responsibility is traced upward to
leaders and policies; for unworthy victims it is pushed downward to rogue actors, local
conditions, or tragic excess.
Also check FACTS WITHOUT RECOGNITION: harm that is on the page but reported in a register
inappropriate to it â€” civilian deaths mentioned inside a paragraph about operational
outcomes, for instance. This is what defeats the defense of "but they reported it."

2. agency_attribution
Compare the causal grammar. When one article names a clear agent with active, unambiguous
language ("he slaughtered," "forces massacred") and the other renders comparable harm
agentless â€” passive voice ("were killed"), agentless nominalization ("a wave of violence"),
softened vocabulary â€” that asymmetry is the finding. The killing described as something that
happened rather than something someone did.

3. presuppositions_doctrine
Identify what each article stands on as axioms rather than as claims to be defended:
  - definite descriptions that settle contested questions in passing ("the rebels," "the regime")
  - verbs that assume a motive structure ("defending," "stabilizing," "responding")
  - modifiers that smuggle judgment ("legitimately elected," "controversial leader")
  - what is treated as needing explanation, versus what passes as common sense
  - whose quoted claims are absorbed into the article's own narration, versus held at arm's
    length as attributed claims
  - whether a mobilizing ideological enemy is invoked in ways that lower the standard of evidence
Where the two articles stand on different floors, name both floors.

4. selective_criteria
Identify what standards each article invites the reader to judge the event by, and whether the
chosen criteria are ones the event is positioned to pass. The classic case: an ally's election
judged by turnout and orderly polling stations, while the criteria that would be applied to an
adversary's election â€” whether the opposition could campaign safely, whether the press was
free, whether the preconditions for a meaningful vote obtained â€” stay off the page.
Where the two articles apply different criteria to the same event, name both sets.

5. suppressed_alternative
Ask whether there is a rival account of this event â€” one an informed observer outside the
reporting country's mainstream would recognize as plausible â€” that one article forecloses so
completely that the chosen frame reads as the only possible reading. The article does not argue
against the alternative; the alternative simply is not there, so the reader does not know there
is something to weigh.
CRITICALLY: the two articles in this pair can be each other's suppressed alternative. Check
both directions.

6. smoke_and_discrepancies
Two narrower checks combined.
  (a) ARTICLE-LEVEL SMOKE PRODUCTION: does either article accumulate volume around a frame â€”
      speculation, peripheral detail, expressions of doubt and interest â€” while never engaging
      the substantive questions (motive, quality of evidence) that would adjudicate it?
  (b) FACTUAL DISCREPANCIES: where do the two articles make incompatible factual claims
      (casualty counts, sequence of events, who initiated)? Flag the discrepancy WITHOUT
      adjudicating which is true â€” you cannot verify facts, only surface disagreement.
Where the facts AGREE across institutionally very different outlets, that agreement is itself
worth one sentence: it tells the reader the fact is solid.

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
CONFIDENCE
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Confidence is defined by EVIDENCE STRENGTH, not by how interesting the finding is:
  "high"   â€” the pattern is unmistakable and quotable from BOTH articles
  "medium" â€” present but partial
  "low"    â€” suggestive only

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
OUTPUT FORMAT
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Return ONLY valid JSON, no markdown fences. Include ALL SIX category keys.
Categories that do not apply need only {"applies": false}.

{
  "row_index": <int>,
  "categories": {
    "worthy_unworthy_victims": {
      "applies": true,
      "confidence": "high" | "medium" | "low",
      "finding": "<1-2 sentences, structural language only, no intent attribution>",
      "evidence_base": ["<verbatim quote from the base article>"],
      "evidence_candidate": ["<verbatim quote from the candidate article>"],
      "counterfactual_check": "<1 sentence: does this finding survive the swap test?>"
    },
    "agency_attribution":       {"applies": false},
    "presuppositions_doctrine": {"applies": false},
    "selective_criteria":       {"applies": false},
    "suppressed_alternative":   {"applies": false},
    "smoke_and_discrepancies":  {"applies": false}
  },
  "why_this_article": "<2-3 plain sentences written FOR THE READER: what does reading this article alongside the original let them see? Lead with the single strongest finding. No jargon, no category names, no intent language.>"
}
"""

CHOMSKY_PAIR_USER_TEMPLATE = """\
BASE ARTICLE â€” the article the reader is currently reading
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{base_text}

CANDIDATE ARTICLE
Outlet:         {cand_domain}
Source country: {cand_country}
Language:       {cand_language}
Title:          {cand_title}
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{cand_text}

â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Possibly unreliable background on the candidate outlet's institutional position.
Use it only to inform your reasoning about structural position. Never assert it as
fact in any output field.
  Ownership:          {ownership_summary}
  State relationship: {state_relationship}
  Model's confidence: {confidence}
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

Analyse this pair. The candidate's row_index is {row_index}.
"""


def chomsky_pair_analysis(base_text: str, candidate_row, outlet_context: dict,
                          client: OpenAI) -> dict:
    """
    One full-text pair analysis: base article <-> one candidate.
    Returns {row_index, categories, why_this_article}.
    """
    row_index = int(candidate_row.get("row_index", 0))

    user_prompt = CHOMSKY_PAIR_USER_TEMPLATE.format(
        base_text=base_text[:7000],
        cand_domain=str(candidate_row.get("domain", "unknown")),
        cand_country=str(candidate_row.get("sourcecountry", "unknown")),
        cand_language=str(candidate_row.get("language", "unknown")),
        cand_title=str(candidate_row.get("title", "")),
        cand_text=str(candidate_row.get("article_text", ""))[:7000],
        ownership_summary=outlet_context.get("ownership_summary", "unknown"),
        state_relationship=outlet_context.get("state_relationship", "unknown"),
        confidence=outlet_context.get("confidence", "low"),
        row_index=row_index,
    )

    raw = api_chat(
        client,
        system=CHOMSKY_PAIR_SYSTEM,
        user=user_prompt,
        max_tokens=3000,
        model=MODEL_FULL,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as e:
        print(f"      [WARNING] Pair analysis returned unparseable JSON for row {row_index}: {e}")
        return {"row_index": row_index, "categories": _clean_categories({}),
                "why_this_article": ""}

    return {
        "row_index":        row_index,
        "categories":       _clean_categories(data.get("categories", {})),
        "why_this_article": str(data.get("why_this_article", "")).strip(),
    }


def _clean_categories(categories: dict) -> dict:
    """
    Normalises the LLM's category output and enforces the evidence rule in code:
    a category that applies but quotes nothing from either article is demoted to
    applies: false. The prompt states the rule; this makes it structural.
    """
    cleaned: dict[str, dict] = {}

    for name in CHOMSKY_CATEGORIES:
        cat = categories.get(name)
        if not isinstance(cat, dict) or not cat.get("applies"):
            cleaned[name] = {"applies": False}
            continue

        ev_base = [str(q).strip() for q in cat.get("evidence_base", []) if str(q).strip()]
        ev_cand = [str(q).strip() for q in cat.get("evidence_candidate", []) if str(q).strip()]

        if not ev_base and not ev_cand:
            cleaned[name] = {
                "applies":  False,
                "_demoted": "applies=true was returned with no verbatim evidence.",
            }
            continue

        confidence = str(cat.get("confidence", "low")).lower().strip()
        if confidence not in CONFIDENCE_WEIGHTS:
            confidence = "low"

        cleaned[name] = {
            "applies":              True,
            "confidence":           confidence,
            "finding":              str(cat.get("finding", "")).strip(),
            "evidence_base":        ev_base,
            "evidence_candidate":   ev_cand,
            "counterfactual_check": str(cat.get("counterfactual_check", "")).strip(),
        }

    return cleaned

