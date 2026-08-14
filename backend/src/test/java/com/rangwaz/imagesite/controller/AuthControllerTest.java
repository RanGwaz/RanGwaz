package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.AuthService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthControllerTest {
    @Test
    void phonePasswordResetDelegatesTheVerifiedRequestAndReturnsTheFreshToken() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService, mock(AuthContext.class));
        ApiDtos.PhonePasswordResetRequest request = new ApiDtos.PhonePasswordResetRequest(
                "13800138000", "123456", "new password", "new password");
        ApiDtos.AuthTokenResponse token = new ApiDtos.AuthTokenResponse("token", "Bearer", 3600, null);
        when(authService.resetPhonePassword(request)).thenReturn(token);

        var response = controller.phonePasswordReset(request);

        assertThat(response.data()).isSameAs(token);
        verify(authService).resetPhonePassword(request);
    }
}
