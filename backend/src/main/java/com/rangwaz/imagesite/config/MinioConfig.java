package com.rangwaz.imagesite.config;

import io.minio.MinioClient;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * MinIO client configuration.
 */
@Configuration
@EnableConfigurationProperties(MinioProperties.class)
public class MinioConfig {
    /**
     * Builds the MinIO client used by media storage.
     *
     * @param properties MinIO properties
     * @return MinIO client
     */
    @Bean
    public MinioClient minioClient(MinioProperties properties) {
        return MinioClient.builder()
                .endpoint(properties.getEndpoint())
                .credentials(properties.getAccessKey(), properties.getSecretKey())
                .build();
    }
}
