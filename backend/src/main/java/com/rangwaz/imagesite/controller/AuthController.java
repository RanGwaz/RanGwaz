package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Authentication endpoints for local development accounts.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final AuthService authService;
    private final AuthContext authContext;

    /**
     * Creates the auth controller.
     *
     * @param authService auth service
     * @param authContext auth context
     */
    public AuthController(AuthService authService, AuthContext authContext) {
        this.authService = authService;
        this.authContext = authContext;
    }

    /**
     * Registers a new account.
     *
     * @param request register request
     * @return token response
     */
    @PostMapping("/register")
    public ApiResponse<ApiDtos.AuthTokenResponse> register(@Valid @RequestBody ApiDtos.RegisterRequest request) {
        return ApiResponse.ok(authService.register(request));
    }

    /**
     * Logs in with username and password.
     *
     * @param request login request
     * @return token response
     */
    @PostMapping("/login")
    public ApiResponse<ApiDtos.AuthTokenResponse> login(@Valid @RequestBody ApiDtos.LoginRequest request) {
        return ApiResponse.ok(authService.login(request));
    }

    /**
     * Returns the current user.
     *
     * @param authorization authorization header
     * @return token response with current user
     */
    @GetMapping("/me")
    public ApiResponse<ApiDtos.AuthTokenResponse> me(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return ApiResponse.ok(authService.me(authContext.requireUserId(authorization)));
    }

    /**
     * Logs out locally.
     *
     * @return empty response
     */
    @PostMapping("/logout")
    public ApiResponse<Void> logout() {
        return ApiResponse.ok(null);
    }
}
