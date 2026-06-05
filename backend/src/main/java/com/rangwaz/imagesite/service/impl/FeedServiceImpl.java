package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.RecommendationMapper;
import com.rangwaz.imagesite.service.FeedService;
import com.rangwaz.imagesite.service.VectorRecallClient;
import com.rangwaz.imagesite.service.VectorRecallClient.VectorHit;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Feed service that separates personalized home ranking from detail-page similarity.
 */
@Service
public class FeedServiceImpl implements FeedService {
    private static final int MAX_RECALL_CANDIDATES = 240;
    private static final int HOME_RECALL_MULTIPLIER = 5;
    private static final int SIMILAR_RECALL_MULTIPLIER = 4;
    private static final double ROUTE_VECTOR_WEIGHT = 0.38;
    private static final double ROUTE_TAG_WEIGHT = 0.2;
    private static final double ROUTE_TOPIC_WEIGHT = 0.14;
    private static final double ROUTE_CATEGORY_WEIGHT = 0.12;
    private static final double ROUTE_FOLLOW_WEIGHT = 0.08;
    private static final double ROUTE_GLOBAL_WEIGHT = 0.08;

    private final ImageContentMapper imageContentMapper;
    private final RecommendationMapper recommendationMapper;
    private final BehaviorMapper behaviorMapper;
    private final VectorRecallClient vectorRecallClient;
    private final ImageServiceImpl imageService;

    /**
     * Creates the feed service.
     *
     * @param imageContentMapper image content mapper
     * @param recommendationMapper recommendation mapper
     * @param behaviorMapper behavior mapper
     * @param vectorRecallClient vector recall client
     * @param imageService post service
     */
    public FeedServiceImpl(ImageContentMapper imageContentMapper,
                           RecommendationMapper recommendationMapper,
                           BehaviorMapper behaviorMapper,
                           VectorRecallClient vectorRecallClient,
                           ImageServiceImpl imageService) {
        this.imageContentMapper = imageContentMapper;
        this.recommendationMapper = recommendationMapper;
        this.behaviorMapper = behaviorMapper;
        this.vectorRecallClient = vectorRecallClient;
        this.imageService = imageService;
    }

    /**
     * Loads the home feed.
     *
     * @param userId optional user id
     * @param page page number
     * @param size page size
     * @return page response
     */
    @Override
    public PageResponse<ApiDtos.ImageView> home(Long userId, int page, int size) {
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        int recallLimit = candidateLimit(offset, safeSize, HOME_RECALL_MULTIPLIER);
        Map<Long, RecallScore> recallScores = new LinkedHashMap<>();
        Set<Long> recentSeenIds = Set.of();
        if (userId != null) {
            List<Long> seedImageIds = behaviorMapper.findRecentPositiveImageIds(userId, 40);
            List<VectorHit> vectorHits = vectorRecallClient.feed(
                    userId,
                    seedImageIds,
                    0,
                    recallLimit
            );
            addVectorRecall(recallScores, vectorHits, ROUTE_VECTOR_WEIGHT, "vector");
            addRankedRecall(recallScores, recommendationMapper.selectUserTagRecall(userId, recallLimit), ROUTE_TAG_WEIGHT, "tag");
            addRankedRecall(recallScores, recommendationMapper.selectUserTopicRecall(userId, recallLimit), ROUTE_TOPIC_WEIGHT, "topic");
            addRankedRecall(recallScores, recommendationMapper.selectUserCategoryRecall(userId, recallLimit), ROUTE_CATEGORY_WEIGHT, "category");
            addRankedRecall(recallScores, recommendationMapper.selectFollowedAuthorRecall(userId, recallLimit), ROUTE_FOLLOW_WEIGHT, "follow");
            recentSeenIds = new HashSet<>(behaviorMapper.findRecentSeenImageIds(userId, 1200));
        }
        addRankedRecall(recallScores, recommendationMapper.selectColdStart(0, recallLimit), ROUTE_GLOBAL_WEIGHT, "global");
        List<ImageEntity> images = recallScores.isEmpty()
                ? recommendationMapper.selectColdStart(offset, safeSize)
                : rankHome(imageContentMapper.findPublishedByIds(new ArrayList<>(recallScores.keySet())),
                recallScores,
                recentSeenIds,
                offset,
                safeSize);
        String reason = userId == null || recallScores.isEmpty() ? "cold-start" : "multi-recall-home";
        if (images.isEmpty()) {
            images = recommendationMapper.selectColdStart(offset, safeSize);
            reason = "cold-start";
        }
        var records = imageService.toViews(images, reason);
        return new PageResponse<>(records, imageContentMapper.countPublished(), safePage, safeSize);
    }

