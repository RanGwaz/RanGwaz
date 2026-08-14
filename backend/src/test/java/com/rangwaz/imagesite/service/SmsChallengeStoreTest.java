package com.rangwaz.imagesite.service;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class SmsChallengeStoreTest {
    @Test
    void loginAndPasswordResetChallengesUseDifferentRedisKeys() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SmsChallengeStore store = new SmsChallengeStore(redis);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<String>> keys = ArgumentCaptor.forClass(List.class);

        store.verifyAndConsume("13800138000", "login", "123456", 5);
        store.verifyAndConsume("13800138000", "password_reset", "123456", 5);

        verify(redis, org.mockito.Mockito.times(2)).execute(
                any(RedisScript.class), keys.capture(), eq("123456"), eq("5"));
        assertThat(keys.getAllValues()).containsExactly(
                List.of("auth:sms:challenge:login:13800138000"),
                List.of("auth:sms:challenge:password_reset:13800138000"));
    }
}
