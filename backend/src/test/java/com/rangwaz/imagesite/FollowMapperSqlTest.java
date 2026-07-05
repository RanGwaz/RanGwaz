package com.rangwaz.imagesite;

import com.rangwaz.imagesite.mapper.FollowMapper;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

class FollowMapperSqlTest {
    @Test
    void followerListQueriesUseExistingUserTableAndFollowColumns() throws Exception {
        String sql = selectSql("findFollowing") + "\n" + selectSql("findFollowers");

        assertThat(sql)
                .contains("JOIN app_users")
                .doesNotContain("JOIN users")
                .doesNotContain("f.id");
        assertThat(sql)
                .contains("ORDER BY f.created_at DESC,f.followee_id DESC")
                .contains("ORDER BY f.created_at DESC,f.follower_id DESC");
    }

    private String selectSql(String methodName) {
        Method method = Arrays.stream(FollowMapper.class.getMethods())
                .filter(candidate -> candidate.getName().equals(methodName))
                .findFirst()
                .orElseThrow();
        return String.join("\n", method.getAnnotation(Select.class).value());
    }
}
