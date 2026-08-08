package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SearchIndexServiceTest {
    @Test
    void unavailableElasticsearchDoesNotStopApplicationByDefault() {
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        doThrow(new IllegalStateException("not ready")).when(client).ensureIndex();
        SearchProperties properties = new SearchProperties();
        SearchIndexService service = new SearchIndexService(mock(ImageContentMapper.class), client, properties);

        assertDoesNotThrow(service::prepareIndex);
    }

    @Test
    void failFastCanStillBeEnabledExplicitly() {
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        doThrow(new IllegalStateException("not ready")).when(client).ensureIndex();
        SearchProperties properties = new SearchProperties();
        properties.setFailFastOnStartup(true);
        SearchIndexService service = new SearchIndexService(mock(ImageContentMapper.class), client, properties);

        assertThrows(IllegalStateException.class, service::prepareIndex);
    }

    @Test
    void indexIsReadyOnlyWhenPublishedAndIndexedCountsMatchAndAreNonZero() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(12L);
        when(client.readVerifiedReindexCertificate(properties.getIndexName())).thenReturn(certificate(12L));
        SearchIndexService service = new SearchIndexService(mapper, client, properties);

        service.prepareIndex();

        assertTrue(service.isIndexReady());
        verify(mapper, never()).pageSearchDocuments(org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void matchingCountsWithoutAnOperatorCertificateRemainUnready() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(12L);
        SearchIndexService service = new SearchIndexService(mapper, client, properties);

        service.prepareIndex();

        assertFalse(service.isIndexReady());
    }

    @Test
    void countMismatchKeepsIndexUnreadyUntilPeriodicCheckSeesCliResult() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(0L, 12L);
        when(client.readVerifiedReindexCertificate(properties.getIndexName())).thenReturn(certificate(12L));
        SearchIndexService service = new SearchIndexService(mapper, client, properties);

        service.prepareIndex();
        assertFalse(service.isIndexReady());

        service.retryIndexPreparation();
        assertTrue(service.isIndexReady());
    }

    @Test
    void periodicCheckDemotesAReadyIndexWhenCountsDrift() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(12L, 11L);
        when(client.readVerifiedReindexCertificate(properties.getIndexName())).thenReturn(certificate(12L));
        SearchIndexService service = new SearchIndexService(mapper, client, properties);

        service.prepareIndex();
        assertTrue(service.isIndexReady());

        service.retryIndexPreparation();
        assertFalse(service.isIndexReady());
    }

    @Test
    void failedIncrementalIndexingImmediatelyDemotesReadiness() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(12L);
        when(client.readVerifiedReindexCertificate(properties.getIndexName())).thenReturn(certificate(12L));
        when(mapper.findSearchDocumentsByIds(List.of(9L)))
                .thenReturn(List.of(mock(ImageSearchDocumentEntity.class)));
        doThrow(new IllegalStateException("bulk failed"))
                .when(client).bulkIndex(org.mockito.ArgumentMatchers.anyList());
        SearchIndexService service = new SearchIndexService(mapper, client, properties);
        service.prepareIndex();

        assertThrows(IllegalStateException.class, () -> service.indexImage(9L));
        assertFalse(service.isIndexReady());
    }

    @Test
    void certificateCountMustMatchBothExactCounts() {
        ImageContentMapper mapper = mock(ImageContentMapper.class);
        ElasticsearchSearchClient client = mock(ElasticsearchSearchClient.class);
        SearchProperties properties = new SearchProperties();
        when(mapper.countPublished()).thenReturn(12L);
        when(client.countDocuments(properties.getIndexName())).thenReturn(12L);
        when(client.readVerifiedReindexCertificate(properties.getIndexName())).thenReturn(certificate(11L));
        SearchIndexService service = new SearchIndexService(mapper, client, properties);

        service.prepareIndex();

        assertFalse(service.isIndexReady());
    }

    private Optional<ElasticsearchSearchClient.ReindexCertificate> certificate(long publishedCount) {
        return Optional.of(new ElasticsearchSearchClient.ReindexCertificate(
                "rangwaz-images-candidate-20260808",
                publishedCount
        ));
    }
}
