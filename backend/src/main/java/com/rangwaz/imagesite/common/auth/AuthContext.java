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
     * Gets the current optional user id.
     *
     * @param authorization authorization header
     * @return user id if the token is valid
     */
    public Optional<Long> currentUserId(String authorization) {
        return authService.resolveUserId(authorization);
    }

    /**
     * Requires the current user id.
     *
     * @param authorization authorization header
     * @return user id
     */
    public Long requireUserId(String authorization) {
        return currentUserId(authorization).orElseThrow(() -> new BusinessException("AUTH_REQUIRED", "请先登录"));
    }
}
