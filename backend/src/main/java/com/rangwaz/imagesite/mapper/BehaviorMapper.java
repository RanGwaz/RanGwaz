package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.UserBehaviorEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;

/**
 * Mapper for recommendation behavior events.
 */
@Mapper
public interface BehaviorMapper {
    /**
     * Inserts a behavior event.
     *
     * @param behavior behavior entity
     */
    @Insert("""
            INSERT INTO user_behaviors(user_id,image_id,behavior_type,scene,position_no,duration_ms)
            VALUES(#{userId},#{imageId},#{behaviorType},#{scene},#{positionNo},#{durationMs})
            """)
    void insert(UserBehaviorEntity behavior);
}
