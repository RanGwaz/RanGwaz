package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.RecommendationMapper;
import com.rangwaz.imagesite.service.FeedService;
import com.rangwaz.imagesite.service.RankingModelClient;
import com.rangwaz.imagesite.service.RankingModelClient.HomeRankCandidate;
import com.rangwaz.imagesite.service.RankingModelClient.RankedHit;
import com.rangwaz.imagesite.service.VectorRecallClient;
import com.rangwaz.imagesite.service.VectorRecallClient.UserEvent;
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
    private static final int ANONYMOUS_FIRST_PAGE_POOL_SIZE = 180;
    private static final int MAX_CLIENT_EXCLUDE_IDS = 240;
    private static final int RECENT_HOME_EXCLUDE_LIMIT = 400;
    private static final int HOME_RECALL_MULTIPLIER = 2;
    private static final int SIMILAR_RECALL_MULTIPLIER = 4;
    private static final double ROUTE_VECTOR_WEIGHT = 0.38;
    private static final double ROUTE_TAG_WEIGHT = 0.2;
    private static final double ROUTE_TOPIC_WEIGHT = 0.14;
    private static final double ROUTE_CATEGORY_WEIGHT = 0.12;
    private static final double ROUTE_METADATA_WEIGHT = ROUTE_TAG_WEIGHT + ROUTE_TOPIC_WEIGHT + ROUTE_CATEGORY_WEIGHT;
    private static final double ROUTE_FOLLOW_WEIGHT = 0.08;
    private static final double ROUTE_GLOBAL_WEIGHT = 0.08;
    private static final double ANON_EXPLORATION_WEIGHT = 0.34;
    private static final double VISITOR_EXPLORATION_WEIGHT = 0.18;
    private static final double USER_EXPLORATION_WEIGHT = 0.12;

    private final ImageContentMapper imageContentMapper;
    private final RecommendationMapper recommendationMapper;
    private final BehaviorMapper behaviorMapper;
    private final VectorRecallClient vectorRecallClient;
    private final RankingModelClient rankingModelClient;
    private final ImageServiceImpl imageService;

    /**
     * Creates the feed service.
     *
     * @param imageContentMapper image content mapper
     * @param recommendationMapper recommendation mapper
     * @param behaviorMapper behavior mapper
     * @param vectorRecallClient vector recall client
     * @param rankingModelClient external ranking model client
     * @param imageService post service
     */
    public FeedServiceImpl(ImageContentMapper imageContentMapper,
                           RecommendationMapper recommendationMapper,
                           BehaviorMapper behaviorMapper,
                           VectorRecallClient vectorRecallClient,
                           RankingModelClient rankingModelClient,
                           ImageServiceImpl imageService) {
        this.imageContentMapper = imageContentMapper;
        this.recommendationMapper = recommendationMapper;
        this.behaviorMapper = behaviorMapper;
        this.vectorRecallClient = vectorRecallClient;
        this.rankingModelClient = rankingModelClient;
        this.imageService = imageService;
    }

    /**
     * Loads the home feed.
     *
     * @param userId optional user id
     * @param page page number
     * @param size page size
     * @param visitorId stable anonymous visitor id
     * @param feedSessionId stable frontend feed session id
     * @param refreshSeed seed used to keep one refresh's pagination stable
     * @return page response
     */
    @Override
    public PageResponse<ApiDtos.ImageView> home(Long userId,
                                                int page,
                                                int size,
                                                String visitorId,
                                                String feedSessionId,
                                                String refreshSeed,
                                                List<Long> excludeImageIds) {
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 60));
        int offset = (safePage - 1) * safeSize;
        int recallLimit = candidateLimit(offset, safeSize, HOME_RECALL_MULTIPLIER);
        String cleanedRefreshSeed = cleanText(refreshSeed);
        Set<Long> clientExcludedIds = cleanImageIds(excludeImageIds);
        Map<Long, RecallScore> recallScores = new LinkedHashMap<>();
        Set<Long> recentSeenIds = new HashSet<>(clientExcludedIds);
        String profileVisitorId = userId == null ? cleanVisitorId(visitorId) : null;
        boolean hasProfileKey = userId != null || profileVisitorId != null;
        boolean firstAnonymousPage = userId == null && safePage == 1;
        boolean hasPersonalizationHistory = userId != null
                || (profileVisitorId != null && behaviorMapper.hasRecentPositiveBehavior(null, profileVisitorId) > 0);
        if (firstAnonymousPage && !hasPersonalizationHistory) {
            List<ImageEntity> images = rankAnonymousFirstPage(
                    recommendationMapper.selectColdStart(0, firstPagePoolSize(safeSize)),
                    cleanedRefreshSeed,
                    clientExcludedIds,
                    safeSize
            );
            var records = imageService.toViews(images, "cold-start-refresh");
            return new PageResponse<>(records, totalEstimate(offset, safeSize, records.size()), safePage, safeSize);
        }
        if (hasProfileKey) {
            List<UserEvent> recentEvents = behaviorMapper.findRecentBehaviorSequence(userId, profileVisitorId, 120).stream()
                    .filter(row -> row.getImageId() != null)
                    .map(row -> new UserEvent(row.getImageId(), row.getBehaviorType(), row.getDurationMs(), row.getAgeHours()))
                    .toList();
            List<Long> seedImageIds = behaviorMapper.findRecentPositiveImageIds(userId, profileVisitorId, 40);
            if (!recentEvents.isEmpty() || !seedImageIds.isEmpty()) {
                List<VectorHit> vectorHits = vectorRecallClient.feed(
                        userId,
                        recentEvents,
                        seedImageIds,
                        0,
                        recallLimit
                );
                addVectorRecall(recallScores, vectorHits, ROUTE_VECTOR_WEIGHT, "vector");
            }
            if (userId != null) {
                addRankedRecall(recallScores, recommendationMapper.selectFollowedAuthorRecall(userId, recallLimit), ROUTE_FOLLOW_WEIGHT, "follow");
            }
            if (!seedImageIds.isEmpty()) {
                addRankedRecall(recallScores, recommendationMapper.selectUserMetadataRecall(userId, profileVisitorId, recallLimit), ROUTE_METADATA_WEIGHT, "metadata");
            }
            recentSeenIds.addAll(behaviorMapper.findRecentSeenImageIds(userId, profileVisitorId, RECENT_HOME_EXCLUDE_LIMIT));
            recentSeenIds.addAll(clientExcludedIds);
        }
        boolean personalizedRecall = !recallScores.isEmpty();
        addRankedRecall(recallScores, recommendationMapper.selectColdStart(0, recallLimit), ROUTE_GLOBAL_WEIGHT, "global");
        HomeRankResult ranked = recallScores.isEmpty()
                ? new HomeRankResult(recommendationMapper.selectColdStart(offset, safeSize), false)
                : rankHome(imageContentMapper.findPublishedByIds(new ArrayList<>(recallScores.keySet())),
                recallScores,
                recentSeenIds,
                offset,
                safeSize,
                userId,
                requestId(feedSessionId, userId, safePage),
                cleanedRefreshSeed,
                explorationWeight(userId, profileVisitorId),
                !firstAnonymousPage || hasPersonalizationHistory);
        List<ImageEntity> images = ranked.images();
        String reason = ranked.modelUsed()
                ? "model-home"
                : (personalizedRecall ? "multi-recall-home" : "cold-start");
        if (images.isEmpty()) {
            images = recommendationMapper.selectColdStart(offset, safeSize);
            reason = "cold-start";
        }
        var records = imageService.toViews(images, reason);
        return new PageResponse<>(records, totalEstimate(offset, safeSize, records.size()), safePage, safeSize);
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
        List<ImageEntity> images = new ArrayList<>(rankSimilar(vectorHits, metadataSimilar, offset, safeSize));
        if (images.size() < safeSize) {
            fillSimilarFallback(postId, images, offset, safeSize);
        }
        var records = imageService.toViews(images, similarReason(vectorHits, metadataSimilar, images));
        return new PageResponse<>(records, imageContentMapper.countSimilar(postId), safePage, safeSize);
    }

    private int candidateLimit(int offset, int size, int multiplier) {
        return Math.min(MAX_RECALL_CANDIDATES, Math.max(size, offset + size * multiplier));
    }

    private int firstPagePoolSize(int size) {
        return Math.max(size, Math.min(ANONYMOUS_FIRST_PAGE_POOL_SIZE, size * 10));
    }

    private List<ImageEntity> rankAnonymousFirstPage(List<ImageEntity> pool,
                                                     String refreshSeed,
                                                     Set<Long> excludedIds,
                                                     int size) {
        if (pool == null || pool.isEmpty()) return List.of();
        Map<Long, Integer> globalRanks = new LinkedHashMap<>();
        for (int index = 0; index < pool.size(); index++) {
            ImageEntity image = pool.get(index);
            if (image.getId() != null) globalRanks.putIfAbsent(image.getId(), index);
        }
        List<ImageEntity> ranked = pool.stream()
                .filter(image -> image.getId() != null)
                .sorted(Comparator
                        .comparingDouble((ImageEntity image) -> anonymousFirstPageScore(
                                image,
                                globalRanks.getOrDefault(image.getId(), pool.size()),
                                refreshSeed,
                                excludedIds.contains(image.getId())
                        )).reversed()
                        .thenComparing(ImageEntity::getPublishedAt, Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(ImageEntity::getId, Comparator.nullsLast(Comparator.reverseOrder())))
                .toList();
        return ranked.stream().limit(size).toList();
    }

    private double anonymousFirstPageScore(ImageEntity image, int rank, String refreshSeed, boolean recentlyShown) {
        return rankDecay(rank) * 0.34
                + engagementScore(image) * 0.22
                + freshnessScore(image) * 0.16
                + metadataQualityScore(image) * 0.08
                + seedJitter(refreshSeed, image.getId()) * 0.20
                - (recentlyShown ? 1.0 : 0);
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

    private HomeRankResult rankHome(List<ImageEntity> candidates,
                                    Map<Long, RecallScore> recallScores,
                                    Set<Long> recentSeenIds,
                                    int offset,
                                    int size,
                                    Long userId,
                                    String requestId,
                                    String refreshSeed,
                                    double explorationWeight,
                                    boolean allowExternalRanking) {
        List<ImageEntity> fallbackOrder = candidates.stream()
                .filter(image -> image.getId() != null)
                .sorted(Comparator
                        .comparingDouble((ImageEntity image) -> homeScore(
                                image,
                                recallScores,
                                recentSeenIds,
                                refreshSeed,
                                explorationWeight
                        )).reversed()
                        .thenComparing(ImageEntity::getPublishedAt, Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(ImageEntity::getId, Comparator.nullsLast(Comparator.reverseOrder())))
                .toList();
        List<RankedHit> modelHits = allowExternalRanking
                ? rankingModelClient.rankHome(
                userId,
                requestId,
                refreshSeed,
                modelCandidates(fallbackOrder, recallScores, recentSeenIds),
                fallbackOrder.size()
        )
                : List.of();
        if (modelHits != null && !modelHits.isEmpty()) {
            return new HomeRankResult(pageSlice(mergeModelOrder(modelHits, fallbackOrder), offset, size), true);
        }
        return new HomeRankResult(pageSlice(fallbackOrder, offset, size), false);
    }

    private long totalEstimate(int offset, int size, int recordCount) {
        if (recordCount < size) return offset + recordCount;
        return offset + recordCount + size;
    }

    private List<HomeRankCandidate> modelCandidates(List<ImageEntity> orderedCandidates,
                                                    Map<Long, RecallScore> recallScores,
                                                    Set<Long> recentSeenIds) {
        List<HomeRankCandidate> candidates = new ArrayList<>();
        int position = 0;
        for (ImageEntity image : orderedCandidates) {
            RecallScore recall = recallScores.get(image.getId());
            candidates.add(new HomeRankCandidate(
                    image.getId(),
                    recall == null ? 0 : recall.score(),
                    recall == null ? 0 : recall.routeCount(),
                    recall == null ? null : recall.primaryRoute(),
                    engagementScore(image),
                    freshnessScore(image),
                    metadataQualityScore(image),
                    recentSeenIds.contains(image.getId()),
                    image.getAuthorId(),
                    image.getMainCategoryId(),
                    image.getRatio(),
                    position
            ));
            position++;
        }
        return candidates;
    }

    private List<ImageEntity> mergeModelOrder(List<RankedHit> modelHits, List<ImageEntity> fallbackOrder) {
        Map<Long, ImageEntity> byId = new LinkedHashMap<>();
        for (ImageEntity image : fallbackOrder) {
            byId.put(image.getId(), image);
        }
        List<ImageEntity> ordered = new ArrayList<>();
        Set<Long> added = new HashSet<>();
        for (RankedHit hit : modelHits) {
            ImageEntity image = byId.get(hit.imageId());
            if (image == null || added.contains(image.getId())) continue;
            ordered.add(image);
            added.add(image.getId());
        }
        for (ImageEntity image : fallbackOrder) {
            if (added.add(image.getId())) ordered.add(image);
        }
        return ordered;
    }

    private List<ImageEntity> pageSlice(List<ImageEntity> ordered, int offset, int size) {
        if (offset >= ordered.size()) return List.of();
        return ordered.stream().skip(offset).limit(size).toList();
    }

    private double homeScore(ImageEntity image,
                             Map<Long, RecallScore> recallScores,
                             Set<Long> recentSeenIds,
                             String refreshSeed,
                             double explorationWeight) {
        RecallScore recall = recallScores.get(image.getId());
        double recallScore = recall == null ? 0 : recall.score();
        double routeBonus = recall == null ? 0 : Math.min(0.08, recall.routeCount() * 0.02);
        double seenPenalty = recentSeenIds.contains(image.getId()) ? 0.72 : 0;
        return recallScore
                + routeBonus
                + engagementScore(image) * 0.12
                + freshnessScore(image) * 0.08
                + metadataQualityScore(image) * 0.02
                + seedJitter(refreshSeed, image.getId()) * explorationWeight
                - seenPenalty;
    }

    private double seedJitter(String refreshSeed, Long imageId) {
        if (refreshSeed == null || refreshSeed.isBlank() || imageId == null) return 0;
        return (Integer.toUnsignedLong(Objects.hash(refreshSeed, imageId)) % 10_000L) / 10_000D;
    }

    private double explorationWeight(Long userId, String visitorId) {
        if (userId != null) return USER_EXPLORATION_WEIGHT;
        if (visitorId != null) return VISITOR_EXPLORATION_WEIGHT;
        return ANON_EXPLORATION_WEIGHT;
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

    private void fillSimilarFallback(Long postId, List<ImageEntity> images, int offset, int size) {
        Set<Long> seen = new HashSet<>();
        for (ImageEntity image : images) {
            if (image.getId() != null) seen.add(image.getId());
        }
        seen.add(postId);
        int fallbackLimit = Math.max(size * 3, size + 12);
        for (ImageEntity image : recommendationMapper.selectSimilarFallback(postId, offset, fallbackLimit)) {
            if (image.getId() == null || seen.contains(image.getId())) continue;
            images.add(image);
            seen.add(image.getId());
            if (images.size() >= size) break;
        }
    }

    private double similarScore(ImageEntity image, Map<Long, Double> recallScores) {
        return recallScores.getOrDefault(image.getId(), 0D)
                + engagementScore(image) * 0.025
                + freshnessScore(image) * 0.015;
    }

    private String similarReason(List<VectorHit> vectorHits, List<ImageEntity> metadataSimilar, List<ImageEntity> rankedImages) {
        boolean hasVector = vectorHits.stream().map(VectorHit::imageId).anyMatch(Objects::nonNull);
        boolean hasMetadata = metadataSimilar.stream().map(ImageEntity::getId).anyMatch(Objects::nonNull);
        boolean hasFallback = !rankedImages.isEmpty() && !hasVector && !hasMetadata;
        if (hasVector && hasMetadata) return "similar-vector-tags";
        if (hasVector) return "similar-vector";
        if (hasMetadata) return "similar-tags";
        if (hasFallback) return "similar-fallback";
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

    private String requestId(String feedSessionId, Long userId, int page) {
        String cleaned = cleanText(feedSessionId);
        if (cleaned != null) return cleaned;
        return "home-" + (userId == null ? "anon" : userId) + "-" + page;
    }

    private String cleanText(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim();
    }

    private Set<Long> cleanImageIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) return Set.of();
        Set<Long> cleaned = new HashSet<>();
        for (Long id : ids) {
            if (id == null || id <= 0) continue;
            cleaned.add(id);
            if (cleaned.size() >= MAX_CLIENT_EXCLUDE_IDS) break;
        }
        return cleaned;
    }

    private String cleanVisitorId(String value) {
        String cleaned = cleanText(value);
        if (cleaned == null) return null;
        return cleaned.length() > 64 ? cleaned.substring(0, 64) : cleaned;
    }

    private record HomeRankResult(List<ImageEntity> images, boolean modelUsed) {
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
