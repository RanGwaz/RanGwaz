package com.rangwaz.imagesite.common.auth;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.regex.Pattern;

/**
 * Password hashing helper with BCrypt storage and legacy-hash migration support.
 */
public final class PasswordHasher {
    private static final String LEGACY_SALT = "rangwaz-local-dev";
    private static final String BCRYPT_PREFIX = "{bcrypt}";
    private static final Pattern LEGACY_SHA_256 = Pattern.compile("^[0-9a-f]{64}$");
    private static final BCryptPasswordEncoder BCRYPT = new BCryptPasswordEncoder(12);

    private PasswordHasher() {
    }

    /**
     * Hashes a raw password with an adaptive BCrypt hash and a unique random salt.
     *
     * @param raw raw password
     * @return hashed password
     */
    public static String hash(String raw) {
        if (raw == null) throw new IllegalArgumentException("raw password is required");
        if (!isBcryptCompatible(raw)) {
            throw new IllegalArgumentException("raw password exceeds BCrypt's 72-byte limit");
        }
        return BCRYPT_PREFIX + BCRYPT.encode(raw);
    }

    /**
     * Returns whether the raw value can be encoded by BCrypt without truncation.
     *
     * @param raw raw password
     * @return whether its UTF-8 representation is at most 72 bytes
     */
    public static boolean isBcryptCompatible(String raw) {
        return raw != null && raw.getBytes(StandardCharsets.UTF_8).length <= 72;
    }

    /**
     * Checks BCrypt hashes and the fixed-salt SHA-256 hashes created by older releases.
     *
     * @param raw raw password
     * @param expectedHash stored hash
     * @return whether the password matches
     */
    public static boolean matches(String raw, String expectedHash) {
        if (raw == null || expectedHash == null || expectedHash.isBlank()) return false;
        try {
            if (expectedHash.startsWith(BCRYPT_PREFIX)) {
                return BCRYPT.matches(raw, expectedHash.substring(BCRYPT_PREFIX.length()));
            }
            if (expectedHash.startsWith("$2")) {
                return BCRYPT.matches(raw, expectedHash);
            }
            if (LEGACY_SHA_256.matcher(expectedHash).matches()) {
                return MessageDigest.isEqual(
                        legacyHash(raw).getBytes(StandardCharsets.US_ASCII),
                        expectedHash.getBytes(StandardCharsets.US_ASCII));
            }
            return false;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    /**
     * Returns whether a successfully verified stored hash should be replaced.
     *
     * @param storedHash current stored hash
     * @return whether the hash uses a legacy or weaker format
     */
    public static boolean needsUpgrade(String storedHash) {
        if (storedHash == null || !storedHash.startsWith(BCRYPT_PREFIX)) return true;
        try {
            return BCRYPT.upgradeEncoding(storedHash.substring(BCRYPT_PREFIX.length()));
        } catch (IllegalArgumentException exception) {
            return true;
        }
    }

    static String legacyHash(String raw) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest((LEGACY_SALT + ":" + raw).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
