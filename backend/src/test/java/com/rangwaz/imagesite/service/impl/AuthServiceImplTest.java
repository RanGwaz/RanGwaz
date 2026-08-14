package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.auth.AuthTokenCodec;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.SmsChallengeStore;
import com.rangwaz.imagesite.service.SmsSender;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.test.util.ReflectionTestUtils;

import static com.rangwaz.imagesite.common.auth.PasswordHasher.hash;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthServiceImplTest {
    private UserMapper userMapper;
    private SmsChallengeStore smsChallengeStore;
    private AuthTokenCodec tokenCodec;
    private AuthServiceImpl authService;

    @BeforeEach
    void setUp() {
        userMapper = mock(UserMapper.class);
        UserServiceImpl userService = mock(UserServiceImpl.class);
        @SuppressWarnings("unchecked")
        ObjectProvider<SmsSender> smsSenderProvider = mock(ObjectProvider.class);
        tokenCodec = mock(AuthTokenCodec.class);
        smsChallengeStore = mock(SmsChallengeStore.class);
        authService = new AuthServiceImpl(userMapper, userService, smsSenderProvider, tokenCodec, smsChallengeStore);
        when(tokenCodec.issue(org.mockito.ArgumentMatchers.anyLong()))
                .thenReturn(new AuthTokenCodec.IssuedToken("token", 3600));
        doAnswer(invocation -> {
            UserEntity user = invocation.getArgument(0);
            if (user.getId() == null) user.setId(99L);
            return null;
        }).when(userMapper).insert(org.mockito.ArgumentMatchers.any(UserEntity.class));
    }

    @Test
    void firstPhoneSignInRequiresTheUserToChooseAndConfirmAPassword() {
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);
        when(userMapper.findByPhone("13800138000")).thenReturn(null);

        assertThatThrownBy(() -> authService.loginWithPhone(
                new ApiDtos.PhoneLoginRequest("13800138000", "123456", null, null)))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("PASSWORD_REQUIRED"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void existingActiveUserCanSignInWithOnlyTheSmsCodeWithoutChangingPassword() {
        UserEntity user = phoneUser("ACTIVE", "existing-hash");
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);
        when(userMapper.findByPhone("13800138000")).thenReturn(user);

        ApiDtos.AuthTokenResponse response = authService.loginWithPhone(
                new ApiDtos.PhoneLoginRequest("13800138000", "123456", null, null));

        assertThat(response.accessToken()).isEqualTo("token");
        verify(userMapper, never()).updatePassword(org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void smsSignInRejectsAnInactiveAccount() {
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);
        when(userMapper.findByPhone("13800138000")).thenReturn(phoneUser("DISABLED", "existing-hash"));

        assertThatThrownBy(() -> authService.loginWithPhone(
                new ApiDtos.PhoneLoginRequest("13800138000", "123456", null, null)))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("ACCOUNT_DISABLED"));
    }

    @Test
    void verifiedExistingUserCanExplicitlyReplaceThePassword() {
        UserEntity user = phoneUser("ACTIVE", "old-hash");
        when(smsChallengeStore.verifyAndConsume("13800138000", "password_reset", "123456", 5)).thenReturn(1L);
        when(userMapper.findByPhone("13800138000")).thenReturn(user);

        authService.resetPhonePassword(new ApiDtos.PhonePasswordResetRequest(
                "13800138000", "123456", "new password", "new password"));

        verify(userMapper).updatePassword(org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.argThat(hash -> !"old-hash".equals(hash)));
    }

    @Test
    void loginSceneCodeCannotBeUsedToResetAPassword() {
        UserEntity user = phoneUser("ACTIVE", "old-hash");
        when(userMapper.findByPhone("13800138000")).thenReturn(user);
        when(smsChallengeStore.verifyAndConsume(
                "13800138000", "login", "123456", 5)).thenReturn(1L);

        assertThatThrownBy(() -> authService.resetPhonePassword(
                new ApiDtos.PhonePasswordResetRequest(
                        "13800138000", "123456", "new password", "new password")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("BAD_SMS_CODE"));
        verify(smsChallengeStore).verifyAndConsume(
                "13800138000", "password_reset", "123456", 5);
        verify(userMapper, never()).updatePassword(
                org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void successfulUsernamePasswordLoginTransparentlyUpgradesALegacyHash() {
        String legacyHash = legacyHash("old password");
        UserEntity user = usernameUser("ACTIVE", legacyHash);
        when(userMapper.findByUsername("alice")).thenReturn(user);
        when(userMapper.updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.anyString())).thenReturn(1);

        authService.login(new ApiDtos.LoginRequest(" alice ", "old password"));

        verify(userMapper).updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.argThat(candidate -> candidate.startsWith("{bcrypt}$2")));
    }

    @Test
    void modernHashIsNotRewrittenDuringPasswordLogin() {
        String modernHash = hash("current password");
        when(userMapper.findByUsername("alice")).thenReturn(usernameUser("ACTIVE", modernHash));

        authService.login(new ApiDtos.LoginRequest("alice", "current password"));

        verify(userMapper, never()).updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void phonePasswordLoginAlsoUpgradesALegacyHash() {
        String legacyHash = legacyHash("old password");
        when(userMapper.findByPhone("13800138000")).thenReturn(phoneUser("ACTIVE", legacyHash));
        when(userMapper.updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.anyString())).thenReturn(1);

        authService.loginWithPhonePassword(
                new ApiDtos.PhonePasswordLoginRequest("13800138000", "old password"));

        verify(userMapper).updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.argThat(candidate -> candidate.startsWith("{bcrypt}$2")));
    }

    @Test
    void correctPasswordDoesNotSignInAnInactiveAccount() {
        String legacyHash = legacyHash("old password");
        when(userMapper.findByUsername("alice")).thenReturn(usernameUser("DISABLED", legacyHash));

        assertThatThrownBy(() -> authService.login(
                new ApiDtos.LoginRequest("alice", "old password")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("ACCOUNT_DISABLED"));
        verify(tokenCodec, never()).issue(org.mockito.ArgumentMatchers.anyLong());
    }

    @Test
    void legacyPasswordOverTheBcryptByteLimitStillSignsInWithoutUnsafeUpgrade() {
        String legacyPassword = "旧".repeat(25);
        String legacyHash = legacyHash(legacyPassword);
        when(userMapper.findByUsername("alice"))
                .thenReturn(usernameUser("ACTIVE", legacyHash));

        ApiDtos.AuthTokenResponse response = authService.login(
                new ApiDtos.LoginRequest("alice", legacyPassword));

        assertThat(response.accessToken()).isEqualTo("token");
        verify(userMapper, never()).updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void sixCharacterLegacyPasswordStillSignsInAndUpgrades() {
        String legacyHash = legacyHash("old123");
        when(userMapper.findByUsername("alice"))
                .thenReturn(usernameUser("ACTIVE", legacyHash));
        when(userMapper.updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.anyString())).thenReturn(1);

        ApiDtos.AuthTokenResponse response = authService.login(
                new ApiDtos.LoginRequest("alice", "old123"));

        assertThat(response.accessToken()).isEqualTo("token");
        verify(userMapper).updatePasswordIfHashMatches(
                org.mockito.ArgumentMatchers.eq(7L),
                org.mockito.ArgumentMatchers.eq(legacyHash),
                org.mockito.ArgumentMatchers.argThat(candidate -> candidate.startsWith("{bcrypt}$2")));
    }

    @Test
    void firstPhoneRegistrationPreservesPasswordWhitespaceExactly() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);
        org.mockito.ArgumentCaptor<UserEntity> userCaptor = org.mockito.ArgumentCaptor.forClass(UserEntity.class);

        authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", " password ", " password "));

        verify(userMapper).insert(userCaptor.capture());
        assertThat(com.rangwaz.imagesite.common.auth.PasswordHasher.matches(
                " password ", userCaptor.getValue().getPasswordHash())).isTrue();
        assertThat(com.rangwaz.imagesite.common.auth.PasswordHasher.matches(
                "password", userCaptor.getValue().getPasswordHash())).isFalse();
    }

    @Test
    void passwordOverTheBcryptByteLimitIsRejectedBeforeConsumingTheSmsCode() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);
        String password = "密".repeat(25);

        assertThatThrownBy(() -> authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", password, password)))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("PASSWORD_TOO_LONG"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void resetValidatesTheNewPasswordBeforeConsumingTheSmsCode() {
        when(userMapper.findByPhone("13800138000")).thenReturn(phoneUser("ACTIVE", "old-hash"));

        assertThatThrownBy(() -> authService.resetPhonePassword(new ApiDtos.PhonePasswordResetRequest(
                "13800138000", "123456", "short", "short")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("INVALID_PASSWORD"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void mismatchedRegistrationPasswordsDoNotConsumeTheSmsCode() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);

        assertThatThrownBy(() -> authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", "new password", "other password")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("PASSWORD_MISMATCH"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void existingSmsLoginNeverImplicitlyChangesThePassword() {
        UserEntity user = phoneUser("ACTIVE", hash("current password"));
        when(userMapper.findByPhone("13800138000")).thenReturn(user);
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);

        authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", "unexpected replacement", "unexpected replacement"));

        verify(userMapper, never()).updatePassword(
                org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void smsCodeRejectsUnknownScenesBeforeReservingTheCooldown() {
        assertThatThrownBy(() -> authService.sendSmsCode(
                new ApiDtos.SendSmsCodeRequest("13800138000", "register")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("INVALID_SMS_SCENE"));

        verify(smsChallengeStore, never()).reserveSend(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any());
    }

    @Test
    void passwordResetCodeRequiresAnExistingAccountBeforeReservingTheCooldown() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);

        assertThatThrownBy(() -> authService.sendSmsCode(
                new ApiDtos.SendSmsCodeRequest("13800138000", "password_reset")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("ACCOUNT_NOT_FOUND"));

        verify(smsChallengeStore, never()).reserveSend(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any());
    }

    @Test
    void concurrentPhoneRegistrationReturnsTheAccountThatWonTheUniqueKeyRace() {
        UserEntity winner = phoneUser("ACTIVE", hash("winner password"));
        when(userMapper.findByPhone("13800138000")).thenReturn(null, winner);
        when(smsChallengeStore.verifyAndConsume("13800138000", "login", "123456", 5)).thenReturn(1L);
        org.mockito.Mockito.doThrow(new DuplicateKeyException("duplicate phone"))
                .when(userMapper).insert(org.mockito.ArgumentMatchers.any(UserEntity.class));

        ApiDtos.AuthTokenResponse response = authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", "new password", "new password"));

        assertThat(response.accessToken()).isEqualTo("token");
        verify(tokenCodec).issue(7L);
    }

    @Test
    void whitespaceOnlyPasswordIsRejectedBeforeConsumingTheSmsCode() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);

        assertThatThrownBy(() -> authService.loginWithPhone(new ApiDtos.PhoneLoginRequest(
                "13800138000", "123456", "        ", "        ")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("PASSWORD_REQUIRED"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void resetForAnUnknownPhoneDoesNotConsumeTheSmsCode() {
        when(userMapper.findByPhone("13800138000")).thenReturn(null);

        assertThatThrownBy(() -> authService.resetPhonePassword(new ApiDtos.PhonePasswordResetRequest(
                "13800138000", "123456", "new password", "new password")))
                .isInstanceOfSatisfying(BusinessException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("ACCOUNT_NOT_FOUND"));
        verify(smsChallengeStore, never()).verifyAndConsume(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void passwordResetIsAnAllowedSmsSceneForAnExistingActiveAccount() {
        when(userMapper.findByPhone("13800138000")).thenReturn(phoneUser("ACTIVE", "hash"));
        when(smsChallengeStore.reserveSend(
                org.mockito.ArgumentMatchers.eq("13800138000"),
                org.mockito.ArgumentMatchers.eq("password_reset"), org.mockito.ArgumentMatchers.any()))
                .thenReturn(true);
        ReflectionTestUtils.setField(authService, "smsMock", true);
        ReflectionTestUtils.setField(authService, "smsDevCode", "123456");
        ReflectionTestUtils.setField(authService, "smsCodeTtlSeconds", 300L);
        ReflectionTestUtils.setField(authService, "smsCooldownSeconds", 60L);

        ApiDtos.SmsCodeResponse response = authService.sendSmsCode(
                new ApiDtos.SendSmsCodeRequest("13800138000", " PASSWORD_RESET "));

        assertThat(response.registered()).isTrue();
        verify(smsChallengeStore).save(
                org.mockito.ArgumentMatchers.eq("13800138000"),
                org.mockito.ArgumentMatchers.eq("password_reset"),
                org.mockito.ArgumentMatchers.eq("123456"),
                org.mockito.ArgumentMatchers.eq(java.time.Duration.ofSeconds(300)));
    }

    private UserEntity phoneUser(String status, String passwordHash) {
        UserEntity user = new UserEntity();
        user.setId(7L);
        user.setPhone("13800138000");
        user.setUsername("phone_13800138000");
        user.setNickname("用户");
        user.setStatus(status);
        user.setPasswordHash(passwordHash);
        return user;
    }

    private UserEntity usernameUser(String status, String passwordHash) {
        UserEntity user = phoneUser(status, passwordHash);
        user.setPhone(null);
        user.setUsername("alice");
        return user;
    }

    private String legacyHash(String rawPassword) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            return java.util.HexFormat.of().formatHex(digest.digest(
                    ("rangwaz-local-dev:" + rawPassword).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new AssertionError(exception);
        }
    }
}
