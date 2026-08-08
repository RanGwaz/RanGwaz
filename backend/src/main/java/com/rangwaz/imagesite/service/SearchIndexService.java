package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
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
        prepareIndex(false);
    }

    /**
     * Indexes one image after publish.
     *
     * @param imageId image id
     */
    public void indexImage(Long imageId) {
        if (imageId == null) return;
        List<ImageSearchDocumentEntity> documents = imageContentMapper.findSearchDocumentsByIds(List.of(imageId));
        try {
            searchClient.bulkIndex(documents);
        } catch (RuntimeException exception) {
            indexReady.set(false);
            throw exception;
        }
    }

    /**
     * Returns whether Elasticsearch contains the complete published dataset.
     */
    public boolean isIndexReady() {
        return indexReady.get();
    }

    private void prepareIndex(boolean failFast) {
        try {
            searchClient.ensureIndex();
            long publishedCount = imageContentMapper.countPublished();
            long indexedCount = searchClient.countDocuments(properties.getIndexName());
            ElasticsearchSearchClient.ReindexCertificate certificate = searchClient
                    .readVerifiedReindexCertificate(properties.getIndexName())
                    .orElse(null);
            boolean ready = certificate != null
                    && publishedCount > 0
                    && publishedCount == indexedCount
                    && publishedCount == certificate.publishedCount();
            boolean wasReady = indexReady.getAndSet(ready);
            if (ready && !wasReady) {
                log.info("Elasticsearch image index is ready: {} documents", indexedCount);
            } else if (!ready) {
                log.warn("Elasticsearch image index is not ready: RDS published={}, Elasticsearch={}, certified={}; " +
                                "search will use the MySQL fallback until the operator reindex job succeeds",
                        publishedCount, indexedCount, certificate == null ? "none" : certificate.publishedCount());
            }
        } catch (RuntimeException exception) {
            indexReady.set(false);
            if (failFast) throw exception;
            log.warn("Elasticsearch is not ready; application will continue and retry in {} ms",
                    properties.getIndexRetryDelayMs(), exception);
        }
    }
}
