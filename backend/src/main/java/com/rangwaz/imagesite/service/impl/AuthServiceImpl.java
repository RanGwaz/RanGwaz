package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.AuthService;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.Optional;
import java.util.UUID;

/**
 * Token-based local authentication service for development.
 */
@Service
public class AuthServiceImpl implements AuthService {
    private static final long TOKEN_TTL_SECONDS = 86_400L;
    private final UserMapper userMapper;
    private final UserServiceImpl userService;

    /**
     * Creates the auth service.
     *
     * @param userMapper user mapper
     * @param userService user service
     */
    public AuthServiceImpl(UserMapper userMapper, UserServiceImpl userService) {
        this.userMapper = userMapper;
        this.userService = userService;
    }

    /**
     * Registers a user.
     *
     * @param request register request
     * @return token response
     */
    @Override
    public ApiDtos.AuthTokenResponse register(ApiDtos.RegisterRequest request) {
        if (userMapper.findByUsername(request.username()) != null) {
            throw new BusinessException("USERNAME_EXISTS", "用户名已存在");
        }
        UserEntity user = new UserEntity();
        user.setUsername(request.username().trim());
        user.setPasswordHash(PasswordHasher.hash(request.password()));
        user.setNickname(request.nickname().trim());
        user.setAvatarUrl("https://api.dicebear.com/9.x/adventurer/svg?seed=" + user.getUsername());
        user.setBio("用图片记录今天的灵感");
        user.setStatus("ACTIVE");
        userMapper.insert(user);
        return tokenResponse(user);
    }

    /**
     * Logs a user in.
     *
     * @param request login request
     * @return token response
     */
    @Override
    public ApiDtos.AuthTokenResponse login(ApiDtos.LoginRequest request) {
        UserEntity user = userMapper.findByUsername(request.username());
        if (user == null || !PasswordHasher.matches(request.password(), user.getPasswordHash())) {
            throw new BusinessException("BAD_CREDENTIALS", "用户名或密码错误");
        }
        return tokenResponse(user);
    }

    /**
     * Resolves the current user from a bearer token.
     *
     * @param authorization authorization header
     * @return optional user id
     */
    @Override
    public Optional<Long> resolveUserId(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) return Optional.empty();
        String token = authorization.substring("Bearer ".length()).trim();
        try {
            String raw = new String(Base64.getUrlDecoder().decode(token), StandardCharsets.UTF_8);
            String[] parts = raw.split(":");
            if (parts.length < 3) return Optional.empty();
            long userId = Long.parseLong(parts[0]);
            long expiresAt = Long.parseLong(parts[1]);
            if (expiresAt < Instant.now().getEpochSecond()) return Optional.empty();
            return Optional.of(userId);
        } catch (RuntimeException exception) {
            return Optional.empty();
        }
    }

    /**
     * Gets the current authenticated user summary.
     *
     * @param userId user id
     * @return token response with current user
     */
    @Override
    public ApiDtos.AuthTokenResponse me(Long userId) {
        return new ApiDtos.AuthTokenResponse("", "Bearer", TOKEN_TTL_SECONDS, userService.findSummary(userId));
    }

    /**
     * Builds a token response.
     *
     * @param user user entity
     * @return token response
     */
    private ApiDtos.AuthTokenResponse tokenResponse(UserEntity user) {
        long expiresAt = Instant.now().plusSeconds(TOKEN_TTL_SECONDS).getEpochSecond();
        String raw = user.getId() + ":" + expiresAt + ":" + UUID.randomUUID();
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
        return new ApiDtos.AuthTokenResponse(token, "Bearer", TOKEN_TTL_SECONDS, userService.toSummary(user));
    }
}
