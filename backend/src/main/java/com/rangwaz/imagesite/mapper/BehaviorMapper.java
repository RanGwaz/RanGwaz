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
     * Checks whether an actor has recent positive history for personalization.
     */
    @Select("""
            <script>
            SELECT EXISTS(
              SELECT 1
              FROM user_behaviors
              WHERE
                <choose>
                  <when test="userId != null">user_id=#{userId}</when>
                  <otherwise>visitor_id=#{visitorId}</otherwise>
                </choose>
                AND behavior_type IN ('favorite','like','comment','share','click','view')
                AND created_at >= DATE_SUB(NOW(), INTERVAL 60 DAY)
              LIMIT 1
            )
            </script>
            """)
    int hasRecentPositiveBehavior(@Param("userId") Long userId,
                                  @Param("visitorId") String visitorId);

    /**
     * Inserts a behavior event.
     *
     * @param behavior behavior entity
     */
    @Insert("""
            INSERT IGNORE INTO user_behaviors(
              user_id,visitor_id,image_id,behavior_type,scene,position_no,duration_ms,
              decision_id,event_id,source,score,created_at
            )
            VALUES(
              #{userId},#{visitorId},#{imageId},#{behaviorType},#{scene},#{positionNo},#{durationMs},
              #{decisionId},#{eventId},#{source},#{score},COALESCE(#{occurredAt},NOW())
            )
            """)
    void insert(UserBehaviorEntity behavior);

    /**
     * Inserts an impression row for recommendation analytics.
     *
     * @param userId optional user id
     * @param visitorId optional visitor id
     * @param imageId image id
     * @param scene feed scene
     * @param positionNo position in feed
     * @param source recommendation source
     */
    @Insert("""
            INSERT IGNORE INTO feed_impressions(
              user_id,visitor_id,image_id,scene,position_no,source,score,
              decision_id,event_id,occurred_at
            )
            VALUES(
              #{userId},#{visitorId},#{imageId},#{scene},#{positionNo},#{source},#{score},
              #{decisionId},#{eventId},COALESCE(#{occurredAt},NOW())
            )
            """)
    void insertFeedImpression(@Param("userId") Long userId,
                              @Param("visitorId") String visitorId,
                              @Param("imageId") Long imageId,
                              @Param("scene") String scene,
                              @Param("positionNo") Integer positionNo,
                              @Param("source") String source,
                              @Param("score") Double score,
                              @Param("decisionId") String decisionId,
                              @Param("eventId") String eventId,
                              @Param("occurredAt") java.time.LocalDateTime occurredAt);

    /**
     * Finds recent positive behavior seed images for vector personalization.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return image ids
     */
    @Select("""
            <script>
            SELECT image_id
            FROM user_behaviors
            WHERE
              <choose>
                <when test="userId != null">user_id=#{userId}</when>
                <otherwise>visitor_id=#{visitorId}</otherwise>
              </choose>
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
            </script>
            """)
    List<Long> findRecentPositiveImageIds(@Param("userId") Long userId,
                                          @Param("visitorId") String visitorId,
                                          @Param("limit") int limit);

    /**
     * Finds the recent behavior sequence for sequence-aware recall.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return recent behavior events
     */
    @Select("""
            <script>
            SELECT image_id AS imageId,
                   behavior_type AS behaviorType,
                   COALESCE(duration_ms,0) AS durationMs,
                   TIMESTAMPDIFF(HOUR,created_at,NOW()) AS ageHours
            FROM user_behaviors
            WHERE
              <choose>
                <when test="userId != null">user_id=#{userId}</when>
                <otherwise>visitor_id=#{visitorId}</otherwise>
              </choose>
              AND behavior_type IN ('favorite','like','comment','share','click','view','impression')
              AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            ORDER BY created_at DESC,id DESC
            LIMIT #{limit}
            </script>
            """)
    List<BehaviorSequenceRow> findRecentBehaviorSequence(@Param("userId") Long userId,
                                                         @Param("visitorId") String visitorId,
                                                         @Param("limit") int limit);

    /**
     * Finds recently seen or engaged image ids for lightweight feed de-duplication.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return image ids
     */
    @Select("""
            <script>
            SELECT image_id
            FROM user_behaviors
            WHERE
              <choose>
                <when test="userId != null">user_id=#{userId}</when>
                <otherwise>visitor_id=#{visitorId}</otherwise>
              </choose>
              AND behavior_type IN ('impression','click','view','like','favorite','comment','share','unlike','unfavorite')
              AND created_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
            GROUP BY image_id
            ORDER BY MAX(created_at) DESC
            LIMIT #{limit}
            </script>
            """)
    List<Long> findRecentSeenImageIds(@Param("userId") Long userId,
                                      @Param("visitorId") String visitorId,
                                      @Param("limit") int limit);

    /**
     * Recent user event row used by the model recall adapter.
     */
    class BehaviorSequenceRow {
        private Long imageId;
        private String behaviorType;
        private Integer durationMs;
        private Integer ageHours;

        public Long getImageId() {
            return imageId;
        }

        public void setImageId(Long imageId) {
            this.imageId = imageId;
        }

        public String getBehaviorType() {
            return behaviorType;
        }

        public void setBehaviorType(String behaviorType) {
            this.behaviorType = behaviorType;
        }

        public Integer getDurationMs() {
            return durationMs;
        }

        public void setDurationMs(Integer durationMs) {
            this.durationMs = durationMs;
        }

        public Integer getAgeHours() {
            return ageHours;
        }

        public void setAgeHours(Integer ageHours) {
            this.ageHours = ageHours;
        }
    }
}
