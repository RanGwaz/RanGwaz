package com.rangwaz.imagesite.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Search engine runtime configuration.
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.search")
public class SearchProperties {
    private String elasticsearchUrl = "http://localhost:9200";
    private String indexName = "rangwaz-images";
    private int connectTimeoutMs = 800;
    private int readTimeoutMs = 2500;
    private int reindexBatchSize = 500;
}
