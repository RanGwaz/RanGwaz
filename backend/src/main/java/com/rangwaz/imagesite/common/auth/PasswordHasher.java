package com.rangwaz.imagesite.common.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Small password hashing helper for local development auth.
 */
public final class PasswordHasher {
    private static final String SALT = "rangwaz-local-dev";

    private PasswordHasher() {
    }

    /**
     * Hashes a raw password with SHA-256 and a local salt.
     *
     * @param raw raw password
     * @return hashed password
     */
    public static String hash(String raw) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest((SALT + ":" + raw).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    /**
     * Checks a raw password against a stored hash.
     *
     * @param raw raw password
     * @param expectedHash stored hash
     * @return whether the password matches
     */
    public static boolean matches(String raw, String expectedHash) {
        return hash(raw).equals(expectedHash);
    }
}
