package com.rangwaz.imagesite.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration properties for MinIO object storage.
 */
@ConfigurationProperties(prefix = "app.storage.minio")
public class MinioProperties {
    private String endpoint;
    private String accessKey;
    private String secretKey;
    private String bucket;
    private String objectUrlPrefix;

    /**
     * Gets the MinIO endpoint.
     *
     * @return endpoint URL
     */
    public String getEndpoint() {
        return endpoint;
    }

    /**
     * Sets the MinIO endpoint.
     *
     * @param endpoint endpoint URL
     */
    public void setEndpoint(String endpoint) {
        this.endpoint = endpoint;
    }

    /**
     * Gets the access key.
     *
     * @return access key
     */
    public String getAccessKey() {
        return accessKey;
    }

    /**
     * Sets the access key.
     *
     * @param accessKey access key
     */
    public void setAccessKey(String accessKey) {
        this.accessKey = accessKey;
    }

    /**
     * Gets the secret key.
     *
     * @return secret key
     */
    public String getSecretKey() {
        return secretKey;
    }

    /**
     * Sets the secret key.
     *
     * @param secretKey secret key
     */
    public void setSecretKey(String secretKey) {
        this.secretKey = secretKey;
    }

    /**
     * Gets the bucket name.
     *
     * @return bucket name
     */
    public String getBucket() {
        return bucket;
    }

    /**
     * Sets the bucket name.
     *
     * @param bucket bucket name
     */
    public void setBucket(String bucket) {
        this.bucket = bucket;
    }

    /**
     * Gets the public object URL prefix.
     *
     * @return object URL prefix
     */
    public String getObjectUrlPrefix() {
        return objectUrlPrefix;
    }

    /**
     * Sets the public object URL prefix.
     *
     * @param objectUrlPrefix object URL prefix
     */
    public void setObjectUrlPrefix(String objectUrlPrefix) {
        this.objectUrlPrefix = objectUrlPrefix;
    }
}
