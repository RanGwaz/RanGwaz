package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.ImageService;
import com.rangwaz.imagesite.service.InteractionService;
import com.rangwaz.imagesite.service.UserService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UserControllerTest {
    @Test
    void preservesExistingProfileMediaWhenMediaUploadIsDisabled() {
        UserService userService = mock(UserService.class);
        AuthContext authContext = mock(AuthContext.class);
        UserController controller = new UserController(
                userService, mock(ImageService.class), mock(InteractionService.class), authContext, false);
        when(authContext.requireUserId("Bearer token")).thenReturn(7L);

        controller.updateMe("Bearer token", new ApiDtos.UpdateProfileRequest(
                "新昵称", "https://untrusted.example/avatar.jpg", "https://untrusted.example/background.jpg", "新简介"));

        ArgumentCaptor<ApiDtos.UpdateProfileRequest> requestCaptor =
                ArgumentCaptor.forClass(ApiDtos.UpdateProfileRequest.class);
        verify(userService).updateProfile(org.mockito.ArgumentMatchers.eq(7L), requestCaptor.capture());
        ApiDtos.UpdateProfileRequest safeRequest = requestCaptor.getValue();
        assertThat(safeRequest.nickname()).isEqualTo("新昵称");
        assertThat(safeRequest.bio()).isEqualTo("新简介");
        assertThat(safeRequest.avatarUrl()).isNull();
        assertThat(safeRequest.backgroundUrl()).isNull();
    }

    @Test
    void passesProfileMediaWhenMediaUploadIsEnabled() {
        UserService userService = mock(UserService.class);
        AuthContext authContext = mock(AuthContext.class);
        UserController controller = new UserController(
                userService, mock(ImageService.class), mock(InteractionService.class), authContext, true);
        when(authContext.requireUserId("Bearer token")).thenReturn(7L);
        ApiDtos.UpdateProfileRequest request = new ApiDtos.UpdateProfileRequest(
                "新昵称", "/media/object/avatar.jpg", "/media/object/background.jpg", "新简介");

        controller.updateMe("Bearer token", request);

        ArgumentCaptor<ApiDtos.UpdateProfileRequest> requestCaptor =
                ArgumentCaptor.forClass(ApiDtos.UpdateProfileRequest.class);
        verify(userService).updateProfile(org.mockito.ArgumentMatchers.eq(7L), requestCaptor.capture());
        assertThat(requestCaptor.getValue()).isSameAs(request);
    }
}
