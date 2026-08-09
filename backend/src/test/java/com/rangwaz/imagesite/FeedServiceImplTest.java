package com.rangwaz.imagesite;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.RecommendationMapper;
import com.rangwaz.imagesite.service.RankingModelClient;
import com.rangwaz.imagesite.service.VectorRecallClient;
import com.rangwaz.imagesite.service.impl.FeedServiceImpl;
import com.rangwaz.imagesite.service.impl.ImageServiceImpl;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.scripting.xmltags.XMLLanguageDriver;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class FeedServiceImplTest {
    @Test
    void similarCosineThresholdConfigurationUsesClosedUnitInterval() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);

        assertDoesNotThrow(() -> new FeedServiceImpl(
                imageContentMapper, recommendationMapper, behaviorMapper,
                vectorRecallClient, rankingModelClient, imageService, 0.0
        ));
        assertDoesNotThrow(() -> new FeedServiceImpl(
                imageContentMapper, recommendationMapper, behaviorMapper,
                vectorRecallClient, rankingModelClient, imageService, 1.0
        ));
        assertThrows(IllegalArgumentException.class, () -> new FeedServiceImpl(
                imageContentMapper, recommendationMapper, behaviorMapper,
                vectorRecallClient, rankingModelClient, imageService, -0.01
        ));
        assertThrows(IllegalArgumentException.class, () -> new FeedServiceImpl(
                imageContentMapper, recommendationMapper, behaviorMapper,
                vectorRecallClient, rankingModelClient, imageService, 1.01
        ));
        assertThrows(IllegalArgumentException.class, () -> new FeedServiceImpl(
                imageContentMapper, recommendationMapper, behaviorMapper,
                vectorRecallClient, rankingModelClient, imageService, Double.NaN
        ));
    }

    @Test
    void similarUsesDefaultCosineThresholdAtInclusiveBoundary() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity belowThreshold = image(11L);
        ImageEntity atThreshold = image(12L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, 0.19),
                new VectorRecallClient.VectorHit(12L, 0.20)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 239)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(belowThreshold, atThreshold));
        when(recommendationMapper.selectSimilarFallback(10L, List.of(12L, 10L), 0, 239)).thenReturn(List.of());

        var page = feedService.similar(10L, 1, 2);

        assertEquals(1, page.total());
        verify(imageService).toViews(eq(List.of(atThreshold)), eq("similar-vector"));
    }

    @Test
    void similarRejectsNonPositiveAndNonFiniteVectorHitsBeforeFallback() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity negative = image(11L);
        ImageEntity zero = image(12L);
        ImageEntity nan = image(13L);
        ImageEntity infinite = image(14L);
        ImageEntity fallback = image(15L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, -0.8),
                new VectorRecallClient.VectorHit(12L, 0.0),
                new VectorRecallClient.VectorHit(13L, Double.NaN),
                new VectorRecallClient.VectorHit(14L, Double.POSITIVE_INFINITY)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 240)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList()))
                .thenReturn(List.of(negative, zero, nan, infinite));
        when(recommendationMapper.selectSimilarFallback(10L, List.of(10L), 0, 240))
                .thenReturn(List.of(fallback));

        var page = feedService.similar(10L, 1, 4);

        assertEquals(1, page.total());
        verify(imageService).toViews(eq(List.of(fallback)), eq("similar-fallback"));
    }

    @Test
    void similarSkipsMetadataAndFallbackWhenPositiveVectorPoolIsFull() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        List<VectorRecallClient.VectorHit> vectorHits = new ArrayList<>();
        List<ImageEntity> published = new ArrayList<>();
        for (int index = 0; index < 240; index++) {
            ImageEntity vectorImage = image(11L + index);
            vectorHits.add(new VectorRecallClient.VectorHit(vectorImage.getId(), 1.0 - index * 0.001));
            published.add(vectorImage);
        }
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(vectorHits);
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(published);

        var page = feedService.similar(10L, 1, 60);

        assertEquals(240, page.total());
        verify(recommendationMapper, never()).selectSimilarByMetadata(eq(10L), eq(0), anyInt());
        verify(recommendationMapper, never()).selectSimilarFallback(eq(10L), anyList(), eq(0), anyInt());
    }

    @Test
    void similarUsesRemainingCapacityForMetadataAndFallback() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity first = image(11L);
        ImageEntity second = image(12L);
        ImageEntity third = image(13L);
        ImageEntity fourth = image(14L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, 0.95),
                new VectorRecallClient.VectorHit(11L, 0.94),
                new VectorRecallClient.VectorHit(10L, 1.0),
                new VectorRecallClient.VectorHit(13L, 0.0),
                new VectorRecallClient.VectorHit(14L, Double.NaN),
                new VectorRecallClient.VectorHit(12L, 0.90)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 238)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(first, first, second));
        when(recommendationMapper.selectSimilarFallback(10L, List.of(11L, 12L, 10L), 0, 238))
                .thenReturn(List.of(second, third, fourth));

        var page = feedService.similar(10L, 1, 4);

        assertEquals(4, page.total());
        verify(recommendationMapper).selectSimilarByMetadata(10L, 0, 238);
        verify(recommendationMapper).selectSimilarFallback(10L, List.of(11L, 12L, 10L), 0, 238);
        verify(imageService).toViews(eq(List.of(first, second, third, fourth)), eq("similar-vector"));
    }

    @Test
    void similarExcludesSourceImageReturnedByVectorRecall() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity source = image(10L);
        ImageEntity related = image(11L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(10L, 1.0),
                new VectorRecallClient.VectorHit(11L, 0.9)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 239)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(source, related));

        feedService.similar(10L, 1, 1);

        verify(imageService).toViews(eq(List.of(related)), eq("similar-vector"));
    }

    @Test
    void similarTotalReflectsFiniteRecalledCandidatePool() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity first = image(11L);
        ImageEntity second = image(12L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, 0.95),
                new VectorRecallClient.VectorHit(12L, 0.90)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 238)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(first, second));
        when(imageContentMapper.countSimilar(10L)).thenReturn(100_000L);

        var page = feedService.similar(10L, 1, 1);

        assertEquals(2, page.total());
    }

    @Test
    void similarFallbackExcludesPrimaryPoolBeforeItsLimitedCandidateWindows() {
        Method fallbackMethod = Arrays.stream(RecommendationMapper.class.getMethods())
                .filter(method -> method.getName().equals("selectSimilarFallback"))
                .findFirst()
                .orElseThrow();
        Select select = fallbackMethod.getAnnotation(Select.class);
        String sql = String.join("\n", select.value());

        assertEquals(4, fallbackMethod.getParameterCount());
        assertFalse(sql.contains("hot_candidates"));
        assertTrue(sql.contains("i.main_category_id=src.main_category_id"));
        assertTrue(sql.contains("i.ratio=src.ratio"));
        assertEquals(2, sql.split("collection=\"excludeIds\"", -1).length - 1);
        assertTrue(sql.contains("i.id NOT IN"));
        String categoryWindow = sql.substring(
                sql.indexOf("category_candidates AS"),
                sql.indexOf("ratio_candidates AS")
        );
        String ratioWindow = sql.substring(
                sql.indexOf("ratio_candidates AS"),
                sql.indexOf("merged_candidates AS")
        );
        assertTrue(categoryWindow.contains("i.id NOT IN"));
        assertTrue(ratioWindow.contains("i.id NOT IN"));
        assertTrue(categoryWindow.indexOf("i.id NOT IN") < categoryWindow.indexOf("LIMIT #{size}"));
        assertTrue(ratioWindow.indexOf("i.id NOT IN") < ratioWindow.indexOf("LIMIT #{size}"));
        var sqlSource = new XMLLanguageDriver().createSqlSource(new Configuration(), sql, Map.class);
        var boundSql = sqlSource.getBoundSql(Map.of(
                "imageId", 10L,
                "excludeIds", List.of(10L, 11L, 12L),
                "offset", 0,
                "size", 5
        ));
        assertEquals(2, boundSql.getSql().split("i.id NOT IN", -1).length - 1);
        assertFalse(boundSql.getSql().contains("<foreach"));
    }

    @Test
    void similarKeepsStrongVectorCandidatesAheadOfMetadataOnlyCandidates() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity vectorCandidate = image(11L);
        ImageEntity metadataOnlyCandidate = image(12L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, 0.95)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 239))
                .thenReturn(List.of(metadataOnlyCandidate));
        when(imageContentMapper.findPublishedByIds(anyList()))
                .thenReturn(List.of(metadataOnlyCandidate, vectorCandidate));

        feedService.similar(10L, 1, 2);

        verify(imageService).toViews(
                eq(List.of(vectorCandidate, metadataOnlyCandidate)),
                eq("similar-vector-tags")
        );
    }

    @Test
    void similarDeepPageDoesNotInflateTotalWhenCandidatesAreExhausted() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of());
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 240)).thenReturn(List.of());
        when(recommendationMapper.selectSimilarFallback(10L, List.of(10L), 0, 240)).thenReturn(List.of());
        when(imageContentMapper.countSimilar(10L)).thenReturn(100_000L);

        var page = feedService.similar(10L, Integer.MAX_VALUE, 30);

        assertEquals(0, page.total());
        verify(recommendationMapper).selectSimilarByMetadata(10L, 0, 240);
    }

    @Test
    void similarUsesStableRecallPoolAndMergesFallbackWithoutCrossPageDuplicates() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity first = image(11L);
        ImageEntity second = image(12L);
        ImageEntity third = image(13L);
        ImageEntity fourth = image(14L);
        ImageEntity fifth = image(15L);
        ImageEntity sixth = image(16L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(List.of(
                new VectorRecallClient.VectorHit(11L, 0.99),
                new VectorRecallClient.VectorHit(12L, 0.90),
                new VectorRecallClient.VectorHit(13L, 0.80),
                new VectorRecallClient.VectorHit(14L, 0.70)
        ));
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 236)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(third, first, fourth, second));
        when(recommendationMapper.selectSimilarFallback(10L, List.of(11L, 12L, 13L, 14L, 10L), 0, 236))
                .thenReturn(List.of(first, fourth, fifth, sixth));

        var firstPage = feedService.similar(10L, 1, 2);
        var secondPage = feedService.similar(10L, 2, 2);
        var thirdPage = feedService.similar(10L, 3, 2);

        assertEquals(6, firstPage.total());
        assertEquals(6, secondPage.total());
        assertEquals(6, thirdPage.total());
        verify(imageService).toViews(eq(List.of(first, second)), eq("similar-vector"));
        verify(imageService).toViews(eq(List.of(third, fourth)), eq("similar-vector"));
        verify(imageService).toViews(eq(List.of(fifth, sixth)), eq("similar-fallback"));
    }

    @Test
    void similarPassesLargeOverlappingPrimaryPoolToFallbackExclusion() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        List<VectorRecallClient.VectorHit> vectorHits = new ArrayList<>();
        List<ImageEntity> overlappingMetadata = new ArrayList<>();
        List<ImageEntity> freshFallback = new ArrayList<>();
        List<Long> expectedExcludeIds = new ArrayList<>();
        for (int index = 0; index < 120; index++) {
            long primaryId = 11L + index;
            vectorHits.add(new VectorRecallClient.VectorHit(primaryId, 0.90 - index * 0.001));
            overlappingMetadata.add(image(primaryId));
            expectedExcludeIds.add(primaryId);
            freshFallback.add(image(1_000L + index));
        }
        expectedExcludeIds.add(10L);
        when(vectorRecallClient.similar(10L, 0, 240)).thenReturn(vectorHits);
        when(recommendationMapper.selectSimilarByMetadata(10L, 0, 120)).thenReturn(overlappingMetadata);
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(overlappingMetadata);
        when(recommendationMapper.selectSimilarFallback(10L, expectedExcludeIds, 0, 120))
                .thenReturn(freshFallback);

        var page = feedService.similar(10L, 1, 60);

        assertEquals(240, page.total());
        verify(recommendationMapper).selectSimilarFallback(10L, expectedExcludeIds, 0, 120);
    }

    @Test
    void anonymousFirstPageUsesFastGlobalPath() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity image = image(1L);
        ApiDtos.ImageView view = view(1L);
        when(recommendationMapper.selectColdStart(0, 180)).thenReturn(List.of(image));
        when(imageService.toViews(anyList(), eq("cold-start-refresh"))).thenReturn(List.of(view));

        var page = feedService.home(null, 1, 30, "visitor-a", "session-a", "seed-a", List.of());

        assertEquals(List.of(view), page.records());
        assertEquals(1, page.total());
        verify(behaviorMapper).hasRecentPositiveBehavior(null, "visitor-a");
        verifyNoInteractions(vectorRecallClient, rankingModelClient);
        verify(imageContentMapper, never()).findPublishedByIds(anyList());
        verify(imageContentMapper, never()).countPublished();
    }

    @Test
    void anonymousFirstPageAvoidsClientExcludedImages() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity excluded = image(1L);
        ImageEntity fresh = image(2L);
        ApiDtos.ImageView freshView = view(2L);
        when(recommendationMapper.selectColdStart(0, 10)).thenReturn(List.of(excluded, fresh));
        when(imageService.toViews(eq(List.of(fresh)), eq("cold-start-refresh"))).thenReturn(List.of(freshView));

        var page = feedService.home(null, 1, 1, "visitor-a", "session-a", "seed-a", List.of(1L));

        assertEquals(List.of(freshView), page.records());
    }

    @Test
    void userHomeDemotesRecentlyInteractedImages() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity interacted = image(1L);
        ImageEntity fresh = image(2L);
        ApiDtos.ImageView freshView = view(2L);
        when(behaviorMapper.findRecentBehaviorSequence(7L, null, 120)).thenReturn(List.of());
        when(behaviorMapper.findRecentPositiveImageIds(7L, null, 40)).thenReturn(List.of());
        when(behaviorMapper.findRecentSeenImageIds(7L, null, 400)).thenReturn(List.of(1L));
        when(recommendationMapper.selectFollowedAuthorRecall(7L, 2)).thenReturn(List.of());
        when(recommendationMapper.selectColdStart(0, 2)).thenReturn(List.of(interacted, fresh));
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(interacted, fresh));
        when(imageService.toViews(eq(List.of(fresh)), eq("cold-start"))).thenReturn(List.of(freshView));

        var page = feedService.home(7L, 1, 1, "visitor-a", "session-a", "seed-a", List.of());

        assertEquals(List.of(freshView), page.records());
    }

    @Test
    void returningVisitorFirstPageUsesVectorPersonalization() {
        ImageContentMapper imageContentMapper = mock(ImageContentMapper.class);
        RecommendationMapper recommendationMapper = mock(RecommendationMapper.class);
        BehaviorMapper behaviorMapper = mock(BehaviorMapper.class);
        VectorRecallClient vectorRecallClient = mock(VectorRecallClient.class);
        RankingModelClient rankingModelClient = mock(RankingModelClient.class);
        ImageServiceImpl imageService = mock(ImageServiceImpl.class);
        FeedServiceImpl feedService = new FeedServiceImpl(
                imageContentMapper,
                recommendationMapper,
                behaviorMapper,
                vectorRecallClient,
                rankingModelClient,
                imageService
        );
        ImageEntity personalized = image(2L);
        ApiDtos.ImageView personalizedView = view(2L);
        when(behaviorMapper.hasRecentPositiveBehavior(null, "visitor-a")).thenReturn(1);
        when(behaviorMapper.findRecentBehaviorSequence(null, "visitor-a", 120)).thenReturn(List.of());
        when(behaviorMapper.findRecentPositiveImageIds(null, "visitor-a", 40)).thenReturn(List.of(1L));
        when(behaviorMapper.findRecentSeenImageIds(null, "visitor-a", 400)).thenReturn(List.of(1L));
        when(vectorRecallClient.feed(eq(null), eq(List.of()), eq(List.of(1L)), eq(0), eq(2)))
                .thenReturn(List.of(new VectorRecallClient.VectorHit(2L, 0.95)));
        when(recommendationMapper.selectUserMetadataRecall(null, "visitor-a", 2)).thenReturn(List.of());
        when(recommendationMapper.selectColdStart(0, 2)).thenReturn(List.of());
        when(imageContentMapper.findPublishedByIds(anyList())).thenReturn(List.of(personalized));
        when(imageService.toViews(eq(List.of(personalized)), eq("multi-recall-home"))).thenReturn(List.of(personalizedView));

        var page = feedService.home(null, 1, 1, "visitor-a", "session-a", "seed-a", List.of());

        assertEquals(List.of(personalizedView), page.records());
        verify(vectorRecallClient).feed(eq(null), eq(List.of()), eq(List.of(1L)), eq(0), eq(2));
    }

    private ImageEntity image(Long id) {
        ImageEntity image = new ImageEntity();
        image.setId(id);
        image.setAuthorId(1L);
        image.setHotScore(BigDecimal.TEN);
        image.setPublishedAt(LocalDateTime.now());
        return image;
    }

    private ApiDtos.ImageView view(Long id) {
        return new ApiDtos.ImageView(
                id,
                null,
                "title",
                "",
                List.of(),
                "recommend",
                "recommend",
                "image",
                List.of(),
                List.of(),
                null,
                null,
                0,
                0,
                0,
                0,
                0,
                0,
                "cold-start",
                LocalDateTime.now(),
                "PUBLISHED",
                null
        );
    }
}
