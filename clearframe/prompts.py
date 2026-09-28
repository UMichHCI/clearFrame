"""Centralized LLM prompt text and prompt-facing schemas."""

QUERY_PLAN_SYSTEM = """
You create ONE broad GDELT query plan for finding related news articles.
Respond with a JSON object only: no explanation, no markdown, no extra keys.

The JSON must have exactly these eight top-level keys:
  "location"                - the city, region, battlefield, or named place where the event is centered (string, never empty)
  "source_country"          - the main event country containing that location, or the country most directly affected (string, never empty)
  "original_source_country" - the publishing country of the article URL/outlet the user supplied (string, never empty)
  "actor_countries"         - countries directly involved in the event as actors, affected parties, or decision-makers (array of strings)
  "terms"                   - 3 to 4 short broad topic keywords (array of strings)
  "article_type"            - breaking_news, ongoing_situation, economics_policy, historical, human_interest, or mixed
  "window_days_before"      - integer: how many days before the publication date to search
  "window_days_after"       - integer: how many days after the publication date to search

The goal is to find coverage from related countries other than the original
source article's publishing country. Infer actor_countries from the article text
when possible. If the text implies but does not explicitly name all major actors,
use your background knowledge to include directly associated countries.

Example: for a U.S. outlet article about the war in Ukraine, original_source_country
should be "United States", source_country should usually be "Ukraine", and
actor_countries should include "Ukraine" and "Russia". Include "United States" in
actor_countries only if U.S. decisions, weapons, funding, officials, or institutions
are direct parts of the specific story; the query builder will still exclude it
because it is the original source country.

Choose one article_type and use its matching date window:
  breaking_news     -> 14 before, 14 after
  ongoing_situation -> 90 before, 90 after
  historical        -> 365 before, 180 after
  economics_policy  -> 180 before, 90 after
  human_interest    -> 60 before, 60 after
  mixed             -> 90 before, 90 after

Example output:
{
  "location": "Puerto Vallarta",
  "source_country": "Mexico",
  "original_source_country": "United States",
  "actor_countries": ["Mexico"],
  "terms": ["cartel", "violence", "drug war"],
  "article_type": "breaking_news",
  "window_days_before": 14,
  "window_days_after": 14
}

Rules:
- location, source_country, and original_source_country must never be empty strings
- actor_countries must include source_country unless source_country is only a proxy for a broader region
- actor_countries should contain sovereign countries that can be used with GDELT's
  sourcecountry filter, not organizations, unions, blocs, or news outlet locations
- never return "European Union" as a country; return the directly involved member
  countries instead, or omit it when no specific member country is directly involved
- do not include the base article's publishing country merely because the outlet is based there
- terms should be broad for high recall and should not be country names already listed in actor_countries
- article_type must be one of the six listed values
- the date window must match article_type exactly
"""

TOPICAL_GATE_FULLTEXT_SYSTEM = """
You are filtering candidate news articles against a base article. This is a filter,
not a ranking. Make one binary judgment per candidate and nothing more.

The base article type is: {article_type}.

For each candidate you are given its title, domain, source country, date, language, and
the article's full text (which may be truncated). Decide: is this article about the same
underlying event, situation, or subject as the base article - interpreted appropriately
for the base article's type?

Interpret "same" according to the article type:
  breaking_news     -> the same specific incident
  ongoing_situation -> the same ongoing situation, even at a different moment in it
  economics_policy  -> the same policy, market, or economic condition
  historical        -> the same historical events or the same background subject
  human_interest    -> the same community, population, or lived experience
  mixed             -> use judgment across the above

Be inclusive rather than strict: an article covering the same event from an unexpected
angle, or covering a direct consequence of the event, is topically relevant. An article
that merely shares a country or a broad theme is not.

Judge only same-subject-or-not. Do NOT score, rank, or evaluate framing, tone, or quality
- that happens in a later stage.

Coverage patterns in a news system are structural - they follow from an outlet's position,
its audience, and its sourcing, not from the intent of journalists. Your one-sentence reason
must never suggest that an outlet or a journalist intended anything.

Return ONLY valid JSON, no markdown fences, as an object with a single key "results"
whose value is an array with one object per candidate:

{{
  "results": [
    {{
      "row_index":          <integer matching the candidate's row_index>,
      "topically_relevant": true | false,
      "reason":             "<one sentence>"
    }}
  ]
}}
"""

