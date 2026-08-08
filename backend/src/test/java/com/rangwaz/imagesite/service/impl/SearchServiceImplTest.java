package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.entity.SearchSuggestionEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.service.ContentSafetyService;
import com.rangwaz.imagesite.service.ElasticsearchSearchClient;
import com.rangwaz.imagesite.service.SearchIndexService;
import com.rangwaz.imagesite.service.TopicService;
import com.rangwaz.imagesite.service.UserService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SearchServiceImplTest {
    private ImageContentMapper imageContentMapper;
    private ImageServiceImpl imageService;
    private ElasticsearchSearchClient searchClient;
    private SearchIndexService searchIndexService;
    private SearchServiceImpl service;

    @BeforeEach
    void setUp() {
        imageContentMapper = mock(ImageContentMapper.class);
        imageService = mock(ImageServiceImpl.class);
        searchClient = mock(ElasticsearchSearchClient.class);
        searchIndexService = mock(SearchIndexService.class);
        ContentSafetyService contentSafetyService = mock(ContentSafetyService.class);
        when(contentSafetyService.allowsText("forest")).thenReturn(true);
        when(contentSafetyService.allowsText("avatar")).thenReturn(true);
        service = new SearchServiceImpl(
                imageContentMapper,
                imageService,
                mock(UserService.class),
                mock(TopicService.class),
                searchClient,
                searchIndexService,
                contentSafetyService
        );
    }

    @Test
    void searchFallsBackToMysqlMetadataWhileIndexIsNotReady() {
        ImageEntity row = new ImageEntity();
        row.setId(42L);
        List<ImageEntity> rows = List.of(row);
        List<ApiDtos.ImageView> views = Collections.singletonList(null);
        when(searchIndexService.isIndexReady()).thenReturn(false);
        when(imageContentMapper.searchExpanded(anyList(), org.mockito.ArgumentMatchers.anyInt())).thenReturn(rows);
        when(imageService.toViews(rows, "search-fallback")).thenReturn(views);

        ApiDtos.SearchResult result = service.search("avatar");

        assertEquals(views, result.images());
        verify(searchClient, never()).searchImageIds(anyList(), eq(180));
        ArgumentCaptor<List<String>> keywords = ArgumentCaptor.forClass(List.class);
        ArgumentCaptor<Integer> limit = ArgumentCaptor.forClass(Integer.class);
        verify(imageContentMapper).searchExpanded(keywords.capture(), limit.capture());
        assertTrue(keywords.getValue().size() <= 2, "fallback keywords must remain strictly bounded");
        assertTrue(limit.getValue() <= 40, "fallback result limit must remain strictly bounded");
    }

    @Test
    void readyIndexKeepsARealZeroHitResultEmpty() {
        when(searchIndexService.isIndexReady()).thenReturn(true);
        when(searchClient.searchImageIds(anyList(), eq(180))).thenReturn(List.of());

        ApiDtos.SearchResult result = service.search("forest");

        assertEquals(List.of(), result.images());
        verify(imageContentMapper, never()).searchExpanded(anyList(), eq(180));
    }

    @Test
    void elasticsearchExceptionStillFallsBackToMysqlMetadata() {
        ImageEntity row = new ImageEntity();
        List<ImageEntity> rows = List.of(row);
        List<ApiDtos.ImageView> views = Collections.singletonList(null);
        when(searchIndexService.isIndexReady()).thenReturn(true);
        when(searchClient.searchImageIds(anyList(), eq(180))).thenThrow(new IllegalStateException("down"));
        when(imageContentMapper.searchExpanded(anyList(), eq(40))).thenReturn(rows);
        when(imageService.toViews(rows, "search-fallback")).thenReturn(views);

        ApiDtos.SearchResult result = service.search("forest");

        assertEquals(views, result.images());
    }

    @Test
    void suggestionsFallBackToMysqlMetadataWhileIndexIsNotReady() {
        SearchSuggestionEntity row = suggestion("metadata");
        when(searchIndexService.isIndexReady()).thenReturn(false);
        when(imageContentMapper.suggestByMetadata(anyList(), eq(12))).thenReturn(List.of(row));

        ApiDtos.SearchSuggestionResponse result = service.suggestions("");

        assertEquals("metadata", result.recommended().get(0).keyword());
        verify(searchClient, never()).suggestKeywords(anyList(), eq(12));
    }

    @Test
    void readyIndexKeepsARealZeroSuggestionResultEmpty() {
        when(searchIndexService.isIndexReady()).thenReturn(true);
        when(searchClient.suggestKeywords(anyList(), eq(12))).thenReturn(List.of());

        ApiDtos.SearchSuggestionResponse result = service.suggestions("");

        assertEquals(List.of(), result.recommended());
        verify(imageContentMapper, never()).suggestByMetadata(anyList(), eq(12));
    }

    private SearchSuggestionEntity suggestion(String keyword) {
        SearchSuggestionEntity row = new SearchSuggestionEntity();
        row.setKeyword(keyword);
        row.setKind("tag");
        row.setPostCount(1L);
        return row;
    }
}
