package com.rangwaz.imagesite.mapper;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Mapper for user follow relationships.
 */
@Mapper
public interface FollowMapper {
    /**
     * Inserts a follow relationship.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @param scene source scene
     */
    @Insert("INSERT IGNORE INTO follows(follower_id,followee_id,scene) VALUES(#{followerId},#{followeeId},#{scene})")
    void follow(@Param("followerId") Long followerId, @Param("followeeId") Long followeeId, @Param("scene") String scene);

    /**
     * Deletes a follow relationship.
     *
     * @param followerId follower id
     * @param followeeId followee id
     */
    @Delete("DELETE FROM follows WHERE follower_id=#{followerId} AND followee_id=#{followeeId}")
    void unfollow(@Param("followerId") Long followerId, @Param("followeeId") Long followeeId);

    /**
     * Checks if a follow relationship exists.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @return count
     */
    @Select("SELECT COUNT(*) FROM follows WHERE follower_id=#{followerId} AND followee_id=#{followeeId}")
    int exists(@Param("followerId") Long followerId, @Param("followeeId") Long followeeId);

    /**
     * Counts users followed by a user.
     *
     * @param userId user id
     * @return following count
     */
    @Select("SELECT COUNT(*) FROM follows WHERE follower_id=#{userId}")
    long countFollowing(@Param("userId") Long userId);

    /**
     * Counts followers for a user.
     *
     * @param userId user id
     * @return follower count
     */
    @Select("SELECT COUNT(*) FROM follows WHERE followee_id=#{userId}")
    long countFollowers(@Param("userId") Long userId);
}
