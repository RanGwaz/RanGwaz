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
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class FeedServiceImplTest {
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
