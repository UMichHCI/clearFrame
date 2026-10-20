"""Centralized LLM prompt text and prompt-facing schemas."""

# GDELT source-country lookup: https://data.gdeltproject.org/api/v2/guides/LOOKUP-COUNTRIES.TXT
COUNTRY_LOOKUP_TEXT = """
AF	Afghanistan
AX	Akrotiri Sovereign Base Area
AL	Albania
AG	Algeria
AQ	American Samoa
AN	Andorra
AO	Angola
AV	Anguilla
AY	Antarctica
AC	Antigua and Barbuda
AR	Argentina
AM	Armenia
AA	Aruba
AT	Ashmore and Cartier Islands
AS	Australia
AU	Austria
AJ	Azerbaijan
BF	Bahamas, The
BA	Bahrain
FQ	Baker Island
BG	Bangladesh
BB	Barbados
BS	Bassas da India
BO	Belarus
BE	Belgium
BH	Belize
BN	Benin
BD	Bermuda
BT	Bhutan
BL	Bolivia
BK	Bosnia-Herzegovina
BC	Botswana
BV	Bouvet Island
BR	Brazil
IO	British Indian Ocean Territory
VI	British Virgin Islands
BX	Brunei
BU	Bulgaria
UV	Burkina Faso
BY	Burundi
CB	Cambodia
CM	Cameroon
CA	Canada
CV	Cape Verde
CJ	Cayman Islands
CT	Central African Republic
CD	Chad
CI	Chile
CH	China
KT	Christmas Island
IP	Clipperton Island
CK	Cocos Keeling Islands
CO	Colombia
CN	Comoros
CF	Congo
CW	Cook Islands
CR	Coral Sea Islands
CS	Costa Rica
IV	Cote dIvoire
HR	Croatia
CU	Cuba
CY	Cyprus
EZ	Czech Republic
LO	Czechoslovakia
CG	Democratic Republic of the Congo
DA	Denmark
DX	Dhekelia Sovereign Base Area
DJ	Djibouti
DO	Dominica
DR	Dominican Republic
TT	East Timor
EC	Ecuador
EG	Egypt
ES	El Salvador
GV	Equatorial Guinea
EK	Equatorial Guinea
ER	Eritrea
EN	Estonia
ET	Ethiopia
PJ	Etorofu, Habomai, Kunashiri and Shikotan Islands
EU	Europa Island
FK	Falkland Islands Islas Malvinas
FO	Faroe Islands
FJ	Fiji
FI	Finland
FR	France
FG	French Guiana
FP	French Polynesia
FS	French Southern and Antarctic Lands
GB	Gabon
GA	Gambia
GZ	Gaza Strip
GG	Georgia
GM	Germany
GH	Ghana
GI	Gibraltar
GO	Glorioso Islands
GR	Greece
GL	Greenland
GJ	Grenada
GP	Guadeloupe
GQ	Guam
GT	Guatemala
GK	Guernsey
PU	Guinea-Bissau
GY	Guyana
HA	Haiti
HM	Heard Island and McDonald Islands
HO	Honduras
HK	Hong Kong
HQ	Howland Island
HU	Hungary
IC	Iceland
IN	India
ID	Indonesia
IR	Iran
IZ	Iraq
EI	Ireland
IM	Isle of Man
IS	Israel
IT	Italy
JM	Jamaica
JN	Jan Mayen
JA	Japan
DQ	Jarvis Island
JE	Jersey
JQ	Johnston Atoll
JO	Jordan
JU	Juan de Nova Island
KZ	Kazakhstan
KE	Kenya
KQ	Kingman Reef
KR	Kiribati
KV	Kosovo
KU	Kuwait
KG	Kyrgyzstan
LA	Laos
LG	Latvia
LE	Lebanon
LT	Lesotho
LI	Liberia
LY	Libya
LS	Liechtenstein
LH	Lithuania
LU	Luxembourg
MC	Macau
MK	Macedonia
MA	Madagascar
MI	Malawi
MY	Malaysia
MV	Maldives
ML	Mali
MT	Malta
RM	Marshall Islands
MB	Martinique
MR	Mauritania
MP	Mauritius
MF	Mayotte
MX	Mexico
FM	Micronesia
MQ	Midway Islands
MD	Moldova
MN	Monaco
MG	Mongolia
MJ	Montenegro
MH	Montserrat
MO	Morocco
MZ	Mozambique
BM	Myanmar
WA	Namibia
NR	Nauru
BQ	Navassa Island
NP	Nepal
NL	Netherlands
NT	Netherlands Antilles
NC	New Caledonia
NZ	New Zealand
NU	Nicaragua
NG	Niger
NI	Nigeria
NE	Niue
NM	No Mans Land
NF	Norfolk Island
KN	North Korea
CQ	Northern Mariana Islands
NO	Norway
OS	Oceans
MU	Oman
PK	Pakistan
PS	Palau
LQ	Palmyra Atoll
PM	Panama
PP	Papua New Guinea
PF	Paracel Islands
PA	Paraguay
PE	Peru
RP	Philippines
PC	Pitcairn Islands
PL	Poland
PO	Portugal
RQ	Puerto Rico
QA	Qatar
RE	Reunion
RO	Romania
RS	Russia
RW	Rwanda
SH	Saint Helena
SC	Saint Kitts and Nevis
ST	Saint Lucia
RN	Saint Martin
SB	Saint Pierre and Miquelon
VC	Saint Vincent and the Grenadines
TB	Saint-Barthelemy Island
WS	Samoa
SM	San Marino
TP	Sao Tome and Principe
SA	Saudi Arabia
SG	Senegal
RI	Serbia
SE	Seychelles
SL	Sierra Leone
SN	Singapore
SI	Slovenia
BP	Solomon Islands
SO	Somalia
SF	South Africa
SX	South Georgia and the South Sandwich Islands
KS	South Korea
OD	South Sudan
SP	Spain
PG	Spratly Islands
CE	Sri Lanka
SU	Sudan
NS	Suriname
SV	Svalbard
WZ	Swaziland
SW	Sweden
SZ	Switzerland
SY	Syria
TW	Taiwan
TI	Tajikistan
TZ	Tanzania
TH	Thailand
TO	Togo
TL	Tokelau
TN	Tonga
TD	Trinidad and Tobago
TE	Tromelin Island
TS	Tunisia
TU	Turkey
TX	Turkmenistan
TK	Turks and Caicos Islands
TV	Tuvalu
UG	Uganda
UP	Ukraine
UF	Undersea Features
UU	Undesignated Sovereignty
AE	United Arab Emirates
UK	United Kingdom
US	United States
UY	Uruguay
UZ	Uzbekistan
NH	Vanuatu
VT	Vatican City
VE	Venezuela
VM	Vietnam, Democratic Republic of
VQ	Virgin Islands
WQ	Wake Island
WF	Wallis and Futuna
WE	West Bank
WI	Western Sahara
YM	Yemen
ZA	Zambia
ZI	Zimbabwe
"""

