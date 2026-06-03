package com.rangwaz.imagesite.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Recommendation runtime configuration.
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.recommendation")
public class RecommendationProperties {
    private String vectorServiceUrl = "http://127.0.0.1:8091";
    private boolean vectorEnabled = true;
}
