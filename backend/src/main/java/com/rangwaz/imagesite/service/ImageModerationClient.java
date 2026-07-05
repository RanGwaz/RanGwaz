package com.rangwaz.imagesite.service;

/**
 * Cloud image moderation provider for user uploads.
 */
public interface ImageModerationClient {
    /**
     * Checks one image with a cloud provider.
     *
     * @param imageUrl public image URL fetchable by the provider
     * @param imageBytes encoded image bytes for providers that support binary payloads
     * @param contentType upload content type
     * @return moderation decision
     */
    ModerationDecision check(String imageUrl, byte[] imageBytes, String contentType);

    /**
     * Cloud moderation decision.
     *
     * @param allowed whether the image can be stored
     * @param reason provider or normalized risk reason
     * @param requestId provider request id for troubleshooting
     */
    record ModerationDecision(boolean allowed, String reason, String requestId) {
        public static ModerationDecision allow(String requestId) {
            return new ModerationDecision(true, "pass", requestId);
        }

        public static ModerationDecision block(String reason, String requestId) {
            return new ModerationDecision(false, reason, requestId);
        }
    }
}