QUERY_PLAN_SYSTEM = """
You create ONE broad GDELT query plan for finding related news articles.
Respond with a JSON object only: no explanation, no markdown, no extra keys.

The JSON must have exactly these nine top-level keys:
  "location"                - the city, region, battlefield, or named place where the event is centered; descriptive metadata, not a required search phrase (string, never empty)
  "source_country"          - the main event country containing that location, or the country most directly affected (string, never empty)
  "original_source_country" - the publishing country of the article URL/outlet the user supplied (string, never empty)
  "actor_countries"         - countries directly involved in the event as actors, affected parties, or decision-makers (array of strings)
  "terms"                   - 3 to 4 short event-specific search terms (array of strings)
  "article_type"            - breaking_news, ongoing_situation, economics_policy, historical, human_interest, or mixed
  "coverage_start_date"     - estimated first relevant coverage date, YYYY-MM-DD; always required, never null
  "coverage_end_date"       - estimated last relevant coverage date, YYYY-MM-DD; always required, never null
  "coverage_period_reason"  - brief explanation of the event timeline, evidence, and uncertainty behind the estimated coverage period (string)

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

Choose terms that identify the event or development through its main people, actions,
commodities, policies, or institutions. Prefer short keywords that different outlets
would use over long exact phrases or generic themes. For a story about Trump's deal
for Russian diesel and sanctions relief, terms such as "Trump", "diesel", and "sanctions"
are more useful than only "energy" and "fuel prices". Terms are searched as alternatives
with OR for high recall; the later topical filter checks whether candidates cover the
same development. The location field is metadata and is not automatically added to the
query. Do not rely on a dateline or announcement venue to identify the story. Include a
place in terms only when it helps identify the event itself.

Choose one article_type, then independently estimate the period during which other
news outlets, foreign or domestic, would likely have reported on the same event or
development. Consider when the event occurred, how long it unfolded, relevant lead-up
and aftermath, and whether the article discusses a specific incident or a longer-running
situation. Use dates and temporal cues in the article to justify the endpoints; do not
assign fixed durations by article type or center the period on publication by default.
Always provide both dates, even when the timeline is uncertain. Make your best estimate
from the event context, relative time references, publication date, and current date.
If no event timing is available, use the publication date as an approximate anchor;
if that is unavailable or a fetch-time fallback, use the current date. Estimate a
reporting period appropriate to the development. Explain these assumptions and your
uncertainty in coverage_period_reason; do not present estimated event dates as facts.

Example output:
{
  "location": "Puerto Vallarta",
  "source_country": "Mexico",
  "original_source_country": "United States",
  "actor_countries": ["Mexico"],
  "terms": ["cartel", "violence", "drug war"],
  "article_type": "breaking_news",
  "coverage_start_date": "2026-09-20",
  "coverage_end_date": "2026-09-24",
  "coverage_period_reason": "The article describes an incident on September 20 and related developments through September 24; reporting on that incident likely spans those dates."
}

Rules:
- location, source_country, and original_source_country must never be empty strings
- actor_countries must include source_country unless source_country is only a proxy for a broader region
- Choose source_country, original_source_country, and actor_countries from the
  complete GDELT country-code lookup below. Return each selected entry's country
  name exactly as listed; GDELT accepts these names in sourcecountry filters.
- do not include the base article's publishing country merely because the outlet is based there
- terms should identify the event while allowing differences in wording across outlets;
  avoid standalone country names already listed in actor_countries
- article_type must be one of the six listed values
- coverage_start_date must be on or before coverage_end_date, and neither may be after the supplied current date
- example dates are illustrative only; infer the period from the supplied article
""" + "\nComplete GDELT country lookup (FIPS code, name):\n" + COUNTRY_LOOKUP_TEXT

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
    "analysis": "<state the exact interpretation first, then explain the article details supporting it; empty string if the category does not apply>",
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

