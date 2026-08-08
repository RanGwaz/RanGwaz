package com.rangwaz.imagesite.config;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * Ensures a local development account exists without seeding fake content.
 */
@Component
@ConditionalOnProperty(prefix = "app.data-initializer", name = "enabled", havingValue = "true")
public class DataInitializer implements CommandLineRunner {
    private final UserMapper userMapper;
    private final String username;
    private final String password;

    /**
     * Creates the data initializer.
     *
     * @param userMapper user mapper
     * @param username explicitly configured local username
     * @param password explicitly configured local password
     */
    public DataInitializer(UserMapper userMapper,
                           @Value("${app.data-initializer.username:}") String username,
                           @Value("${app.data-initializer.password:}") String password) {
        this.userMapper = userMapper;
        this.username = username;
        this.password = password;
    }

    /**
     * Seeds only the local development user. Dataset posts are imported by tools/import_images.py.
     *
     * @param args command-line args
     */
    @Override
    public void run(String... args) {
        if (!StringUtils.hasText(username) || !StringUtils.hasText(password)) {
            throw new IllegalStateException("app.data-initializer username and password are required when enabled");
        }
        if (userMapper.findByUsername(username) != null) return;
        UserEntity user = new UserEntity();
        user.setUsername(username);
        user.setPasswordHash(PasswordHasher.hash(password));
        user.setNickname(username);
        user.setStatus("ACTIVE");
        userMapper.insert(user);
    }
}
