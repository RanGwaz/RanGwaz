package com.rangwaz.imagesite.config;

import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DataInitializerTest {
    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withBean(UserMapper.class, () -> mock(UserMapper.class))
            .withUserConfiguration(DataInitializer.class);

    @Test
    void initializerIsDisabledByDefault() {
        contextRunner.run(context -> context.assertThat().doesNotHaveBean(DataInitializer.class));
    }

    @Test
    void initializerRequiresAnExplicitOptIn() {
        contextRunner
                .withPropertyValues(
                        "app.data-initializer.enabled=true",
                        "app.data-initializer.username=mira",
                        "app.data-initializer.password=local-only-password"
                )
                .run(context -> context.assertThat().hasSingleBean(DataInitializer.class));
    }

    @Test
    void enabledInitializerRejectsMissingCredentials() {
        DataInitializer initializer = new DataInitializer(mock(UserMapper.class), "", "");

        assertThrows(IllegalStateException.class, initializer::run);
    }

    @Test
    void existingConfiguredUserIsNotInsertedAgain() {
        UserMapper mapper = mock(UserMapper.class);
        when(mapper.findByUsername("local-user")).thenReturn(new UserEntity());
        DataInitializer initializer = new DataInitializer(mapper, "local-user", "local-password");

        initializer.run();

        verify(mapper, never()).insert(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void explicitlyConfiguredUserIsInsertedWithAHash() {
        UserMapper mapper = mock(UserMapper.class);
        DataInitializer initializer = new DataInitializer(mapper, "local-user", "local-password");
        ArgumentCaptor<UserEntity> userCaptor = ArgumentCaptor.forClass(UserEntity.class);

        initializer.run();

        verify(mapper).insert(userCaptor.capture());
        UserEntity user = userCaptor.getValue();
        assertEquals("local-user", user.getUsername());
        assertEquals("local-user", user.getNickname());
        assertEquals("ACTIVE", user.getStatus());
        assertNotEquals("local-password", user.getPasswordHash());
    }
}