    /**
     * Loads posts similar to a detail post.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return page response
     */
    @Override
    public PageResponse<ApiDtos.ImageView> similar(Long postId, int page, int size) {
        imageService.requirePost(postId);
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        int candidateLimit = candidateLimit(offset, safeSize, SIMILAR_RECALL_MULTIPLIER);
        List<VectorHit> vectorHits = vectorRecallClient.similar(postId, 0, candidateLimit);
        List<ImageEntity> metadataSimilar = recommendationMapper.selectSimilarByMetadata(postId, 0, candidateLimit);
        List<ImageEntity> images = rankSimilar(vectorHits, metadataSimilar, offset, safeSize);
        var records = imageService.toViews(images, similarReason(vectorHits, metadataSimilar));
        return new PageResponse<>(records, imageContentMapper.countSimilar(postId), safePage, safeSize);
    }

    private int candidateLimit(int offset, int size, int multiplier) {
        return Math.min(MAX_RECALL_CANDIDATES, Math.max(size, offset + size * multiplier));
    }

    private List<Long> hitIds(List<VectorHit> hits) {
        return hits.stream()
                .map(VectorHit::imageId)
                .filter(id -> id != null && id > 0)
                .distinct()
                .toList();
    }

    private Map<Long, Double> scoreMap(List<VectorHit> hits) {
        Map<Long, Double> scores = new LinkedHashMap<>();
        for (VectorHit hit : hits) {
            if (hit.imageId() != null && hit.imageId() > 0) {
                scores.putIfAbsent(hit.imageId(), cleanScore(hit.score()));
            }
        }
        return scores;
    }

    private void addVectorRecall(Map<Long, RecallScore> scores,
                                 List<VectorHit> hits,
                                 double routeWeight,
                                 String route) {
        int rank = 0;
        for (VectorHit hit : hits) {
            if (hit.imageId() != null && hit.imageId() > 0) {
                double contribution = routeWeight * (cleanScore(hit.score()) * 0.85 + rankDecay(rank) * 0.15);
                scores.computeIfAbsent(hit.imageId(), RecallScore::new).add(route, contribution);
                rank++;
            }
        }
    }

    private void addRankedRecall(Map<Long, RecallScore> scores,
                                 List<ImageEntity> images,
                                 double routeWeight,
                                 String route) {
        int rank = 0;
        for (ImageEntity image : images) {
            if (image.getId() != null) {
                double contribution = routeWeight * rankDecay(rank);
                scores.computeIfAbsent(image.getId(), RecallScore::new).add(route, contribution);
                rank++;
            }
        }
    }

