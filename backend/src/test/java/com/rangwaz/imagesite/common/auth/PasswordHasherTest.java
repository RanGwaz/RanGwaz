package com.rangwaz.imagesite.common.auth;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PasswordHasherTest {
    @Test
    void newPasswordsUseAUniqueAdaptiveBcryptHash() {
        String first = PasswordHasher.hash("correct horse battery staple");
        String second = PasswordHasher.hash("correct horse battery staple");

        assertThat(first).startsWith("{bcrypt}$2");
        assertThat(second).startsWith("{bcrypt}$2");
        assertThat(second).isNotEqualTo(first);
    }

    @Test
    void bcryptMatchesOnlyTheExactRawPasswordAndNeedsNoUpgrade() {
        String hash = PasswordHasher.hash("  spaces are part of this password  ");

        assertThat(PasswordHasher.matches("  spaces are part of this password  ", hash)).isTrue();
        assertThat(PasswordHasher.matches("spaces are part of this password", hash)).isFalse();
        assertThat(PasswordHasher.needsUpgrade(hash)).isFalse();
    }

    @Test
    void legacySha256HashesStillVerifyAndAreMarkedForUpgrade() {
        String legacyHash = PasswordHasher.legacyHash("old password");

        assertThat(PasswordHasher.matches("old password", legacyHash)).isTrue();
        assertThat(PasswordHasher.matches("wrong password", legacyHash)).isFalse();
        assertThat(PasswordHasher.needsUpgrade(legacyHash)).isTrue();
    }

    @Test
    void malformedOrMissingHashesFailClosed() {
        assertThat(PasswordHasher.matches("password", null)).isFalse();
        assertThat(PasswordHasher.matches("password", "not-a-hash")).isFalse();
        assertThat(PasswordHasher.matches(null, PasswordHasher.hash("password"))).isFalse();
    }

    @Test
    void bcryptByteLimitIsCheckedBeforeEncoding() {
        String oversized = "密".repeat(25);

        assertThat(PasswordHasher.isBcryptCompatible(oversized)).isFalse();
        assertThatThrownBy(() -> PasswordHasher.hash(oversized))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
