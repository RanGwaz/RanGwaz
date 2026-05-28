package com.rangwaz.imagesite.config;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.UserMapper;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

/**
 * Ensures a local development account exists without seeding fake content.
 */
@Component
public class DataInitializer implements CommandLineRunner {
    private static final String DEV_USERNAME = "mira";
    private static final String DEV_PASSWORD = "RanGwaz147..";

    private final UserMapper userMapper;

    /**
     * Creates the data initializer.
     *
     * @param userMapper user mapper
     */
    public DataInitializer(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    /**
     * Seeds only the local development user. Dataset posts are imported by tools/import_images.py.
     *
     * @param args command-line args
     */
    @Override
    public void run(String... args) {
        if (userMapper.findByUsername(DEV_USERNAME) != null) return;
        UserEntity user = new UserEntity();
        user.setUsername(DEV_USERNAME);
        user.setPasswordHash(PasswordHasher.hash(DEV_PASSWORD));
        user.setNickname(DEV_USERNAME);
        user.setStatus("ACTIVE");
        userMapper.insert(user);
    }
}
