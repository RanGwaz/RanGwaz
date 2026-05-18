package com.rangwaz.imagesite.common.auth;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.service.AuthService;
import org.springframework.stereotype.Component;

import java.util.Optional;

/**
 * Resolves optional and required users from bearer tokens.
 */
@Component
public class AuthContext {
    private final AuthService authService;

    /**
     * Creates the auth context helper.
     *
     * @param authService auth service
     */
    public AuthContext(AuthService authService) {
        this.authService = authService;
    }

    /**
     * Resolves an optional user id.
     *
     * @param authorization authorization header
     * @return optional user id
     */
    public Optional<Long> currentUserId(String authorization) {
        return authService.resolveUserId(authorization);
    }

    /**
     * Resolves a required user id.
     *
     * @param authorization authorization header
     * @return user id
     */
    public Long requireUserId(String authorization) {
        return currentUserId(authorization).orElseThrow(() -> new BusinessException("AUTH_REQUIRED", "请先登录"));
    }
}
