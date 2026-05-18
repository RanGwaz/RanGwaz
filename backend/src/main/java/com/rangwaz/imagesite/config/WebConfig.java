package com.rangwaz.imagesite.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.nio.file.Path;

/**
 * Web MVC configuration for local React development and uploaded image serving.
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {
    private final String uploadRoot;
    private final String publicUploadPrefix;

    /**
     * Creates the web configuration.
     *
     * @param uploadRoot local upload root
     * @param publicUploadPrefix public upload URL prefix
     */
    public WebConfig(@Value("${app.upload-root}") String uploadRoot,
                     @Value("${app.public-upload-prefix}") String publicUploadPrefix) {
        this.uploadRoot = uploadRoot;
        this.publicUploadPrefix = publicUploadPrefix;
    }

    /**
     * Allows the Vite dev server to call the API.
     *
     * @param registry CORS registry
     */
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOrigins("http://localhost:5173", "http://127.0.0.1:5173")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .exposedHeaders("Authorization")
                .allowCredentials(false);
    }

    /**
     * Serves files uploaded during local development.
     *
     * @param registry resource handler registry
     */
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String location = Path.of(uploadRoot).toAbsolutePath().normalize().toUri().toString();
        registry.addResourceHandler(publicUploadPrefix + "/**").addResourceLocations(location);
    }
}
