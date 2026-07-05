package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.AuthService;
import com.rangwaz.imagesite.service.SmsSender;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;

/**
 * Token-based local authentication service.
 */
@Service
public class AuthServiceImpl implements AuthService {
    private static final long TOKEN_TTL_SECONDS = 86_400L;
    private static final Pattern MAINLAND_PHONE = Pattern.compile("^1[3-9]\\d{9}$");

    private final UserMapper userMapper;
    private final UserServiceImpl userService;
    private final Optional<SmsSender> smsSender;
    private final SecureRandom random = new SecureRandom();
    private final Map<String, SmsChallenge> smsChallenges = new ConcurrentHashMap<>();
    private final Map<String, Object> smsLocks = new ConcurrentHashMap<>();

    @Value("${app.sms.mock:true}")
    private boolean smsMock;

    @Value("${app.sms.dev-code:}")
    private String smsDevCode;

    @Value("${app.sms.code-ttl-seconds:300}")
    private long smsCodeTtlSeconds;

    @Value("${app.sms.cooldown-seconds:60}")
    private long smsCooldownSeconds;

    /**
     * Creates the auth service.
     *
     * @param userMapper user mapper
     * @param userService user service
     * @param smsSenderProvider optional SMS provider
     */
    public AuthServiceImpl(UserMapper userMapper,
                           UserServiceImpl userService,
                           ObjectProvider<SmsSender> smsSenderProvider) {
        this.userMapper = userMapper;
        this.userService = userService;
        this.smsSender = Optional.ofNullable(smsSenderProvider.getIfAvailable());
    }

    /**
     * Registers a user.
     *
     * @param request register request
     * @return token response
     */
    @Override
    public ApiDtos.AuthTokenResponse register(ApiDtos.RegisterRequest request) {
        String username = request.username().trim();
        if (userMapper.findByUsername(username) != null) {
            throw new BusinessException("USERNAME_EXISTS", "用户名已存在");
        }
        String password = requireUsablePassword(request.password());
        UserEntity user = new UserEntity();
        user.setUsername(username);
        user.setPasswordHash(PasswordHasher.hash(password));
        user.setNickname(request.nickname().trim());
        user.setAvatarUrl("https://api.dicebear.com/9.x/adventurer/svg?seed=" + user.getUsername());
        user.setBio("用图片收集灵感，用审美整理世界。");
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
        UserEntity user = userMapper.findByUsername(request.username().trim());
        if (user == null || !PasswordHasher.matches(request.password(), user.getPasswordHash())) {
            throw new BusinessException("BAD_CREDENTIALS", "用户名或密码错误");
        }
        return tokenResponse(user);
    }

    /**
     * Sends an SMS verification code. Local development returns the code in the API response.
     *
     * @param request SMS code request
     * @return send result
     */
    @Override
    public ApiDtos.SmsCodeResponse sendSmsCode(ApiDtos.SendSmsCodeRequest request) {
        String phone = normalizePhone(request.phone());
        Object lock = smsLocks.computeIfAbsent(phone, ignored -> new Object());
        synchronized (lock) {
            boolean registered = userMapper.findByPhone(phone) != null;
            long now = Instant.now().getEpochSecond();
            SmsChallenge existing = smsChallenges.get(phone);
            if (existing != null && existing.sentAt() + smsCooldownSeconds > now) {
                long retryAfter = existing.sentAt() + smsCooldownSeconds - now;
                throw new BusinessException("SMS_TOO_FREQUENT", "验证码发送太频繁，请 " + retryAfter + " 秒后再试");
            }
            String code = newSmsCode();
            if (smsMock) {
                System.out.println("[SMS mock] " + phone + " code=" + code);
            } else {
                SmsSender sender = smsSender.orElseThrow(() ->
                        new BusinessException("SMS_PROVIDER_NOT_CONFIGURED", "真实短信服务尚未启用，请先配置短信发送适配器"));
                sender.sendVerificationCode(phone, code, Duration.ofSeconds(smsCodeTtlSeconds), request.scene());
            }
            smsChallenges.put(phone, new SmsChallenge(code, now + smsCodeTtlSeconds, now, 0));
            return new ApiDtos.SmsCodeResponse(true, smsMock ? code : null, smsCodeTtlSeconds, smsCooldownSeconds, registered);
        }
    }

    /**
     * Logs in with a verified phone number, creating the account on first use.
     *
     * @param request phone login request
     * @return token response
     */
    @Override
    public ApiDtos.AuthTokenResponse loginWithPhone(ApiDtos.PhoneLoginRequest request) {
        String phone = normalizePhone(request.phone());
        assertSmsCode(phone, request.code());
        UserEntity user = userMapper.findByPhone(phone);
        if (user == null) {
            String password = requireMatchingPassword(request.password(), request.passwordConfirm());
            user = createPhoneUser(phone, password);
        } else {
            user = maybeUpdatePassword(user, request.password(), request.passwordConfirm());
        }
        smsChallenges.remove(phone);
        return tokenResponse(user);
    }