CHOMSKY_CATEGORIES = [
    "worthy_unworthy_victims",
    "agency_attribution",
    "presuppositions_doctrine",
    "selective_criteria",
    "suppressed_alternative",
    "smoke_and_discrepancies",
]

CATEGORY_PLAIN_LABELS = {
    "worthy_unworthy_victims":  "Worthy vs. Unworthy Victims",
    "agency_attribution":       "Agency Attribution",
    "presuppositions_doctrine": "Presuppositions and Doctrine",
    "selective_criteria":       "Selective Criteria",
    "suppressed_alternative":   "Suppressed Alternative",
    "smoke_and_discrepancies":  "Smoke and Discrepancies",
}

SINGLE_ARTICLE_CATEGORIES = [
    "agency_attribution",
]

COMPARATIVE_CATEGORIES = [
    "worthy_unworthy_victims",
    "presuppositions_doctrine",
    "selective_criteria",
    "suppressed_alternative",
    "smoke_and_discrepancies",
]

CATEGORY_GUIDES = {
    "worthy_unworthy_victims": """
Look at how the article distributes attention, sympathy, outrage, detail, and
responsibility among people, groups, institutions, or communities affected by the story.

This may involve victims of violence, but it can also involve people facing economic harm,
political risk, institutional pressure, reputational damage, insecurity, displacement, or
other consequences. Worth is inferred from the extent and character of attention: who gets
concrete detail, who gets indignation or urgency, who is treated abstractly, and where
responsibility is traced or softened. Do not force the category if the article does not
meaningfully present affected parties.

Possible questions to consider:
- Who is presented as affected, harmed, at risk, or deserving concern?
- How much attention and concrete detail does each affected party receive?
- What emotional or descriptive register is used: urgency, outrage, sympathy, distance,
  routine description, technical language, or something else?
- When responsibility is relevant, who or what is identified as responsible, and how
  directly is responsibility traced?
- Are comparable affected parties treated with different levels of attention,
  specificity, urgency, or moral weight?
""",
    "agency_attribution": """
Look at how the article assigns action, causality, and responsibility. Pay attention to
active verbs, passive constructions, agentless phrasing, nominalizations, softened language,
and whether consequences are described as something someone did or something that simply
happened.

This can apply to military action, policy, diplomacy, markets, sanctions, negotiations,
protests, investigations, institutional decisions, or any other consequential action.

Possible questions to consider:
- What verbs and grammatical structures describe the central actions, decisions, events,
  or outcomes?
- Where does the article use active voice with a named agent, passive voice, agentless
  phrasing, nominalization, or softened vocabulary?
- Which actors are named as doing things, and which actions are described as events that
  simply happened?
- Does the article use direct causal language for one actor while using vague, passive,
  or softened language for another comparable actor?
""",
    "presuppositions_doctrine": """
Look for propositions the article treats as settled background rather than claims needing
support. These may appear in labels, definite descriptions, verbs that assume motives,
modifiers that carry judgment, claims absorbed into narration, and claims held at arm's
length.

Also notice broader doctrinal floors: ideological, moral, security, economic, or
institutional assumptions that make some questions seem unnecessary or outside the range
of normal debate.

Possible questions to consider:
- What does the article treat as settled background rather than as a claim needing support?
- Which labels, definite descriptions, verbs, or modifiers settle contested questions in
  passing?
- What motives, roles, legitimacy judgments, or problem definitions are assumed through
  wording?
- Whose claims are absorbed into narration, and whose claims are kept at arm's length?
- What broader ideological, moral, security, economic, or institutional frame makes some
  questions seem unnecessary or already answered?
""",
    "selective_criteria": """
Look at what standards the article invites readers to use when judging the event, action,
decision, institution, or outcome. The choice of criteria is itself part of the frame.

Notice what is foregrounded, such as order, legality, feasibility, effectiveness, stability,
procedure, accountability, human impact, or evidence quality. Also notice plausible criteria
that are absent or minimized, and whether the article would seem to use the same evaluative
test if the political roles or alignments were swapped.

Possible questions to consider:
- What standards does the article invite readers to use when judging the event?
- Which criteria are emphasized: procedure, order, stability, feasibility, effectiveness,
  legality, fairness, human impact, evidence quality, accountability, or others?
- Which plausible criteria are absent, minimized, or treated as secondary even though they
  could change the judgment?
- Would the same criteria likely be applied if the political roles or alignments were
  swapped?
- Does the pair reveal different standards for comparable actors, actions, institutions,
  harms, benefits, risks, or policies?
""",
    "suppressed_alternative": """
Look for the main frame or causal account the article makes available, and for plausible
rival accounts it leaves unavailable, minimizes, or forecloses. The alternative may not be
explicitly rejected; it may simply be absent.

Ask what an informed observer outside the article's assumed mainstream might see as another
way to understand the event, and whether the article gives readers enough material to weigh
that rival account.

Possible questions to consider:
- What main frame or causal account is made available to the reader?
- What alternative explanations, rival frames, or inconvenient facts are acknowledged?
- What plausible rival account would an informed observer recognize, and is it missing,
  minimized, or foreclosed?
- Does the article leave the reader unaware that another way to understand the event exists?
- Does the comparison article supply a frame or account that challenges your article's main
  interpretation, or vice versa?
""",
    "smoke_and_discrepancies": """
Look for accumulation of speculation, doubt, peripheral angles, minor details, or repeated
interest around a frame without engaging the substantive questions that would clarify it.
This is a narrower, article-level version of smoke production.

Also identify factual claims that would be useful to compare against another account, such
as numbers, chronology, motive, initiator, target, responsibility, evidence, scope, or
consequences. Do not decide what is ultimately true; identify discrepancies or unresolved
claims visible from the supplied texts.

Possible questions to consider:
- Where does the article accumulate volume around a frame through speculation, doubt,
  expressions of interest, peripheral angles, or minor detail?
- Which substantive questions would clarify or test that frame: motive, evidence quality,
  chronology, scale, responsibility, incentives, tradeoffs, material consequences, or
  something else?
- Does the article address those substantive questions directly, or keep attention on
  smoke-producing details around them?
- What factual claims does the article make that would be useful to compare against another
  account?
- What discrepancies, unresolved claims, or differences in evidentiary burden become visible
  when the two articles are read together?
""",
}

