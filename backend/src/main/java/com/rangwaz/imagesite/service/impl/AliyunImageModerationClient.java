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

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Aliyun Content Moderation enhanced image moderation client.
 */
@Service
@ConditionalOnProperty(name = "app.content-safety.cloud.provider", havingValue = "aliyun", matchIfMissing = true)
public class AliyunImageModerationClient implements ImageModerationClient {
    private static final Logger log = LoggerFactory.getLogger(AliyunImageModerationClient.class);
    private static final String JAVA_HMAC_SHA1 = "HmacSHA1";
    private static final String ALIYUN_SIGNATURE_METHOD = "HMAC-SHA1";

    private final ObjectMapper objectMapper;
    private final ContentSafetyProperties properties;
    private final HttpClient httpClient;

    /**
     * Creates the moderation client.
     *
     * @param objectMapper JSON mapper
     * @param properties content-safety properties
     */
    public AliyunImageModerationClient(ObjectMapper objectMapper, ContentSafetyProperties properties) {
        this.objectMapper = objectMapper;
        this.properties = properties;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(4))
                .build();
    }

    @Override
    public ModerationDecision check(String imageUrl, byte[] imageBytes, String contentType) {
        ContentSafetyProperties.Cloud cloud = properties.getCloud();
        ContentSafetyProperties.Aliyun config = cloud.getAliyun();
        if (!cloud.isEnabled()) return ModerationDecision.allow(null);
        requireConfigured(config);
        String normalizedImageUrl = requirePublicImageUrl(imageUrl);
        String dataId = UUID.randomUUID().toString();
        try {
            String serviceParameters = objectMapper.writeValueAsString(Map.of(
                    "dataId", dataId,
                    "imageUrl", normalizedImageUrl
            ));
            Map<String, String> params = baseParams(config);
            params.put("Action", "ImageModeration");
            params.put("Service", StringUtils.hasText(config.getService()) ? config.getService().trim() : "baselineCheck");
            params.put("ServiceParameters", serviceParameters);
            params.put("Signature", sign(params, config.getAccessKeySecret()));

            HttpRequest request = HttpRequest.newBuilder(URI.create(config.getEndpoint().trim()))
                    .timeout(Duration.ofMillis(Math.max(1000, config.getRequestTimeoutMs())))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(canonicalQuery(params), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            JsonNode payload = objectMapper.readTree(response.body());
            return toDecision(response.statusCode(), payload, dataId, contentType, response.body());
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            log.warn("Aliyun image moderation failed dataId={} contentType={} error={}", dataId, contentType, exception.toString(), exception);
            throw new BusinessException("IMAGE_MODERATION_FAILED", "图片安全审核暂时不可用，请稍后重试");
        }
    }

    private ModerationDecision toDecision(int httpStatus, JsonNode payload, String dataId, String contentType, String rawBody) {
        String providerCode = payload.path("Code").asText("");
        String requestId = payload.path("RequestId").asText("");
        if (httpStatus / 100 != 2 || !providerAccepted(providerCode)) {
            String message = providerMessage(payload);
            log.warn("Aliyun image moderation rejected request dataId={} httpStatus={} providerCode={} requestId={} message={} response={}",
                    dataId, httpStatus, providerCode, requestId, message, abbreviate(rawBody, 1200));
            throw new BusinessException("IMAGE_MODERATION_FAILED", "图片安全审核失败：" + message);
        }

        JsonNode data = payload.path("Data");
        String riskLevel = firstText(data, "RiskLevel", "riskLevel");
        String reason = moderationReason(data, riskLevel);
        boolean allowed = isAllowedRisk(riskLevel, reason);
        log.info("Aliyun image moderation result dataId={} requestId={} contentType={} riskLevel={} reason={} allowed={}",
                dataId, requestId, contentType, riskLevel, reason, allowed);
        return allowed
                ? ModerationDecision.allow(requestId)
                : ModerationDecision.block(reason, requestId);
    }

    private boolean providerAccepted(String code) {
        return "OK".equalsIgnoreCase(code) || "200".equals(code) || "Success".equalsIgnoreCase(code);
    }

    private boolean isAllowedRisk(String riskLevel, String reason) {
        String risk = riskLevel == null ? "" : riskLevel.trim().toLowerCase();
        String normalizedReason = reason == null ? "" : reason.trim().toLowerCase();
        if (risk.isBlank()) return normalizedReason.isBlank() || "pass".equals(normalizedReason) || "nonlabel".equals(normalizedReason);
        return risk.equals("none")
                || risk.equals("normal")
                || risk.equals("pass")
                || risk.equals("low")
                || risk.equals("0");
    }

    private String moderationReason(JsonNode data, String riskLevel) {
        JsonNode result = data.path("Result");
        if (result.isArray() && !result.isEmpty()) {
            JsonNode first = result.get(0);
            String label = firstText(first, "Label", "label");
            String description = firstText(first, "Description", "description");
            if (StringUtils.hasText(label)) return label;
            if (StringUtils.hasText(description)) return description;
        }
        return StringUtils.hasText(riskLevel) ? riskLevel : "cloud-risk";
    }

    private String firstText(JsonNode node, String... names) {
        for (String name : names) {
            String value = node.path(name).asText("");
            if (StringUtils.hasText(value)) return value;
        }
        return "";
    }

    private String providerMessage(JsonNode payload) {
        String message = firstText(payload, "Message", "Msg", "message", "msg");
        if (StringUtils.hasText(message)) return message;
        JsonNode data = payload.path("Data");
        message = firstText(data, "Message", "Msg", "message", "msg", "Description", "description");
        if (StringUtils.hasText(message)) return message;
        JsonNode result = data.path("Result");
        if (result.isArray() && !result.isEmpty()) {
            message = firstText(result.get(0), "Message", "Msg", "message", "msg", "Description", "description", "Label", "label");
            if (StringUtils.hasText(message)) return message;
        }
        return "图片审核服务返回异常";
    }

    private String abbreviate(String value, int maxLength) {
        if (value == null) return "";
        if (value.length() <= maxLength) return value;
        return value.substring(0, maxLength) + "...";
    }

    private Map<String, String> baseParams(ContentSafetyProperties.Aliyun config) {
        Map<String, String> params = new TreeMap<>();
        params.put("Format", "JSON");
        params.put("Version", "2022-03-02");
        params.put("RegionId", StringUtils.hasText(config.getRegionId()) ? config.getRegionId().trim() : "cn-shanghai");
        params.put("AccessKeyId", config.getAccessKeyId().trim());
        params.put("SignatureMethod", ALIYUN_SIGNATURE_METHOD);
        params.put("SignatureVersion", "1.0");
        params.put("SignatureNonce", UUID.randomUUID().toString());
        params.put("Timestamp", DateTimeFormatter.ISO_INSTANT.format(Instant.now()));
        return params;
    }

    private String sign(Map<String, String> params, String secret) throws Exception {
        String canonical = canonicalQuery(params);
        String stringToSign = "POST&%2F&" + percentEncode(canonical);
        Mac mac = Mac.getInstance(JAVA_HMAC_SHA1);
        mac.init(new SecretKeySpec((secret.trim() + "&").getBytes(StandardCharsets.UTF_8), JAVA_HMAC_SHA1));
        return Base64.getEncoder().encodeToString(mac.doFinal(stringToSign.getBytes(StandardCharsets.UTF_8)));
    }

    private String canonicalQuery(Map<String, String> params) {
        return params.entrySet().stream()
                .sorted(Map.Entry.comparingByKey())
                .map(entry -> percentEncode(entry.getKey()) + "=" + percentEncode(entry.getValue()))
                .collect(Collectors.joining("&"));
    }

    private String percentEncode(String value) {
        return URLEncoder.encode(value == null ? "" : value, StandardCharsets.UTF_8)
                .replace("+", "%20")
                .replace("*", "%2A")
                .replace("%7E", "~");
    }

    private void requireConfigured(ContentSafetyProperties.Aliyun config) {
        if (!StringUtils.hasText(config.getAccessKeyId()) || !StringUtils.hasText(config.getAccessKeySecret())) {
            log.warn("Aliyun image moderation is not configured accessKeyIdPresent={} accessKeySecretPresent={}",
                    StringUtils.hasText(config.getAccessKeyId()),
                    StringUtils.hasText(config.getAccessKeySecret()));
            throw new BusinessException("IMAGE_MODERATION_NOT_CONFIGURED", "图片安全审核缺少云厂商 AccessKey 配置");
        }
        if (!StringUtils.hasText(config.getEndpoint())) {
            throw new BusinessException("IMAGE_MODERATION_NOT_CONFIGURED", "图片安全审核缺少云厂商接口地址");
        }
    }

    private String requirePublicImageUrl(String imageUrl) {
        String value = imageUrl == null ? "" : imageUrl.trim();
        if (!StringUtils.hasText(value) || (!value.startsWith("http://") && !value.startsWith("https://"))) {
            throw new BusinessException(
                    "IMAGE_MODERATION_NOT_CONFIGURED",
                    "阿里云图片审核需要公网可访问的 imageUrl，请将 app.storage.minio.object-url-prefix 配置为 https://域名/media/object"
            );
        }
        if (value.contains("localhost") || value.contains("127.0.0.1") || value.contains("0.0.0.0")) {
            throw new BusinessException(
                    "IMAGE_MODERATION_NOT_CONFIGURED",
                    "阿里云图片审核无法访问本机地址，请使用公网域名配置 app.storage.minio.object-url-prefix"
            );
        }
        return value;
    }
}
