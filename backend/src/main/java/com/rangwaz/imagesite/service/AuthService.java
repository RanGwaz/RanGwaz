package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;

import java.util.Optional;

/**
 * Service interface for local username/password authentication.
 */
public interface AuthService {
    /**
     * Registers a user.
     *
     * @param request register request
     * @return token response
     */
    ApiDtos.AuthTokenResponse register(ApiDtos.RegisterRequest request);

    /**
     * Logs a user in.
     *
     * @param request login request
     * @return token response
     */
    ApiDtos.AuthTokenResponse login(ApiDtos.LoginRequest request);

    /**
     * Sends a phone verification code.
     *
     * @param request SMS code request
     * @return send result
     */
    ApiDtos.SmsCodeResponse sendSmsCode(ApiDtos.SendSmsCodeRequest request);

    /**
     * Logs in or creates a user with a verified phone number.
     *
     * @param request phone login request
     * @return token response
     */
    ApiDtos.AuthTokenResponse loginWithPhone(ApiDtos.PhoneLoginRequest request);

    /**
     * Resolves the current user from a bearer token.
     *
     * @param authorization authorization header
     * @return optional user id
     */
    Optional<Long> resolveUserId(String authorization);

    /**
     * Gets the current authenticated user summary.
     *
     * @param userId user id
     * @return token response with current user
     */
    ApiDtos.AuthTokenResponse me(Long userId);
}
