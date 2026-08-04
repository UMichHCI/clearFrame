import pandas as pd

from .config import MAX_FULLTEXT_CANDIDATES
from .stage1_fetch import get_article_text
from .stage2_query_plan import normalize_country
def fetch_candidate_texts(candidates_df: pd.DataFrame, indices: list[int],
                          event_country: str,
                          max_candidates: int = MAX_FULLTEXT_CANDIDATES) -> pd.DataFrame:
    """
    Fetches full text for the given candidate row indices.

    Ordering: candidates whose sourcecountry matches the event country come first,
    then GDELT's original order. Full text is fetched sequentially for the first
    max_candidates. Candidates whose fetch returns empty text are dropped.

    In "metadata" gate mode, `indices` are the candidates that passed the gate.
    In "fulltext" gate mode, `indices` are all candidates (the gate runs afterward
    on the text this fetches).

    Returns a DataFrame with an `article_text` column and a `row_index` column
    pointing back into candidates_df.
    """
    if not indices or candidates_df.empty:
        return pd.DataFrame()

    event_ctry = normalize_country(event_country)

    def is_local(idx: int) -> bool:
        row = candidates_df.iloc[idx]
        return normalize_country(str(row.get("sourcecountry", ""))) == event_ctry

    # Stable sort: local sources first, GDELT order preserved within each group.
    ordered = sorted(indices, key=lambda idx: 0 if is_local(idx) else 1)
    n_local = sum(1 for idx in indices if is_local(idx))

    print(f"      {len(indices)} candidate(s) to fetch "
          f"({n_local} local to {event_country}, {len(indices) - n_local} non-local).")
    print(f"      Fetching full text for up to {max_candidates}, local sources first.")

    to_fetch = ordered[:max_candidates]
    rows: list[dict] = []

    for n, idx in enumerate(to_fetch, start=1):
        row    = candidates_df.iloc[idx]
        url    = str(row.get("url", ""))
        title  = str(row.get("title", ""))
        domain = str(row.get("domain", ""))
        tag    = "local" if is_local(idx) else "non-local"

        print(f"      [{n}/{len(to_fetch)}] ({tag}) {domain} â€” {title[:55]}...")
        text, _pub_date = get_article_text(url)

        if not text or not text.strip():
            print("           -> dropped: no text retrieved.")
            continue

        record = row.to_dict()
        record["row_index"]    = idx
        record["article_text"] = text
        record["is_local"]     = is_local(idx)
        rows.append(record)
        print(f"           -> {len(text)} characters.")

    if not rows:
        print("      No candidate yielded usable full text.")
        return pd.DataFrame()

    print(f"      {len(rows)} candidate(s) have usable full text.")
    return pd.DataFrame(rows).reset_index(drop=True)

