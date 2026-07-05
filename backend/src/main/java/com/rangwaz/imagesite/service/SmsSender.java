package com.rangwaz.imagesite.service;

import java.time.Duration;

/**
 * Sends verification codes through a real SMS provider.
 */
public interface SmsSender {
    /**
     * Sends one verification code.
     *
     * @param phone normalized phone number
     * @param code verification code
     * @param ttl code time-to-live
     * @param scene request scene
     */
    void sendVerificationCode(String phone, String code, Duration ttl, String scene);
}
