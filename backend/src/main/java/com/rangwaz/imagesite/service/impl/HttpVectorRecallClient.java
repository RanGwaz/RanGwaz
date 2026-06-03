package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.config.RecommendationProperties;
import com.rangwaz.imagesite.service.VectorRecallClient;
import com.rangwaz.imagesite.service.VectorRecallClient.VectorHit;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;

/**
 * HTTP adapter for the Python Milvus recall service.
 */
@Component
public class HttpVectorRecallClient implements VectorRecallClient {
    private final RecommendationProperties properties;
    private final RestClient restClient;

    /**
     * Creates the vector recall client.
     *
     * @param properties recommendation properties
     */
    public HttpVectorRecallClient(RecommendationProperties properties) {
        this.properties = properties;
        this.restClient = RestClient.builder().baseUrl(properties.getVectorServiceUrl()).build();
    }

    /**
     * Recalls personalized feed candidates from user seed images.
     *
     * @param userId optional user id
     * @param seedImageIds recent positive image ids
     * @param offset result offset
     * @param limit result limit
     * @return recalled hits ordered by vector score
     */
    @Override
    public List<VectorHit> feed(Long userId, List<Long> seedImageIds, int offset, int limit) {
        if (!properties.isVectorEnabled() || seedImageIds == null || seedImageIds.isEmpty()) return List.of();
        try {
            VectorRecallResponse response = restClient.post()
                    .uri("/recall/feed")
                    .body(new FeedRecallRequest(userId, seedImageIds, Math.max(0, offset), Math.max(1, limit)))
                    .retrieve()
                    .body(VectorRecallResponse.class);
            return hits(response);
        } catch (RestClientException ex) {
            return List.of();
        }
    }

    /**
     * Recalls images similar to a source image.
     *
     * @param imageId source image id
     * @param offset result offset
     * @param limit result limit
     * @return recalled hits ordered by vector score
     */
    @Override
    public List<VectorHit> similar(Long imageId, int offset, int limit) {
        if (!properties.isVectorEnabled() || imageId == null) return List.of();
        try {
            VectorRecallResponse response = restClient.post()
                    .uri("/recall/similar")
                    .body(new SimilarRecallRequest(imageId, Math.max(0, offset), Math.max(1, limit)))
                    .retrieve()
                    .body(VectorRecallResponse.class);
            return hits(response);
        } catch (RestClientException ex) {
            return List.of();
        }
    }

    private List<VectorHit> hits(VectorRecallResponse response) {
        if (response == null || response.hits() == null) return List.of();
        return response.hits().stream()
                .filter(hit -> hit.imageId() != null && hit.imageId() > 0)
                .map(hit -> new VectorHit(hit.imageId(), hit.score() == null ? 0 : hit.score()))
                .toList();
    }

    private record FeedRecallRequest(Long userId, List<Long> seedImageIds, int offset, int limit) {
    }

    private record SimilarRecallRequest(Long imageId, int offset, int limit) {
    }

    private record VectorRecallResponse(List<RecallHit> hits) {
    }

    private record RecallHit(Long imageId, Double score) {
    }
}
