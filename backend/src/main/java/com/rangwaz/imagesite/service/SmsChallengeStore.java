package com.rangwaz.imagesite.service;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Shared, expiring SMS challenge storage for multi-instance authentication.
 */
@Component
public class SmsChallengeStore {
    private static final String CHALLENGE_PREFIX = "auth:sms:challenge:";
    private static final String COOLDOWN_PREFIX = "auth:sms:cooldown:";
    private static final DefaultRedisScript<Long> VERIFY_SCRIPT = new DefaultRedisScript<>(
            """
            local value = redis.call('GET', KEYS[1])
            if not value then return -2 end
            local separator = string.find(value, '|', 1, true)
            if not separator then
              redis.call('DEL', KEYS[1])
              return -2
            end
            local expected = string.sub(value, 1, separator - 1)
            local attempts = tonumber(string.sub(value, separator + 1)) or 0
            if expected == ARGV[1] then
              redis.call('DEL', KEYS[1])
              return 1
            end
            attempts = attempts + 1
            if attempts >= tonumber(ARGV[2]) then
              redis.call('DEL', KEYS[1])
              return -1
            end
            redis.call('SET', KEYS[1], expected .. '|' .. attempts, 'KEEPTTL')
            return 0
            """,
            Long.class
    );

    private final StringRedisTemplate redis;

    public SmsChallengeStore(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public boolean reserveSend(String phone, String scene, Duration cooldown) {
        return Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(cooldownKey(phone, scene), "1", cooldown));
    }

    public long retryAfterSeconds(String phone, String scene, long fallbackSeconds) {
        Long ttl = redis.getExpire(cooldownKey(phone, scene), TimeUnit.SECONDS);
        return ttl == null || ttl < 1 ? fallbackSeconds : ttl;
    }

    public void releaseSend(String phone, String scene) {
        redis.delete(cooldownKey(phone, scene));
    }

    public void save(String phone, String scene, String code, Duration ttl) {
        redis.opsForValue().set(challengeKey(phone, scene), code + "|0", ttl);
    }

    /**
     * @return 1 verified, 0 incorrect, -1 too many attempts, -2 missing or expired
     */
    public long verifyAndConsume(String phone, String scene, String code, int maxAttempts) {
        Long result = redis.execute(
                VERIFY_SCRIPT,
                List.of(challengeKey(phone, scene)),
                code,
                Integer.toString(maxAttempts)
        );
        return result == null ? -2 : result;
    }

    private String challengeKey(String phone, String scene) {
        return CHALLENGE_PREFIX + scene + ":" + phone;
    }

    private String cooldownKey(String phone, String scene) {
        return COOLDOWN_PREFIX + scene + ":" + phone;
    }
}