For every category, assess the evidence in this order. This is the order for reaching
an interpretation; present explanatory text with the interpretation first and its
supporting article details afterward:
1. Identify the observable contrast in the two texts.
2. Infer the most specific premise that could organize the user's article's pattern.
3. State the boundary of debate produced by that premise: what question, judgment, causal
   account, or policy possibility becomes unnecessary, implausible, or unsayable?
4. Explain why the comparison makes the premise visible.
5. Only when supported, state which institutional or political interest the frame
   structurally advantages. Interest alignment is not proof of coordination or intent.

At each step, assess whether the supplied evidence supports the inference. If it does
not, do not force a finding or complete the sequence speculatively. When the premise,
boundary, or comparative explanation cannot be supported, set
"meaningful_difference": false, preserve any supported observable contrast and its
textual basis, and leave unsupported inference fields empty. Leave interest_alignment
empty when interest alignment is unsupported, even if the premise and boundary are
supported.

Mark "meaningful_difference" true only when the textual contrast supports a non-trivial
doctrinal inference. A difference in topic, emphasis, tone, or included facts by itself is
not enough. If several explanations fit, choose the narrowest supported inference and set
inference_strength accordingly.

Look for established institutional or political assumptions that shape what the article
treats as true, how it explains events, and which policies it considers acceptable.
Identify these assumptions even when they are not stated directly, and show which details
in the texts support your reading. Do not make statements without an explanation.

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

