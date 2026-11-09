def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    k: int = 60,
    top_k: int | None = None,
) -> list[dict]:
    """
    Fuse multiple ranked result lists using Reciprocal Rank Fusion.

    Example:
        BM25    -> 15
        Gemini  -> 15
                   |
                  RRF
                   |
             up to 30 unique chunks

    If top_k is None, the complete fused candidate pool is returned.
    """

    if not result_lists:
        return []

    if k <= 0:
        raise ValueError("RRF k must be greater than zero.")

    if top_k is not None and top_k <= 0:
        return []

    scores: dict[str, float] = {}
    result_map: dict[str, dict] = {}

    for list_index, results in enumerate(result_lists, start=1):
        if not results:
            continue

        seen_in_list: set[str] = set()

        for rank, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                continue

            chunk_id = result.get("chunk_id")

            if not chunk_id:
                continue

            if chunk_id in seen_in_list:
                continue

            seen_in_list.add(chunk_id)

            rrf_score = 1.0 / (k + rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + rrf_score

            if chunk_id not in result_map:
                result_map[chunk_id] = dict(result)
            else:
                existing = result_map[chunk_id]
                for key, value in result.items():
                    if key not in existing or existing.get(key) in (None, ""):
                        existing[key] = value

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    if top_k is None:
        selected = ranked
    else:
        selected = ranked[:top_k]

    final_results = []

    for fused_rank, (chunk_id, rrf_score) in enumerate(selected, start=1):
        result = dict(result_map[chunk_id])
        result["rrf_score"] = float(rrf_score)
        result["rrf_rank"] = fused_rank
        result["retriever"] = "rrf"
        final_results.append(result)

    return final_results
