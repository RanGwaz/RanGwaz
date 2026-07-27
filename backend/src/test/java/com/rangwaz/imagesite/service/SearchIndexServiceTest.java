package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;

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
}
