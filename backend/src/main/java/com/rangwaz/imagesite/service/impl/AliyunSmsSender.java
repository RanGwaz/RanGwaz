package com.rangwaz.imagesite.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.service.SmsSender;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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
 * Aliyun number-auth SMS verification sender using the RPC API signature protocol.
 */
@Service
@ConditionalOnProperty(name = "app.sms.provider", havingValue = "aliyun")
public class AliyunSmsSender implements SmsSender {
    private static final Logger log = LoggerFactory.getLogger(AliyunSmsSender.class);
    private static final String JAVA_HMAC_SHA1 = "HmacSHA1";
    private static final String ALIYUN_SIGNATURE_METHOD = "HMAC-SHA1";

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    @Value("${app.sms.aliyun.endpoint:https://dypnsapi.aliyuncs.com/}")
    private String endpoint;

    @Value("${app.sms.aliyun.region-id:cn-hangzhou}")
    private String regionId;

    @Value("${app.sms.aliyun.access-key-id:}")
    private String accessKeyId;

    @Value("${app.sms.aliyun.access-key-secret:}")
    private String accessKeySecret;

    @Value("${app.sms.aliyun.sign-name:}")
    private String signName;

    @Value("${app.sms.aliyun.template-code:}")
    private String templateCode;

    @Value("${app.sms.aliyun.country-code:86}")
    private String countryCode;

    @Value("${app.sms.aliyun.scheme-name:}")
    private String schemeName;

    @Value("${app.sms.aliyun.duplicate-policy:1}")
    private int duplicatePolicy;

    @Value("${app.sms.aliyun.interval-seconds:${app.sms.cooldown-seconds:60}}")
    private long intervalSeconds;

    @Value("${app.sms.aliyun.return-verify-code:false}")
    private boolean returnVerifyCode;

    @Value("${app.sms.aliyun.auto-retry:1}")
    private int autoRetry;

    @Value("${app.sms.aliyun.request-timeout-ms:6000}")
    private long requestTimeoutMs;

