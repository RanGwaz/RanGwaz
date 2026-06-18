package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.config.RecommendationProperties;
import com.rangwaz.imagesite.service.VectorRecallClient;
import com.rangwaz.imagesite.service.VectorRecallClient.UserEvent;
import com.rangwaz.imagesite.service.VectorRecallClient.VectorHit;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
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
    private final RestClient vectorRestClient;
    private final RestClient modelRestClient;

    /**
     * Creates the vector recall client.
     *
     * @param properties recommendation properties
     */
    public HttpVectorRecallClient(RecommendationProperties properties) {
        this.properties = properties;
        SimpleClientHttpRequestFactory vectorRequestFactory = new SimpleClientHttpRequestFactory();
        vectorRequestFactory.setConnectTimeout(800);
        vectorRequestFactory.setReadTimeout(2000);
        this.vectorRestClient = RestClient.builder()
                .requestFactory(vectorRequestFactory)
                .baseUrl(properties.getVectorServiceUrl())
                .build();
        SimpleClientHttpRequestFactory modelRequestFactory = new SimpleClientHttpRequestFactory();
        modelRequestFactory.setConnectTimeout(properties.getModelConnectTimeoutMs());
        modelRequestFactory.setReadTimeout(properties.getModelReadTimeoutMs());
        this.modelRestClient = RestClient.builder()
                .requestFactory(modelRequestFactory)
                .baseUrl(properties.getModelServiceUrl())
                .build();
    }

    /**
     * Recalls personalized feed candidates from user seed images.
     *
     * @param userId optional user id
     * @param recentEvents recent behavior sequence
     * @param seedImageIds recent positive image ids
     * @param offset result offset
     * @param limit result limit
     * @return recalled hits ordered by vector score
     */
    @Override
    public List<VectorHit> feed(Long userId,
                                List<UserEvent> recentEvents,
                                List<Long> seedImageIds,
                                int offset,
                                int limit) {
        boolean noSeeds = seedImageIds == null || seedImageIds.isEmpty();
        boolean noEvents = recentEvents == null || recentEvents.isEmpty();
        if (!properties.isVectorEnabled() || (noSeeds && noEvents)) return List.of();
        if (!properties.isModelRecallEnabled() && noSeeds) return List.of();
        List<Long> safeSeedImageIds = noSeeds ? List.of() : seedImageIds;
        try {
            VectorRecallResponse response = properties.isModelRecallEnabled()
                    ? modelRestClient.post()
                    .uri("/recall/home")
                    .body(new ModelFeedRecallRequest(
                            userId,
                            recentEvents == null ? List.of() : recentEvents,
                            safeSeedImageIds,
                            List.of(),
                            Math.max(0, offset),
                            Math.max(1, limit),
                            null
                    ))
                    .retrieve()
                    .body(VectorRecallResponse.class)
                    : vectorRestClient.post()
                    .uri("/recall/feed")
                    .body(new FeedRecallRequest(userId, safeSeedImageIds, Math.max(0, offset), Math.max(1, limit)))
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
            VectorRecallResponse response = vectorRestClient.post()
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

    private record ModelFeedRecallRequest(Long userId,
                                          List<UserEvent> events,
                                          List<Long> seedImageIds,
                                          List<Long> excludeImageIds,
                                          int offset,
                                          int limit,
                                          String refreshSeed) {
    }

    private record SimilarRecallRequest(Long imageId, int offset, int limit) {
    }

    private record VectorRecallResponse(List<RecallHit> hits) {
    }

    private record RecallHit(Long imageId, Double score) {
    }
}
