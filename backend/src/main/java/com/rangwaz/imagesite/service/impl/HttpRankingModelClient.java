package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.config.RecommendationProperties;
import com.rangwaz.imagesite.service.RankingModelClient;
import com.rangwaz.imagesite.service.RankingModelClient.HomeRankCandidate;
import com.rangwaz.imagesite.service.RankingModelClient.RankedHit;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;

/**
 * HTTP adapter for the Python recommendation model service.
 */
@Component
public class HttpRankingModelClient implements RankingModelClient {
    private final RecommendationProperties properties;
    private final RestClient restClient;

    /**
     * Creates the ranking model client.
     *
     * @param properties recommendation properties
     */
    public HttpRankingModelClient(RecommendationProperties properties) {
        this.properties = properties;
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(properties.getModelConnectTimeoutMs());
        requestFactory.setReadTimeout(properties.getModelReadTimeoutMs());
        this.restClient = RestClient.builder()
                .requestFactory(requestFactory)
                .baseUrl(properties.getModelServiceUrl())
                .build();
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
    @Override
    public List<RankedHit> rankHome(Long userId,
                                    String requestId,
                                    String refreshSeed,
                                    List<HomeRankCandidate> candidates,
                                    int limit) {
        if (!properties.isModelRankingEnabled() || candidates == null || candidates.isEmpty()) return List.of();
        try {
            HomeRankResponse response = restClient.post()
                    .uri("/rank/home")
                    .body(new HomeRankRequest(
                            userId,
                            "home",
                            requestId,
                            refreshSeed,
                            candidates,
                            Math.max(1, limit)
                    ))
                    .retrieve()
                    .body(HomeRankResponse.class);
            return hits(response);
        } catch (RestClientException ex) {
            return List.of();
        }
    }

    private List<RankedHit> hits(HomeRankResponse response) {
        if (response == null || response.hits() == null) return List.of();
        return response.hits().stream()
                .filter(hit -> hit.imageId() != null && hit.imageId() > 0)
                .map(hit -> new RankedHit(hit.imageId(), hit.score() == null ? 0 : hit.score(), hit.reason()))
                .toList();
    }

    private record HomeRankRequest(Long userId,
                                   String scene,
                                   String requestId,
                                   String refreshSeed,
                                   List<HomeRankCandidate> candidates,
                                   Integer limit) {
    }

    private record HomeRankResponse(String modelName, String modelVersion, List<ModelRankHit> hits) {
    }

    private record ModelRankHit(Long imageId, Double score, String reason) {
    }
}
