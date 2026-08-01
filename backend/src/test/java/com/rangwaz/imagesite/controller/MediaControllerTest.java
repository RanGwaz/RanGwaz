package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.common.exception.GlobalExceptionHandler;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.MediaService;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class MediaControllerTest {
    @Test
    void rejectsUploadWhenMediaUploadIsDisabled() throws Exception {
        MediaService mediaService = mock(MediaService.class);
        AuthContext authContext = mock(AuthContext.class);
        MediaController controller = new MediaController(mediaService, authContext, false);
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        MockMultipartFile file = new MockMultipartFile("file", "image.jpg", "image/jpeg", new byte[]{1});

        mockMvc.perform(multipart("/media/upload")
                        .file(file)
                        .header("Authorization", "Bearer token"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("PUBLISHING_DISABLED"));

        verifyNoInteractions(authContext, mediaService);
    }

    @Test
    void uploadsMediaWhenMediaUploadIsEnabled() {
        MediaService mediaService = mock(MediaService.class);
        AuthContext authContext = mock(AuthContext.class);
        MediaController controller = new MediaController(mediaService, authContext, true);
        MockMultipartFile file = new MockMultipartFile("file", "image.jpg", "image/jpeg", new byte[]{1});
        ApiDtos.UploadResponse uploadResponse = new ApiDtos.UploadResponse(
                "images/image.jpg", "/api/media/object/images/image.jpg", "image/jpeg",
                null, 1, 1, 1L, "hash");
        when(authContext.requireUserId("Bearer token")).thenReturn(1L);
        when(mediaService.upload(file)).thenReturn(uploadResponse);

        ApiResponse<ApiDtos.UploadResponse> response = controller.upload("Bearer token", file);

        assertThat(response.success()).isTrue();
        assertThat(response.data()).isSameAs(uploadResponse);
        verify(authContext).requireUserId("Bearer token");
        verify(mediaService).upload(file);
    }
}
