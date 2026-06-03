package com.rangwaz.imagesite.service;

import java.util.List;

/**
 * Interface for vector recall.
 */
public interface VectorRecallClient {
    /**
     * One vector recall hit.
     *
     * @param imageId image id
     * @param score vector similarity score
     */
    record VectorHit(Long imageId, double score) {
    }

    /**
     * Recalls personalized feed candidates from user seed images.
     *
     * @param userId optional user id
     * @param seedImageIds recent positive image ids
     * @param offset result offset
     * @param limit result limit
     * @return recalled image ids ordered by vector score
     */
    List<VectorHit> feed(Long userId, List<Long> seedImageIds, int offset, int limit);

    /**
     * Recalls images similar to a source image.
     *
     * @param imageId source image id
     * @param offset result offset
     * @param limit result limit
     * @return recalled image ids ordered by vector score
     */
    List<VectorHit> similar(Long imageId, int offset, int limit);
}