READER_OUTPUT_GUIDANCE = """
Shared readability requirements (take priority over other style guidance):
Write as if explaining the finding aloud to someone who knows nothing about media theory,
political science, or the academic vocabulary of framing. Use plain language and concrete examples.
It should be understandable to a person with an average high school reading level.
Avoid jargon, technical terms, and academic vocabulary.
"""

COUNTRY_CONTEXT_GUIDANCE = """
Use country-specific background knowledge to help explain the observed differences.
Go beyond naming a viewpoint: explain why this particular actor or outlet might find
that interpretation convincing or useful. Relevant context includes historical relations,
alliances and rivalries, security concerns, economic ties, domestic politics, and the
outlet's ownership, independence, audience, or relationship with the government when known.
Apply this scrutiny to your article's country and its allies as well as its opponents.

Distinguish two questions: does the stated objection have a sound basis, and does making
that objection also serve a political interest? Both can be true. A country can identify
a real harm while using it to weaken a rival. A strategic benefit does not by itself
make an objection false, and a reasonable objection does not establish consistent concern.
"""

CATEGORY_SYNTHESIS_GUIDES = {
    "worthy_unworthy_victims": """
The first sentence MUST explicitly name whose harm gets more attention, whose gets
less, and the actual harm involved. Do not merely announce unequal concern or leave
the affected groups for later sentences.
Name the people or groups whose suffering receives greater
concern and those whose suffering receives less concern. Identify the actual harm or
risk for each, and explain which gets sympathy, detail, urgency, or accountability.
State this unequal treatment in the opening claim. "Worthy" and "unworthy" describe
the weight the coverage gives their suffering, not their actual moral worth. Do not
call someone a victim without identifying a supported harm, or invent a second group
merely to fill the category.
""",
    "agency_attribution": """
The first sentence MUST explicitly name who your article blames, excuses, or leaves
unnamed, and for which action or consequence. If the finding concerns unequal treatment
of actors, name both actors and how responsibility is assigned differently.
Identify whose action
or responsibility is made explicit and whose is softened, obscured, or justified.
State that attribution in the opening claim, then show the verbs, passive wording,
missing agent, or stated justification that supports it. Distinguish responsibility
assigned by the article from independently established responsibility; do not invent
an unnamed actor or assume passive grammar alone proves an ideological pattern.
""",
    "presuppositions_doctrine": """
The first sentence MUST explicitly state the idea your article accepts without
examining it, naming the actor, action, or policy concerned. State the actual idea
as a complete proposition, not just that the article makes an assumption.
State the exact proposition your article treats as true
without arguing for it. Name the actor, institution, action, or policy it concerns.
Explain what that assumption makes seem legitimate, necessary, or beyond questioning.
Show the labels, claims absorbed into narration, or other details that establish it,
and how the comparison exposes it. A topic or attitude such as "security matters"
is too vague unless the paragraph specifies whose security and what it permits.
""",
    "selective_criteria": """
The first sentence MUST explicitly state how your article judges a named action or
actor: what counts as success, failure, or acceptable cost, and which relevant test
receives less weight or is applied differently. Do not just say standards differ.
Name the actual standard used to judge a named actor, action,
or policy, and the relevant standard given less weight or applied differently.
Specify what counts as success, failure, legitimacy, or acceptable cost in each
article. State the unequal or narrowed test in the opening claim and support it
with concrete judgments from the texts. Do not claim a double standard unless the
actors or actions are sufficiently comparable; a hypothetical role reversal alone
is not evidence.
""",
    "suppressed_alternative": """
The first sentence MUST explicitly name the explanation or choice your article
presents and the specific alternative it leaves unexplored or dismisses. Do not
just say another perspective is missing.
Name the explanation or policy choice your article makes
available and the specific rival account or option it leaves unexplored. Identify
the actors and consequences involved, and show which comparison details make the
alternative plausible. Do not merely say "other perspectives are missing."
""",
    "smoke_and_discrepancies": """
The first sentence MUST explicitly identify either the distraction and the important
question it displaces, or the conflicting claims and who makes each one. Use only
the supported finding; do not force both a distraction and a factual discrepancy.
Identify the specific speculation or peripheral detail
that displaces a substantive question, or the exact disputed claim in the texts.
For a discrepancy, state who reports what about the same event and distinguish
an actual conflict from differences in timing or scope. Do not decide which is true
without evidence or label uncertainty itself as smoke.
""",
}