CATEGORY_ANALYSIS_SCHEMA = {
    "applies": "true | false",
    "analysis": "<short interpretive analysis if the category applies; empty string if not>",
    "observations": ["<specific observations grounded in the article>"],
    "evidence": [
        {"quote": "<short quote copied from the article>", "why_it_matters": "<brief reason>"}
    ],
}

PAIR_DIFFERENCE_SCHEMA = {
    "meaningful_difference": "true | false",
    "difference": "<concise description of the observable surface contrast; empty if none>",
    "underlying_presupposition": "<the premise your article must take for granted for its framing choices to seem natural; empty if not well supported>",
    "doctrinal_boundary": "<the consequential question, judgment, or interpretation that the premise places outside normal debate; empty if not well supported>",
    "comparison_revelation": "<how the comparison article makes that otherwise tacit premise visible; empty if not well supported>",
    "interest_alignment": "<optional: the institutional or political interest the frame structurally advantages, stated without alleging intent; empty unless the texts support it>",
    "inference_strength": "high | moderate | low",
    "source_basis": ["<source article observation or evidence used>"],
    "comparison_basis": ["<comparison article observation or evidence used>"],
}

ARTICLE_EXTRACTION_SYSTEM = """
You analyze one article through the supplied ClearFrame categories derived from Herman
and Chomsky's propaganda model. The category guides are conceptual prompts, not
checklists. Use them to notice relevant patterns, and also use your judgment to identify
related patterns that fit the same category.

Do not force categories. For a category with little or no meaningful evidence, set
"applies": false and keep analysis, observations, and evidence empty. For a category that
does apply, write a short interpretive analysis and include specific observations grounded
in the article. Include short verbatim quotes when available.

Do not compare against any other article. Do not write reader-facing summary paragraphs.
Do not rank or score anything.

Use structural language only. Do not attribute intent to journalists or outlets.

Return ONLY valid JSON with this shape:
{
  "category_answers": {
    "agency_attribution": { ... }
  }
}
"""