    private List<ImageEntity> rankHome(List<ImageEntity> candidates,
                                       Map<Long, RecallScore> recallScores,
                                       Set<Long> recentSeenIds,
                                       int offset,
                                       int size) {
        return candidates.stream()
                .filter(image -> image.getId() != null)
                .sorted(Comparator
                        .comparingDouble((ImageEntity image) -> homeScore(image, recallScores, recentSeenIds)).reversed()
                        .thenComparing(ImageEntity::getPublishedAt, Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(ImageEntity::getId, Comparator.nullsLast(Comparator.reverseOrder())))
                .skip(offset)
                .limit(size)
                .toList();
    }

    private double homeScore(ImageEntity image, Map<Long, RecallScore> recallScores, Set<Long> recentSeenIds) {
        RecallScore recall = recallScores.get(image.getId());
        double recallScore = recall == null ? 0 : recall.score();
        double routeBonus = recall == null ? 0 : Math.min(0.08, recall.routeCount() * 0.02);
        double seenPenalty = recentSeenIds.contains(image.getId()) ? 0.28 : 0;
        return recallScore
                + routeBonus
                + engagementScore(image) * 0.12
                + freshnessScore(image) * 0.08
                + metadataQualityScore(image) * 0.02
                - seenPenalty;
    }

    private List<ImageEntity> rankSimilar(List<VectorHit> vectorHits,
                                          List<ImageEntity> metadataSimilar,
                                          int offset,
                                          int size) {
        Map<Long, Double> scores = new LinkedHashMap<>();
        int rank = 0;
        for (VectorHit hit : vectorHits) {
            if (hit.imageId() != null && hit.imageId() > 0) {
                scores.merge(hit.imageId(), cleanScore(hit.score()) * 0.76 + rankDecay(rank) * 0.06, Double::sum);
                rank++;
            }
        }
        rank = 0;
        for (ImageEntity image : metadataSimilar) {
            if (image.getId() != null) {
                scores.merge(image.getId(), rankDecay(rank) * 0.24, Double::sum);
                rank++;
            }
        }
        if (scores.isEmpty()) {
            return List.of();
        }
        List<ImageEntity> candidates = imageContentMapper.findPublishedByIds(List.copyOf(scores.keySet()));
        return candidates.stream()
                .filter(image -> image.getId() != null)
                .sorted(Comparator
                        .comparingDouble((ImageEntity image) -> similarScore(image, scores)).reversed()
                        .thenComparing(ImageEntity::getPublishedAt, Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(ImageEntity::getId, Comparator.nullsLast(Comparator.reverseOrder())))
                .skip(offset)
                .limit(size)
                .toList();
    }

    private double similarScore(ImageEntity image, Map<Long, Double> recallScores) {
        return recallScores.getOrDefault(image.getId(), 0D)
                + engagementScore(image) * 0.025
                + freshnessScore(image) * 0.015;
    }

    private String similarReason(List<VectorHit> vectorHits, List<ImageEntity> metadataSimilar) {
        boolean hasVector = vectorHits.stream().map(VectorHit::imageId).anyMatch(Objects::nonNull);
        boolean hasMetadata = metadataSimilar.stream().map(ImageEntity::getId).anyMatch(Objects::nonNull);
        if (hasVector && hasMetadata) return "similar-vector-tags";
        if (hasVector) return "similar-vector";
        if (hasMetadata) return "similar-tags";
        return "similar-empty";
    }

    private double rankDecay(int rank) {
        return 1D / Math.sqrt(rank + 1D);
    }

    private double cleanScore(double score) {
        if (Double.isNaN(score) || Double.isInfinite(score)) return 0;
        return Math.max(0, score);
    }

    private double engagementScore(ImageEntity image) {
        double hot = decimal(image.getHotScore());
        double interactions = safe(image.getLikeCount()) * 1.2
                + safe(image.getFavoriteCount()) * 1.6
                + safe(image.getCommentCount()) * 1.1
                + safe(image.getShareCount()) * 1.3
                + safe(image.getViewCount()) * 0.08;
        return Math.log1p(Math.max(0, hot + interactions)) / 10D;
    }

    private double freshnessScore(ImageEntity image) {
        LocalDateTime publishedAt = image.getPublishedAt();
        if (publishedAt == null) return 0;
        long hours = Math.max(0, Duration.between(publishedAt, LocalDateTime.now()).toHours());
        return 24D / (hours + 24D);
    }

    private double metadataQualityScore(ImageEntity image) {
        double score = 0;
        if (image.getDescription() != null && !image.getDescription().isBlank()) score += 0.4;
        if (image.getMainCategoryId() != null) score += 0.25;
        if (image.getRatio() != null && !image.getRatio().isBlank()) score += 0.15;
        if (image.getThumbnailUrl() != null && !image.getThumbnailUrl().isBlank()) score += 0.2;
        return score;
    }

    private int safe(Integer value) {
        return value == null ? 0 : Math.max(0, value);
    }

    private double decimal(BigDecimal value) {
        return value == null ? 0 : value.doubleValue();
    }

    private static final class RecallScore {
        private final Long imageId;
        private double score;
        private int routeCount;
        private String primaryRoute;
        private double primaryContribution;

        private RecallScore(Long imageId) {
            this.imageId = imageId;
        }

        private void add(String route, double contribution) {
            score += contribution;
            routeCount++;
            if (contribution > primaryContribution) {
                primaryContribution = contribution;
                primaryRoute = route;
            }
        }

        private double score() {
            return score;
        }

        private int routeCount() {
            return routeCount;
        }

        @SuppressWarnings("unused")
        private String primaryRoute() {
            return primaryRoute;
        }

        @SuppressWarnings("unused")
        private Long imageId() {
            return imageId;
        }
    }
}