    /**
     * Logs in with a phone number and password.
     *
     * @param request phone-password login request
     * @return token response
     */
    @Override
    public ApiDtos.AuthTokenResponse loginWithPhonePassword(ApiDtos.PhonePasswordLoginRequest request) {
        String phone = normalizePhone(request.phone());
        UserEntity user = userMapper.findByPhone(phone);
        if (user == null || !PasswordHasher.matches(request.password(), user.getPasswordHash())) {
            throw new BusinessException("BAD_CREDENTIALS", "手机号或密码错误");
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

    private ApiDtos.AuthTokenResponse tokenResponse(UserEntity user) {
        long expiresAt = Instant.now().plusSeconds(TOKEN_TTL_SECONDS).getEpochSecond();
        String raw = user.getId() + ":" + expiresAt + ":" + UUID.randomUUID();
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
        return new ApiDtos.AuthTokenResponse(token, "Bearer", TOKEN_TTL_SECONDS, userService.toSummary(user));
    }

    private String normalizePhone(String rawPhone) {
        String phone = rawPhone == null ? "" : rawPhone.trim().replaceAll("[\\s-]", "");
        if (phone.startsWith("+86")) phone = phone.substring(3);
        else if (phone.startsWith("86") && phone.length() == 13) phone = phone.substring(2);
        if (!MAINLAND_PHONE.matcher(phone).matches()) {
            throw new BusinessException("INVALID_PHONE", "请输入有效的中国大陆手机号");
        }
        return phone;
    }

    private String newSmsCode() {
        String fixedCode = smsDevCode == null ? "" : smsDevCode.trim();
        if (fixedCode.matches("\\d{4,8}")) return fixedCode;
        return String.format("%06d", random.nextInt(1_000_000));
    }

    private void assertSmsCode(String phone, String rawCode) {
        String code = rawCode == null ? "" : rawCode.trim();
        SmsChallenge challenge = smsChallenges.get(phone);
        long now = Instant.now().getEpochSecond();
        if (challenge == null || challenge.expiresAt() < now) {
            smsChallenges.remove(phone);
            throw new BusinessException("SMS_CODE_EXPIRED", "验证码已过期，请重新获取");
        }
        if (!challenge.code().equals(code)) {
            int attempts = challenge.attempts() + 1;
            if (attempts >= 5) {
                smsChallenges.remove(phone);
                throw new BusinessException("BAD_SMS_CODE_LOCKED", "验证码错误次数过多，请重新获取");
            }
            smsChallenges.put(phone, new SmsChallenge(challenge.code(), challenge.expiresAt(), challenge.sentAt(), attempts));
            throw new BusinessException("BAD_SMS_CODE", "验证码错误");
        }
    }

    private String requireUsablePassword(String rawPassword) {
        String password = rawPassword == null ? "" : rawPassword.trim();
        if (password.length() < 6 || password.length() > 64) {
            throw new BusinessException("INVALID_PASSWORD", "密码需为 6-64 位");
        }
        return password;
    }

    private String requireMatchingPassword(String rawPassword, String rawPasswordConfirm) {
        String password = requireUsablePassword(rawPassword);
        String passwordConfirm = rawPasswordConfirm == null ? "" : rawPasswordConfirm.trim();
        if (!password.equals(passwordConfirm)) {
            throw new BusinessException("PASSWORD_MISMATCH", "两次输入的密码不一致");
        }
        return password;
    }

    private UserEntity maybeUpdatePassword(UserEntity user, String rawPassword, String rawPasswordConfirm) {
        String password = rawPassword == null ? "" : rawPassword.trim();
        String passwordConfirm = rawPasswordConfirm == null ? "" : rawPasswordConfirm.trim();
        if (password.isEmpty() && passwordConfirm.isEmpty()) {
            return user;
        }
        String matchingPassword = requireMatchingPassword(password, passwordConfirm);
        String passwordHash = PasswordHasher.hash(matchingPassword);
        userMapper.updatePassword(user.getId(), passwordHash);
        user.setPasswordHash(passwordHash);
        return user;
    }

    private UserEntity createPhoneUser(String phone, String password) {
        UserEntity user = new UserEntity();
        user.setPhone(phone);
        user.setUsername(uniquePhoneUsername(phone));
        user.setPasswordHash(PasswordHasher.hash(password));
        user.setNickname("手机用户" + phone.substring(Math.max(0, phone.length() - 4)));
        user.setAvatarUrl("https://api.dicebear.com/9.x/adventurer/svg?seed=" + user.getUsername());
        user.setBio("用手机号登录 Vibelo。");
        user.setStatus("ACTIVE");
        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException exception) {
            throw new BusinessException("PHONE_EXISTS", "该手机号已注册，请直接登录");
        }
        return user;
    }

    private String uniquePhoneUsername(String phone) {
        String digits = phone.replaceAll("\\D", "");
        String base = "phone_" + (digits.length() > 20 ? digits.substring(digits.length() - 20) : digits);
        String username = base;
        int suffix = 1;
        while (userMapper.findByUsername(username) != null) {
            username = base + "_" + suffix++;
        }
        return username;
    }

    private record SmsChallenge(String code, long expiresAt, long sentAt, int attempts) {
    }
}