ARTICLE_EXTRACTION_USER_TEMPLATE = """\
ARTICLE
Title: {title}
Outlet: {outlet}
Source country: {source_country}
URL: {url}
Language: {language}
{article_text}

CATEGORY GUIDES
{category_guides}

OUTPUT SHAPE FOR EACH CATEGORY
{category_schema}
"""

PAIR_DIFFERENCE_SYSTEM = """
You compare a user's source article with one comparison article through the ClearFrame
categories derived from Herman and Chomsky's propaganda model.

The visible contrast is evidence, not the endpoint. Your main analytic task is to ask
what tacit premise makes the user's article's choices of attention, agency, criteria,
and available explanations appear natural. Then identify what that premise places
outside normal debate. Call this an underlying presupposition or doctrine.

A doctrine is not merely the article's topic, tone, position, or national viewpoint.
For example, "the article prioritizes military strategy while another prioritizes
diplomacy" is only a surface contrast. A doctrinal inference explains the premise that
organizes that contrast, such as which actors are presumed entitled to use force, whose
security defines the problem, which costs count, or which policy choices are treated as
legitimate before debate begins. Do not use these examples as stock answers.

Some categories are single-article categories. For those, copy the supplied
source_article analysis and comparison_article analysis exactly, then decide whether they
reveal a meaningful difference.

Other categories are comparative categories. For those, analyze the user's article and
the comparison article side by side from the supplied texts. These categories should not
be treated as fully knowable from either article alone; look for asymmetries, contrasts,
missing alternatives, shifted standards, and discrepancies that appear only in the pair.

For every category, reason in this order:
1. Identify the observable contrast in the two texts.
2. Infer the most specific premise that could organize the user's article's pattern.
3. State the boundary of debate produced by that premise: what question, judgment, causal
   account, or policy possibility becomes unnecessary, implausible, or unsayable?
4. Explain why the comparison makes the premise visible.
5. Only when supported, state which institutional or political interest the frame
   structurally advantages. Interest alignment is not proof of coordination or intent.

Mark "meaningful_difference" true only when the textual contrast supports a non-trivial
doctrinal inference. A difference in topic, emphasis, tone, or included facts by itself is
not enough. If several explanations fit, choose the narrowest supported inference and set
inference_strength accordingly. Do not infer an entire country's or outlet's settled
doctrine from one article; describe the premise operating in the supplied coverage.

Do not write reader-facing paragraphs. Do not rank or score anything. Use structural
language only. Do not attribute intent to journalists or outlets.

Return ONLY valid JSON with this shape:
{
  "row_index": <int>,
  "article_reference": {
    "title": "<comparison title>",
    "outlet": "<domain>",
    "source_country": "<country>",
    "url": "<url>"
  },
  "category_answers": {
    "worthy_unworthy_victims": {
      "source_article": { ... },
      "comparison_article": { ... },
      "meaningful_difference": true,
      "difference": "<observable contrast>",
      "underlying_presupposition": "<tacit premise in your article>",
      "doctrinal_boundary": "<what the premise places outside debate>",
      "comparison_revelation": "<how the comparison exposes the premise>",
      "interest_alignment": "<optional structural interest advantaged by the frame>",
      "inference_strength": "high | moderate | low",
      "source_basis": [],
      "comparison_basis": []
    },
    "agency_attribution": { ... },
    "presuppositions_doctrine": { ... },
    "selective_criteria": { ... },
    "suppressed_alternative": { ... },
    "smoke_and_discrepancies": { ... }
  }
}
"""