    /**
     * Creates the sender.
     *
     * @param objectMapper JSON mapper
     */
    public AliyunSmsSender(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(3))
                .build();
    }

    @Override
    public void sendVerificationCode(String phone, String code, Duration ttl, String scene) {
        requireConfigured();
        try {
            long minutes = Math.max(1, (long) Math.ceil(ttl.toSeconds() / 60D));
            String templateParam = objectMapper.writeValueAsString(Map.of(
                    "code", code,
                    "min", String.valueOf(minutes)
            ));
            Map<String, String> params = baseParams();
            params.put("Action", "SendSmsVerifyCode");
            params.put("PhoneNumber", phone);
            params.put("CountryCode", cleanCountryCode());
            params.put("SignName", signName.trim());
            params.put("TemplateCode", templateCode.trim());
            params.put("TemplateParam", templateParam);
            params.put("OutId", cleanOutId(scene));
            params.put("ValidTime", String.valueOf(Math.max(1, ttl.toSeconds())));
            params.put("DuplicatePolicy", String.valueOf(duplicatePolicy));
            params.put("Interval", String.valueOf(Math.max(0, intervalSeconds)));
            params.put("ReturnVerifyCode", String.valueOf(returnVerifyCode));
            params.put("AutoRetry", String.valueOf(autoRetry));
            if (StringUtils.hasText(schemeName)) {
                params.put("SchemeName", schemeName.trim());
            }

            String signature = sign(params);
            params.put("Signature", signature);
            String body = canonicalQuery(params);
            HttpRequest request = HttpRequest.newBuilder(URI.create(endpoint.trim()))
                    .timeout(Duration.ofMillis(Math.max(1000, requestTimeoutMs)))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            JsonNode payload = objectMapper.readTree(response.body());
            String providerCode = payload.path("Code").asText("");
            boolean success = payload.path("Success").asBoolean("OK".equalsIgnoreCase(providerCode));
            if (response.statusCode() / 100 != 2 || !"OK".equalsIgnoreCase(providerCode) || !success) {
                String message = payload.path("Message").asText("号码认证短信发送失败");
                JsonNode model = payload.path("Model");
                String requestId = StringUtils.hasText(payload.path("RequestId").asText(""))
                        ? payload.path("RequestId").asText("")
                        : model.path("RequestId").asText("");
                log.warn("Aliyun number-auth SMS rejected phone={} signName={} templateCode={} httpStatus={} providerCode={} requestId={} bizId={} message={}",
                        maskPhone(phone),
                        signName.trim(),
                        templateCode.trim(),
                        response.statusCode(),
                        providerCode,
                        requestId,
                        model.path("BizId").asText(""),
                        message);
                throw new BusinessException("SMS_PROVIDER_REJECTED", "号码认证短信发送失败：" + message);
            }
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            log.warn("Aliyun number-auth SMS failed phone={} scene={} error={}", maskPhone(phone), cleanOutId(scene), exception.toString(), exception);
            throw new BusinessException("SMS_PROVIDER_FAILED", "号码认证短信暂时不可用，请稍后重试");
        }
    }

    private Map<String, String> baseParams() {
        Map<String, String> params = new TreeMap<>();
        params.put("Format", "JSON");
        params.put("Version", "2017-05-25");
        params.put("RegionId", StringUtils.hasText(regionId) ? regionId.trim() : "cn-hangzhou");
        params.put("AccessKeyId", accessKeyId.trim());
        params.put("SignatureMethod", ALIYUN_SIGNATURE_METHOD);
        params.put("SignatureVersion", "1.0");
        params.put("SignatureNonce", UUID.randomUUID().toString());
        params.put("Timestamp", DateTimeFormatter.ISO_INSTANT.format(Instant.now()));
        return params;
    }

    private String sign(Map<String, String> params) throws Exception {
        String canonical = canonicalQuery(params);
        String stringToSign = "POST&%2F&" + percentEncode(canonical);
        Mac mac = Mac.getInstance(JAVA_HMAC_SHA1);
        mac.init(new SecretKeySpec((accessKeySecret.trim() + "&").getBytes(StandardCharsets.UTF_8), JAVA_HMAC_SHA1));
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

    private String cleanOutId(String scene) {
        String cleaned = StringUtils.hasText(scene) ? scene.trim() : "login";
        return cleaned.length() > 32 ? cleaned.substring(0, 32) : cleaned;
    }

    private String cleanCountryCode() {
        return StringUtils.hasText(countryCode) ? countryCode.trim().replace("+", "") : "86";
    }

    private void requireConfigured() {
        if (!StringUtils.hasText(accessKeyId)
                || !StringUtils.hasText(accessKeySecret)
                || !StringUtils.hasText(signName)
                || !StringUtils.hasText(templateCode)) {
            log.warn("Aliyun SMS is not fully configured accessKeyIdPresent={} accessKeySecretPresent={} signNamePresent={} templateCodePresent={}",
                    StringUtils.hasText(accessKeyId),
                    StringUtils.hasText(accessKeySecret),
                    StringUtils.hasText(signName),
                    StringUtils.hasText(templateCode));
            throw new BusinessException("SMS_PROVIDER_NOT_CONFIGURED", "号码认证短信缺少阿里云 AccessKey、签名或模板配置");
        }
        if (!StringUtils.hasText(endpoint)) {
            throw new BusinessException("SMS_PROVIDER_NOT_CONFIGURED", "号码认证短信缺少阿里云接口地址");
        }
    }

    private String maskPhone(String phone) {
        if (!StringUtils.hasText(phone)) return "";
        String cleaned = phone.trim();
        if (cleaned.length() <= 7) return "***";
        return cleaned.substring(0, 3) + "****" + cleaned.substring(cleaned.length() - 4);
    }
}
