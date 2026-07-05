package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;

import java.util.List;

/**
 * Maintains the Elasticsearch image index.
 */
@Service
public class SearchIndexService {
    private final ImageContentMapper imageContentMapper;
    private final ElasticsearchSearchClient searchClient;
    private final SearchProperties properties;

    public SearchIndexService(ImageContentMapper imageContentMapper, ElasticsearchSearchClient searchClient, SearchProperties properties) {
        this.imageContentMapper = imageContentMapper;
        this.searchClient = searchClient;
        this.properties = properties;
    }

    /**
     * Prepares the ES index when the application starts.
     */
    @EventListener(ApplicationReadyEvent.class)
    public void prepareIndex() {
        searchClient.ensureIndex();
    }

    /**
     * Indexes one image after publish.
     *
     * @param imageId image id
     */
    public void indexImage(Long imageId) {
        if (imageId == null) return;
        List<ImageSearchDocumentEntity> documents = imageContentMapper.findSearchDocumentsByIds(List.of(imageId));
        searchClient.bulkIndex(documents);
    }

    /**
     * Rebuilds all published image documents into Elasticsearch.
     *
     * @return indexed document count
     */
    public long reindexAllPublished() {
        searchClient.recreateIndex();
        long count = 0;
        long afterId = 0;
        int batchSize = Math.max(50, properties.getReindexBatchSize());
        while (true) {
            List<ImageSearchDocumentEntity> documents = imageContentMapper.pageSearchDocuments(afterId, batchSize);
            if (CollectionUtils.isEmpty(documents)) break;
            searchClient.bulkIndex(documents);
            count += documents.size();
            afterId = documents.get(documents.size() - 1).getId();
        }
        return count;
    }
}