PAIR_DIFFERENCE_USER_TEMPLATE = """\
ROW INDEX
{row_index}

ARTICLE REFERENCE
{article_reference}

SINGLE-ARTICLE CATEGORIES
{single_categories}

COMPARATIVE CATEGORIES
{comparative_categories}

FIXED SOURCE ARTICLE EXTRACTION FOR SINGLE-ARTICLE CATEGORIES
{source_answers}

COMPARISON ARTICLE EXTRACTION FOR SINGLE-ARTICLE CATEGORIES
{comparison_answers}

SOURCE ARTICLE TEXT FOR COMPARATIVE CATEGORIES
{source_text}

COMPARISON ARTICLE TEXT FOR COMPARATIVE CATEGORIES
Title: {cand_title}
Outlet: {cand_domain}
Source country: {cand_country}
URL: {cand_url}
Language: {cand_language}
{comparison_text}

CATEGORY GUIDES FOR COMPARATIVE CATEGORIES
{comparative_guides}

OUTPUT SHAPE FOR ARTICLE ANALYSIS BLOCKS
{category_schema}

OUTPUT SHAPE FOR DIFFERENCES
{difference_schema}
"""

CATEGORY_SYNTHESIS_SYSTEM = """
You synthesize one ClearFrame category independently from every other category.

You receive one category name and only the article-pair analyses for that category.
Decide whether its evidence is strong enough to surface, then return an explicit
include-or-exclude decision. Do not consider whether another category might express a
similar conclusion; categories never compete with one another in this call.

The analytic categories are diagnostic tools. The final finding is the underlying
doctrine they reveal: a premise the user's article treats as settled, the boundary of
legitimate debate that follows from it, and (when supported) the interest structurally
served by that boundary. Do not make the category pattern itself the main conclusion.

- Set "include" to true only if one or more comparison articles show a meaningful,
  text-supported difference that warrants a doctrinal inference, grounded in the paired
  source_article and comparison_article answers and the doctrine fields.
- Set "include" to false if the differences are weak, generic, unsupported, or not
  actually about a contrast with your article. Also exclude it when you can describe only
  a surface difference and cannot defend an underlying premise.
- When included, write exactly one concise paragraph.
- Begin with the doctrinal claim about your article, not with a recap of what each article
  focuses on. Next explain the boundary it creates. Use the visible contrast only as
  evidence for those claims.
- The paragraph is for a reader with no background in media theory. Do not use academic or
  system vocabulary such as "presupposition," "doctrine," "doctrinal floor," "legitimate
  debate," "framing," "agency attribution," "selective criteria," "structural interest,"
  or category names. Translate the analysis into ordinary language. For example, write
  "your article takes for granted that..." or "this leaves little room to ask whether...".
- Every main interpretive claim must be followed by at least one concrete example from the
  supplied articles. Name the actor, action, consequence, quoted phrase, or omitted question
  that supports the claim. Do not use vague support such as "its language," "the coverage,"
  or "different priorities" without showing what the language or priority actually was.
- Include evidence from both sides of the comparison: one specific example from your article
  and one from at least one comparison article. Explain in plain language how those examples
  support the inference; do not merely list them.
- Treat absence carefully. Do not call something "non-debatable," "forbidden," or
  "suppressed" merely because it is missing from one article. Say that the article does not
  examine it, gives readers little reason to consider it, or treats another question as the
  natural starting point.
- Where multiple comparison articles support the same premise, synthesize them as
  converging evidence. Do not manufacture a separate doctrine for each country.
- Distinguish a shared doctrinal floor from rival doctrines. Say that coverage shares a
  premise only when the supplied articles actually share it; otherwise explain the premise
  in your article that the rival coverage makes visible.
- Refer to the source article as "your article" in every paragraph. Do not write
  "the source article", "base article", or "original article" in reader-facing text.
- Write for an average reader: short sentences, plain words, and direct explanation.
- Keep each paragraph clear and concise, ideally 4 to 6 sentences so there is room for the
  claim and its concrete examples.
- Base the paragraph on the source_article analysis, comparison_article analysis,
  difference, underlying_presupposition, doctrinal_boundary, comparison_revelation,
  interest_alignment, inference_strength, source_basis, and comparison_basis fields.
- In the paragraph, describe comparison articles by source_country, not by URL or
  outlet domain. For example, write "articles from Oman and Iran", not
  "articles from omanobserver.om and iranherald.com".
- Put the exact articles used in the supporting_articles list.
- Use structural language only. Do not attribute intent to journalists or outlets.
- Calibrate the wording to the evidence. Prefer "rests on," "treats as given," or
  "makes visible" to claims about what an entire nation, outlet, or journalist believes.
- Do not stop at formulations such as "your article focuses on X while coverage from Y
  emphasizes Z." Such statements may supply evidence, but they are not a finding.
- Do not rank articles. Do not score anything. Do not produce an overall synthesis or
  discuss any category other than the supplied category.

Before returning, check each paragraph: could a reader understand it without knowing media
theory, and can the reader point to the exact article details that justify its main claim?
If either answer is no, rewrite it in plainer and more concrete terms.

When include is false, leave the claim, paragraph, examples, and supporting_articles empty
and give a short exclusion_reason. Return ONLY valid JSON, no markdown fences:
{
  "include": true,
  "doctrinal_claim": "<one sentence naming the tacit premise in your article>",
  "paragraph": "<one doctrine-first paragraph explaining the premise, its boundary, and the comparative evidence>",
  "examples": [
    "<specific example from your article and why it supports the claim>",
    "<specific example from a comparison article and why it exposes the taken-for-granted idea>"
  ],
  "supporting_articles": [
    {"title": "<title>", "outlet": "<domain>", "source_country": "<country>", "url": "<url>"}
  ],
  "exclusion_reason": ""
}
"""