CATEGORY_SYNTHESIS_SYSTEM = """
You synthesize one ClearFrame category independently from every other category.

You receive one category name and only the article-pair analyses for that category.
Decide whether its evidence is strong enough to surface, then return an explicit
include-or-exclude decision.

Apply the supplied category-specific guide when writing the paragraph.

Background knowledge cannot substitute for an observed difference between the articles..

- Set "include" to true only if one or more comparison articles show a meaningful,
  text-supported difference that warrants a doctrinal inference, grounded in the paired
  source_article and comparison_article answers and the doctrine fields.
- Set "include" to false if the differences are weak, generic, unsupported, or not
  actually about a contrast with your article. Also exclude it when you can describe only
  a surface difference and cannot defend an underlying premise.
- When included, write exactly one concise paragraph.
- The first sentence MUST directly and explicitly answer the supplied category's
  question, following its category-specific guide. A reader who sees only that sentence
  must know the answer, including the relevant names, actions, harms, idea, standards,
  alternatives, or conflicting claims. Do not open with a general observation, an
  abstract interpretation, or a restatement of the question. Do not make readers infer
  the answer from later examples. Keep the answer in plain language; then use the
  remaining sentences for evidence, the underlying assumption, why the difference may
  exist, and what it leaves unexamined.
- Every main claim about how the articles present the story must be supported by at least
  one concrete example from the supplied articles. Background explanations may draw on
  your wider knowledge; identify them as context or possible causes, not article evidence.
  Name the actor, action, consequence, quoted phrase, or omitted question
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
- Aim for 5 to 7 short sentences per paragraph, roughly 100 to 150 words. Use more room
  when needed to preserve distinct evidence, counterexamples, or important qualifications.
- Base the paragraph on the source_article analysis, comparison_article analysis,
  difference, underlying_presupposition, doctrinal_boundary, comparison_revelation,
  interest_alignment, inference_strength, source_basis, and comparison_basis fields.
- In the paragraph, describe comparison articles by source_country, not by URL or
  outlet domain. For example, write "articles from Oman and Iran", not
  "articles from omanobserver.om and iranherald.com".
- Put the exact articles used in the supporting_articles list.

Before returning, check each paragraph: could a reader understand it without knowing media
theory, and can the reader distinguish the article evidence for its main finding from
the background knowledge used to explain it?
If either answer is no, rewrite it in plainer and more concrete terms.
Read only the first sentence: does it explicitly answer this category's question,
with the specifics required by its guide? If the reader must guess or read further
to find that answer, rewrite the opening. The rest of the paragraph must support
and explain that answer.
Could the reader name the affected groups, actor-action relationship, assumed proposition,
or evaluative standards relevant to this category? If not, rewrite the finding with
those specifics. If the evidence cannot supply them, exclude the category.

When include is false, leave the claim, paragraph, examples, and supporting_articles empty
and give a short exclusion_reason. Return ONLY valid JSON, no markdown fences:
{
  "include": true,
  "doctrinal_claim": "<one sentence naming the tacit premise in your article>",
  "paragraph": "<one paragraph whose first sentence explicitly answers the category question, followed by evidence and explanation of the assumption and its consequences>",
  "examples": [
    "<specific example from your article and why it supports the claim>",
    "<specific example from a comparison article and why it exposes the taken-for-granted idea>"
  ],
  "supporting_articles": [
    {"title": "<title>", "outlet": "<domain>", "source_country": "<country>", "url": "<url>"}
  ],
  "exclusion_reason": ""
}
""" + COUNTRY_CONTEXT_GUIDANCE + READER_OUTPUT_GUIDANCE

