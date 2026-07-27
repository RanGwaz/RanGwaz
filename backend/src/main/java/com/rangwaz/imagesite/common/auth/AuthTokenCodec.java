package com.rangwaz.imagesite.common.auth;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.util.Base64;
import java.util.Optional;
import java.util.UUID;

/**
 * Issues and verifies compact HMAC-signed bearer tokens.
 */
@Component
public class AuthTokenCodec {
    private static final String VERSION = "v1";
    private static final String HMAC_ALGORITHM = "HmacSHA256";

    private final byte[] secret;
    private final long ttlSeconds;
    private final Clock clock;

    @Autowired
    public AuthTokenCodec(@Value("${app.auth.token-secret}") String secret,
                          @Value("${app.auth.token-ttl-seconds:86400}") long ttlSeconds) {
        this(secret, ttlSeconds, Clock.systemUTC());
    }

    AuthTokenCodec(String secret, long ttlSeconds, Clock clock) {
        if (secret == null || secret.length() < 32) {
            throw new IllegalStateException("app.auth.token-secret must contain at least 32 characters");
        }
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.ttlSeconds = Math.max(300, ttlSeconds);
        this.clock = clock;
    }

    public IssuedToken issue(Long userId) {
        long expiresAt = clock.instant().getEpochSecond() + ttlSeconds;
        String payload = userId + ":" + expiresAt + ":" + UUID.randomUUID();
        String encodedPayload = Base64.getUrlEncoder().withoutPadding()
                .encodeToString(payload.getBytes(StandardCharsets.UTF_8));
        String signingInput = VERSION + "." + encodedPayload;
        String signature = Base64.getUrlEncoder().withoutPadding().encodeToString(sign(signingInput));
        return new IssuedToken(signingInput + "." + signature, ttlSeconds);
    }

    public Optional<Long> resolve(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) return Optional.empty();
        String[] parts = authorization.substring("Bearer ".length()).trim().split("\\.");
        if (parts.length != 3 || !VERSION.equals(parts[0])) return Optional.empty();
        try {
            byte[] suppliedSignature = Base64.getUrlDecoder().decode(parts[2]);
            byte[] expectedSignature = sign(parts[0] + "." + parts[1]);
            if (!MessageDigest.isEqual(expectedSignature, suppliedSignature)) return Optional.empty();
            String payload = new String(Base64.getUrlDecoder().decode(parts[1]), StandardCharsets.UTF_8);
            String[] values = payload.split(":");
            if (values.length != 3) return Optional.empty();
            long userId = Long.parseLong(values[0]);
            long expiresAt = Long.parseLong(values[1]);
            if (userId <= 0 || expiresAt < clock.instant().getEpochSecond()) return Optional.empty();
            return Optional.of(userId);
        } catch (RuntimeException exception) {
            return Optional.empty();
        }
    }

    public long ttlSeconds() {
        return ttlSeconds;
    }

    private byte[] sign(String value) {
        try {
            Mac mac = Mac.getInstance(HMAC_ALGORITHM);
            mac.init(new SecretKeySpec(secret, HMAC_ALGORITHM));
            return mac.doFinal(value.getBytes(StandardCharsets.UTF_8));
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to sign authentication token", exception);
        }
    }

    public record IssuedToken(String value, long expiresInSeconds) {
    }
}
