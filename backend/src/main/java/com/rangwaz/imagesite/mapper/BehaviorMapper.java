package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.UserBehaviorEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

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

    /**
     * Inserts an impression row for recommendation analytics.
     *
     * @param userId optional user id
     * @param imageId image id
     * @param scene feed scene
     * @param positionNo position in feed
     * @param source recommendation source
     */
    @Insert("""
            INSERT INTO feed_impressions(user_id,image_id,scene,position_no,source)
            VALUES(#{userId},#{imageId},#{scene},#{positionNo},#{source})
            """)
    void insertFeedImpression(@Param("userId") Long userId,
                              @Param("imageId") Long imageId,
                              @Param("scene") String scene,
                              @Param("positionNo") Integer positionNo,
                              @Param("source") String source);

    /**
     * Finds recent positive behavior seed images for vector personalization.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return image ids
     */
    @Select("""
            SELECT image_id
            FROM user_behaviors
            WHERE user_id=#{userId}
              AND behavior_type IN ('favorite','like','comment','share','click','view')
              AND created_at >= DATE_SUB(NOW(), INTERVAL 60 DAY)
            GROUP BY image_id
            ORDER BY
              MAX(
                CASE behavior_type
                  WHEN 'favorite' THEN 60
                  WHEN 'like' THEN 45
                  WHEN 'comment' THEN 40
                  WHEN 'share' THEN 40
                  WHEN 'click' THEN 25
                  WHEN 'view' THEN 15
                  ELSE 1
                END
              ) DESC,
              MAX(created_at) DESC
            LIMIT #{limit}
            """)
    List<Long> findRecentPositiveImageIds(@Param("userId") Long userId, @Param("limit") int limit);
}
