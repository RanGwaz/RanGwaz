package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Maintains the Elasticsearch image index.
 */
@Service
public class SearchIndexService {
    private static final Logger log = LoggerFactory.getLogger(SearchIndexService.class);

    private final ImageContentMapper imageContentMapper;
    private final ElasticsearchSearchClient searchClient;
    private final SearchProperties properties;
    private final AtomicBoolean indexReady = new AtomicBoolean(false);

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
        prepareIndex(properties.isFailFastOnStartup());
    }

    /**
     * Retries index preparation after a slow or temporarily unavailable Elasticsearch startup.
     */
    @Scheduled(
            initialDelayString = "${app.search.index-retry-delay-ms:30000}",
            fixedDelayString = "${app.search.index-retry-delay-ms:30000}"
    )
    public void retryIndexPreparation() {
        if (!indexReady.get()) {
            prepareIndex(false);
        }
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

    private void prepareIndex(boolean failFast) {
        try {
            searchClient.ensureIndex();
            if (indexReady.compareAndSet(false, true)) {
                log.info("Elasticsearch image index is ready");
            }
        } catch (RuntimeException exception) {
            indexReady.set(false);
            if (failFast) throw exception;
            log.warn("Elasticsearch is not ready; application will continue and retry in {} ms",
                    properties.getIndexRetryDelayMs(), exception);
        }
    }
}
