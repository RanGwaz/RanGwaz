package com.rangwaz.imagesite.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Mapper for user-image interaction state.
 */
@Mapper
public interface InteractionMapper {
    /**
     * Checks if an interaction is active.
     *
     * @param userId user id
     * @param imageId image id
     * @param type interaction type
     * @return active count
     */
    @Select("""
            SELECT COUNT(*) FROM user_interactions
            WHERE user_id=#{userId} AND image_id=#{imageId} AND interaction_type=#{type} AND active=1
            """)
    int countActive(@Param("userId") Long userId, @Param("imageId") Long imageId, @Param("type") String type);

    /**
     * Upserts interaction state.
     *
     * @param userId user id
     * @param imageId image id
     * @param type interaction type
     * @param active active flag
     */
    @Insert("""
            INSERT INTO user_interactions(user_id,image_id,interaction_type,active)
            VALUES(#{userId},#{imageId},#{type},#{active})
            ON DUPLICATE KEY UPDATE active=#{active},updated_at=NOW()
            """)
    void upsert(@Param("userId") Long userId, @Param("imageId") Long imageId, @Param("type") String type, @Param("active") boolean active);
}
