package com.rangwaz.imagesite.common.auth;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AuthTokenCodecTest {
    private static final String SECRET = "test-secret-with-at-least-thirty-two-characters";

    @Test
    void springCreatesCodecFromConfiguredConstructor() {
        new ApplicationContextRunner()
                .withPropertyValues(
                        "app.auth.token-secret=" + SECRET,
                        "app.auth.token-ttl-seconds=3600"
                )
                .withBean(AuthTokenCodec.class)
                .run(context -> {
                    assertEquals(1, context.getBeansOfType(AuthTokenCodec.class).size());
                    assertEquals(3600, context.getBean(AuthTokenCodec.class).ttlSeconds());
                });
    }

    @Test
    void signedTokenResolvesOriginalUser() {
        Clock clock = Clock.fixed(Instant.parse("2026-07-12T08:00:00Z"), ZoneOffset.UTC);
        AuthTokenCodec codec = new AuthTokenCodec(SECRET, 3600, clock);

        AuthTokenCodec.IssuedToken issued = codec.issue(42L);

        assertEquals(42L, codec.resolve("Bearer " + issued.value()).orElseThrow());
        assertEquals(3600, issued.expiresInSeconds());
    }

    @Test
    void tamperedTokenIsRejected() {
        Clock clock = Clock.fixed(Instant.parse("2026-07-12T08:00:00Z"), ZoneOffset.UTC);
        AuthTokenCodec codec = new AuthTokenCodec(SECRET, 3600, clock);
        String token = codec.issue(42L).value();
        String[] parts = token.split("\\.");
        String changedPayload = (parts[1].startsWith("A") ? "B" : "A") + parts[1].substring(1);
        String tampered = parts[0] + "." + changedPayload + "." + parts[2];

        assertTrue(codec.resolve("Bearer " + tampered).isEmpty());
    }

    @Test
    void expiredTokenIsRejected() {
        AuthTokenCodec issuer = new AuthTokenCodec(
                SECRET,
                300,
                Clock.fixed(Instant.parse("2026-07-12T08:00:00Z"), ZoneOffset.UTC)
        );
        String token = issuer.issue(42L).value();
        AuthTokenCodec verifier = new AuthTokenCodec(
                SECRET,
                300,
                Clock.fixed(Instant.parse("2026-07-12T08:06:00Z"), ZoneOffset.UTC)
        );

        assertTrue(verifier.resolve("Bearer " + token).isEmpty());
    }
}