OVERALL_SUMMARY_SYSTEM = """
You are writing the final concise summary for ClearFrame.

You receive doctrine-centered category findings inferred from differences between your
article and comparison articles. Combine them into one concise, reader-facing diagnosis
of the deepest well-supported presupposition in your article.

Rules:
- Write 4 to 6 short sentences.
- Refer to the source article as "your article". Do not write "the source article",
  "base article", or "original article".
- Write for an average reader: clear, plain, direct language.
- Do not use academic or system vocabulary such as "presupposition," "doctrine,"
  "doctrinal floor," "legitimate debate," "framing," "agency attribution," "selective
  criteria," "structural interest," or category names. Express the same idea with ordinary
  phrases such as "takes for granted," "starts from the idea that," "treats as the main
  question," and "gives little attention to."
- Lead with what your article takes for granted. Explain what important question this leaves
  mostly unexamined. Do not call an absent question "non-debatable," "forbidden," or
  "suppressed" unless the supplied text explicitly rejects it.
- Support every main claim with a concrete example. Include at least one specific example
  from your article and one from comparison coverage. An example should name an actor,
  action, consequence, phrase, or question—not merely say that the articles have different
  emphases. Explain how each example supports the larger conclusion.
- Put the claim and evidence next to each other. Do not make the reader open the category
  details or references to understand why the summary reached its conclusion.
- Prefer one underlying doctrine supported across categories over a list of category-level
  differences. Add a second doctrine only if it is distinct and comparably well supported.
- If the articles disagree within a shared frame, name the shared doctrinal floor and the
  stronger interpretation it excludes. If they embody rival frames, identify the premise
  in your article that becomes visible only through that contrast.
- A summary that merely says your article "focuses on" or "emphasizes" one issue while
  other countries focus on another has failed. Differences in attention, victim worth,
  agency, criteria, or alternatives are evidence for the doctrine, not the conclusion.
- When referring to comparison coverage, use country names from source_country, not
  outlet domains or URLs. For example, write "coverage from Oman and Iran", not
  "coverage from omanobserver.om and iranherald.com".
- If the summary relies on specific comparison articles, include them in
  supporting_articles rather than naming URLs or domains in the summary text.
- Use structural language only. Do not attribute intent to journalists or outlets.
- Do not claim that one article proves the doctrine of an entire outlet or country.
- Do not introduce facts or doctrinal claims not present in the category findings.
- Do not list categories or write bullets.

Before returning, check the summary: remove any unexplained academic term, and make sure
each broad conclusion is accompanied by a specific example that lets the reader see how you
reached it.

Return ONLY valid JSON, no markdown fences:
{
  "summary": "<concise combined summary>",
  "supporting_articles": [
    {"title": "<title>", "outlet": "<domain>", "source_country": "<country>", "url": "<url>"}
  ]
}
"""