OVERALL_SUMMARY_SYSTEM = """
You write ClearFrame's overall synthesis of what the category analysis reveals beneath
news coverage, using Herman and Chomsky's propaganda-model approach.

The pipeline has already compared the articles, identified observable differences, and
inferred the assumptions those differences expose. You receive all included category
findings, including doctrinal_claim, explanatory paragraphs, and supporting evidence.
Your task is to connect those analytic findings into one accessible narrative about
what readers are encouraged to accept, whose interests and costs count, and which
questions or alternatives receive little room. Summarize the analysis, not the articles.

Analytic purpose:
- Explain what must be taken for granted for those choices to seem natural, and how
  that premise narrows the judgments or possible solutions readers are offered.
- Begin with the broad, supported assumption or tension exposed across the findings.
  Make the opening concrete about the actors, authority, harms, or choices involved.
  Do not open with "the coverage offers different perspectives" or an event recap.
- Connect related category findings into a coherent explanation of how those assumptions
  work together. Do not march through categories or repeat their individual talking points.
  Do not force every finding into one assumption if the analysis supports distinct ones.
- Use the range of supported viewpoints to expose assumptions that would be harder to
  see in isolation. Explain how a competing premise changes who must justify an action,
  what counts as an acceptable cost, or which choices seem available. Include meaningful
  disagreements among comparison viewpoints; do not cherry-pick a convenient opponent
  or flatten all other coverage into a single alternative.
- Distinguish shared assumptions from competing assumptions. Coverage can disagree on
  tactics while accepting the same authority or goals, but infer that shared premise
  only when the category findings support it. Do not manufacture a hidden consensus.

Keep the narrative at the level of interpretation:
- Do not recount the event, summarize what each article says, catalog factual disputes,
  repeat quotations, or walk through examples.
  Include only enough concrete context to identify the assumption and its consequences.
- Do not organize sentences as "your article reports X; coverage from A says Y; coverage
  from B adds Z." Organize them around what the comparison reveals about authority,
  responsibility, acceptable costs, or the limits of the explanations offered.
- A statement such as "one article emphasizes security while another emphasizes harm"
  is only an observation. The synthesis must explain the supported assumption behind
  that difference and what it makes easier to accept or harder to question.

Length, language, and accuracy:
- Write exactly one connected paragraph, aiming for 200 to 250 words. Use less when the
  findings do not support that length. Do not pad with background, repetition, or recap.
- Refer to the user's source as "your article". Identify comparison viewpoints by their
  underlying assumptions; use country names to distinguish them.
- Use all included findings to assess the meaningful range of interpretations. Group
  overlapping findings, retain important tensions, and preserve uncertainty and
  counterexamples that limit the conclusion. Breadth does not require equal space for
  every article or treating every claim as equally credible.
- Do not include citations, reference markers, URLs, headings, bullets, or article rankings.

Before returning, check: does the paragraph explain the assumptions and boundaries
revealed by comparing the coverage, or merely describe what the articles discuss?
If it could be written from a list of article summaries without the category analysis,
rewrite it. Each main sentence should advance an interpretation or explain its
consequences, rather than add another reported detail. Check that multiple supported
viewpoints inform the synthesis without turning it into an article-by-article survey.

Return ONLY valid JSON, no markdown fences:
{
  "summary": "<one plain-language narrative connecting the assumptions and limits exposed by the category findings>"
}
""" + COUNTRY_CONTEXT_GUIDANCE + READER_OUTPUT_GUIDANCE
