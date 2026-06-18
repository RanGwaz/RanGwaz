package com.rangwaz.imagesite.service;

import java.util.List;

/**
 * Adapter boundary for an external home-feed ranking model.
 */
public interface RankingModelClient {
    /**
     * Model features for one home-feed candidate.
     *
     * @param imageId image id
     * @param recallScore merged recall score from Java routes
     * @param routeCount number of recall routes that produced the item
     * @param primarySource strongest recall route
     * @param engagementScore normalized engagement feature
     * @param freshnessScore normalized freshness feature
     * @param metadataQualityScore normalized metadata quality feature
     * @param recentlySeen whether the user saw the item recently
     * @param authorId author id
     * @param categoryId main category id
     * @param ratio image ratio label
     * @param positionHint fallback rank position
     */
    record HomeRankCandidate(Long imageId,
                             double recallScore,
                             int routeCount,
                             String primarySource,
                             double engagementScore,
                             double freshnessScore,
                             double metadataQualityScore,
                             boolean recentlySeen,
                             Long authorId,
                             Long categoryId,
                             String ratio,
                             Integer positionHint) {
    }

    /**
     * One ranked model hit.
     *
     * @param imageId image id
     * @param score model score
     * @param reason model reason or route
     */
    record RankedHit(Long imageId, double score, String reason) {
    }

    /**
     * Ranks home-feed candidates.
     *
     * @param userId optional user id
     * @param requestId stable request/session id
     * @param refreshSeed seed used to keep one refresh's pagination stable
     * @param candidates candidate features
     * @param limit maximum hits expected
     * @return ranked hits ordered by model score
     */
    List<RankedHit> rankHome(Long userId,
                             String requestId,
                             String refreshSeed,
                             List<HomeRankCandidate> candidates,
                             int limit);
}
