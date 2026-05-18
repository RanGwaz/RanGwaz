package com.rangwaz.imagesite.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Mapper for user-post interaction state.
 */
@Mapper
public interface InteractionMapper {
    /**
     * Checks if an interaction is active.
     *
     * @param userId user id
     * @param postId post id
     * @param type interaction type
     * @return active count
     */
    @Select("""
            SELECT COUNT(*) FROM user_interactions
            WHERE user_id=#{userId} AND post_id=#{postId} AND interaction_type=#{type} AND active=1
            """)
    int countActive(@Param("userId") Long userId, @Param("postId") Long postId, @Param("type") String type);

    /**
     * Upserts interaction state.
     *
     * @param userId user id
     * @param postId post id
     * @param type interaction type
     * @param active active flag
     */
    @Insert("""
            INSERT INTO user_interactions(user_id,post_id,interaction_type,active)
            VALUES(#{userId},#{postId},#{type},#{active})
            ON DUPLICATE KEY UPDATE active=#{active},updated_at=NOW()
            """)
    void upsert(@Param("userId") Long userId, @Param("postId") Long postId, @Param("type") String type, @Param("active") boolean active);
}
