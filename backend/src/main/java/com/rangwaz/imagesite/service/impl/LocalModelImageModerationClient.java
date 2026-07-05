package com.rangwaz.imagesite.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.config.ContentSafetyProperties;
import com.rangwaz.imagesite.service.ImageModerationClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;

/**
 * Local HTTP image moderation client for no-public-domain deployments.
 */
@Service
@ConditionalOnProperty(name = "app.content-safety.cloud.provider", havingValue = "local-model")
public class LocalModelImageModerationClient implements ImageModerationClient {
    private static final Logger log = LoggerFactory.getLogger(LocalModelImageModerationClient.class);

    private final ObjectMapper objectMapper;
    private final ContentSafetyProperties properties;
    private final HttpClient httpClient;

    public LocalModelImageModerationClient(ObjectMapper objectMapper, ContentSafetyProperties properties) {
        this.objectMapper = objectMapper;
        this.properties = properties;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(3))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    @Override
    public ModerationDecision check(String imageUrl, byte[] imageBytes, String contentType) {
        ContentSafetyProperties.Model model = properties.getCloud().getModel();
        if (!properties.getCloud().isEnabled()) return ModerationDecision.allow(null);
        requireConfigured(model, imageBytes);
        try {
            String encodedImage = Base64.getEncoder().encodeToString(imageBytes);
            String payload = objectMapper.writeValueAsString(Map.of(
                    "imageBase64", encodedImage,
                    "image_base64", encodedImage,
                    "base64", encodedImage,
                    "contentType", StringUtils.hasText(contentType) ? contentType : "image/jpeg"
            ));
            HttpRequest request = HttpRequest.newBuilder(URI.create(model.getUrl().trim()))
                    .version(HttpClient.Version.HTTP_1_1)
                    .timeout(Duration.ofMillis(Math.max(1000, model.getRequestTimeoutMs())))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = sendWithRetry(request);
            JsonNode body = objectMapper.readTree(response.body());
            return toDecision(response.statusCode(), body, response.body());
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            log.warn("Local image moderation failed url={} contentType={} error={}",
                    model.getUrl(), contentType, exception.toString(), exception);
            throw new BusinessException("IMAGE_MODERATION_FAILED", "图片安全审核暂时不可用，请稍后重试");
        }
    }

    private HttpResponse<String> sendWithRetry(HttpRequest request) throws IOException, InterruptedException {
        try {
            return httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException exception) {
            log.warn("Local image moderation request transport failed once; retrying error={}", exception.toString());
            return httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        }
    }

    private ModerationDecision toDecision(int httpStatus, JsonNode payload, String rawBody) {
        if (httpStatus / 100 != 2) {
            String message = providerMessage(payload);
            log.warn("Local image moderation rejected request httpStatus={} message={} response={}",
                    httpStatus, message, abbreviate(rawBody, 1200));
            throw new BusinessException("IMAGE_MODERATION_FAILED", "图片安全审核服务返回异常：" + message);
        }
        boolean allowed = payload.path("allowed").asBoolean(false);
        String reason = firstText(payload, "reason", "label", "risk", "message");
        String requestId = firstText(payload, "requestId", "request_id");
        if (!StringUtils.hasText(reason)) reason = allowed ? "pass" : "unsafe-image";
        log.info("Local image moderation result allowed={} reason={} requestId={}", allowed, reason, requestId);
        return allowed
                ? ModerationDecision.allow(requestId)
                : ModerationDecision.block(reason, requestId);
    }

    private void requireConfigured(ContentSafetyProperties.Model model, byte[] imageBytes) {
        if (!StringUtils.hasText(model.getUrl())) {
            throw new BusinessException("IMAGE_MODERATION_NOT_CONFIGURED", "图片安全审核缺少本地模型服务地址");
        }
        if (imageBytes == null || imageBytes.length == 0) {
            throw new BusinessException("IMAGE_MODERATION_FAILED", "图片安全审核缺少图片数据");
        }
        if (imageBytes.length > model.getMaxBase64Bytes()) {
            throw new BusinessException("IMAGE_TOO_LARGE_FOR_MODERATION", "图片过大，无法进行安全审核");
        }
    }

    private String firstText(JsonNode node, String... names) {
        for (String name : names) {
            String value = node.path(name).asText("");
            if (StringUtils.hasText(value)) return value;
        }
        return "";
    }

    private String providerMessage(JsonNode payload) {
        String message = firstText(payload, "detail", "message", "error", "reason");
        if (StringUtils.hasText(message)) return message;
        JsonNode detail = payload.path("detail");
        if (detail.isObject()) {
            String objectMessage = firstText(detail, "message", "msg", "error", "reason");
            if (StringUtils.hasText(objectMessage)) return objectMessage + " keys=" + detail.path("keys");
        }
        if (detail.isArray() && !detail.isEmpty()) {
            String first = firstText(detail.get(0), "msg", "message", "type");
            if (StringUtils.hasText(first)) return first;
        }
        return "HTTP error";
    }

    private String abbreviate(String value, int maxLength) {
        if (value == null) return "";
        if (value.length() <= maxLength) return value;
        return value.substring(0, maxLength) + "...";
    }
}
