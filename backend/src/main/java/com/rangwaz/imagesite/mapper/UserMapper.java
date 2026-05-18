package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.UserEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Mapper for user persistence.
 */
@Mapper
public interface UserMapper {
    /**
     * Counts users.
     *
     * @return user count
     */
    @Select("SELECT COUNT(*) FROM app_users")
    long countUsers();

    /**
     * Finds a user by id.
     *
     * @param id user id
     * @return user entity
     */
    @Select("SELECT * FROM app_users WHERE id = #{id}")
    UserEntity findById(@Param("id") Long id);

    /**
     * Finds a user by username.
     *
     * @param username username
     * @return user entity
     */
    @Select("SELECT * FROM app_users WHERE username = #{username}")
    UserEntity findByUsername(@Param("username") String username);

    /**
     * Inserts a user.
     *
     * @param user user entity
     */
    @Insert("""
            INSERT INTO app_users(username,password_hash,nickname,avatar_url,bio,status)
            VALUES(#{username},#{passwordHash},#{nickname},#{avatarUrl},#{bio},#{status})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(UserEntity user);

    /**
     * Updates profile fields.
     *
     * @param user user entity
     */
    @Update("""
            UPDATE app_users
            SET nickname=#{nickname},avatar_url=#{avatarUrl},background_url=#{backgroundUrl},bio=#{bio}
            WHERE id=#{id}
            """)
    void updateProfile(UserEntity user);

    /**
     * Lists users that match a keyword.
     *
     * @param keyword search keyword
     * @param limit maximum rows
     * @return matching users
     */
    @Select("""
            SELECT * FROM app_users
            WHERE status='ACTIVE' AND (nickname LIKE CONCAT('%',#{keyword},'%') OR username LIKE CONCAT('%',#{keyword},'%'))
            ORDER BY id DESC
            LIMIT #{limit}
            """)
    List<UserEntity> search(@Param("keyword") String keyword, @Param("limit") int limit);
}
