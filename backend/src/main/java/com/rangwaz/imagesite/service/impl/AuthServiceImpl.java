package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.common.auth.AuthTokenCodec;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.AuthService;
import com.rangwaz.imagesite.service.SmsChallengeStore;
import com.rangwaz.imagesite.service.SmsSender;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.Duration;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Token-based local authentication service.
 */
@Service
public class AuthServiceImpl implements AuthService {
    private static final Pattern MAINLAND_PHONE = Pattern.compile("^1[3-9]\\d{9}$");

    private final UserMapper userMapper;
    private final UserServiceImpl userService;
    private final Optional<SmsSender> smsSender;
    private final AuthTokenCodec tokenCodec;
    private final SmsChallengeStore smsChallengeStore;
    private final SecureRandom random = new SecureRandom();

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
                           ObjectProvider<SmsSender> smsSenderProvider,
                           AuthTokenCodec tokenCodec,
                           SmsChallengeStore smsChallengeStore) {
        this.userMapper = userMapper;
        this.userService = userService;
        this.smsSender = Optional.ofNullable(smsSenderProvider.getIfAvailable());
        this.tokenCodec = tokenCodec;
        this.smsChallengeStore = smsChallengeStore;
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
        Duration cooldown = Duration.ofSeconds(smsCooldownSeconds);
        if (!smsChallengeStore.reserveSend(phone, cooldown)) {
            long retryAfter = smsChallengeStore.retryAfterSeconds(phone, smsCooldownSeconds);
            throw new BusinessException("SMS_TOO_FREQUENT", "验证码发送太频繁，请 " + retryAfter + " 秒后再试");
        }
        boolean registered = userMapper.findByPhone(phone) != null;
        String code = newSmsCode();
        try {
            if (smsMock) {
                System.out.println("[SMS mock] " + phone + " code=" + code);
            } else {
                SmsSender sender = smsSender.orElseThrow(() ->
                        new BusinessException("SMS_PROVIDER_NOT_CONFIGURED", "真实短信服务尚未启用，请先配置短信发送适配器"));
                sender.sendVerificationCode(phone, code, Duration.ofSeconds(smsCodeTtlSeconds), request.scene());
            }
            smsChallengeStore.save(phone, code, Duration.ofSeconds(smsCodeTtlSeconds));
        } catch (RuntimeException exception) {
            smsChallengeStore.releaseSend(phone);
            throw exception;
        }
        return new ApiDtos.SmsCodeResponse(true, smsMock ? code : null, smsCodeTtlSeconds, smsCooldownSeconds, registered);
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
            String password = optionalMatchingPassword(request.password(), request.passwordConfirm());
            user = createPhoneUser(phone, password);
        } else {
            user = maybeUpdatePassword(user, request.password(), request.passwordConfirm());
        }
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
        return tokenCodec.resolve(authorization);
    }

    /**
     * Gets the current authenticated user summary.
     *
     * @param userId user id
     * @return token response with current user
     */
    @Override
    public ApiDtos.AuthTokenResponse me(Long userId) {
        return new ApiDtos.AuthTokenResponse("", "Bearer", tokenCodec.ttlSeconds(), userService.findSummary(userId));
    }

    private ApiDtos.AuthTokenResponse tokenResponse(UserEntity user) {
        AuthTokenCodec.IssuedToken token = tokenCodec.issue(user.getId());
        return new ApiDtos.AuthTokenResponse(token.value(), "Bearer", token.expiresInSeconds(), userService.toSummary(user));
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
        long result = smsChallengeStore.verifyAndConsume(phone, code, 5);
        if (result == -2) {
            throw new BusinessException("SMS_CODE_EXPIRED", "验证码已过期，请重新获取");
        }
        if (result == -1) {
            throw new BusinessException("BAD_SMS_CODE_LOCKED", "验证码错误次数过多，请重新获取");
        }
        if (result == 0) {
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
    private String optionalMatchingPassword(String rawPassword, String rawPasswordConfirm) {
        String password = rawPassword == null ? "" : rawPassword.trim();
        String confirmation = rawPasswordConfirm == null ? "" : rawPasswordConfirm.trim();
        if (password.isEmpty() && confirmation.isEmpty()) {
            return UUID.randomUUID() + "-" + UUID.randomUUID();
        }
        return requireMatchingPassword(password, confirmation);
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

}
